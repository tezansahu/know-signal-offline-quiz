"""Rehearsal / load-test tool: fake phones that play against an already-running quiz server.

Start the server first (start-quiz.bat), then in a second terminal:
  python scripts\simulate.py --players 40            # bots join once you click "Open the room"; you drive from /host
  python scripts\simulate.py --players 150 --drive   # fully automatic self-test (opens a session and advances itself)
"""

import argparse
import http.client
import json
import random
import threading
import time
from urllib.parse import urlparse


class Bot(threading.Thread):
    def __init__(self, base, name, stats):
        super().__init__(daemon=True)
        self.base, self.name, self.stats = base, name, stats
        self.token = None
        self.answered = set()
        self.last_phase = None

    def conn(self):
        u = urlparse(self.base)
        return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=60)

    def post(self, path, body):
        c = self.conn()
        c.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        return r.status, data

    def run(self):
        try:
            self._run()
        except (OSError, ValueError) as e:
            self.stats["errors"].append(f"{type(e).__name__}: {e}")
            if not self.token:
                self.stats["join_fail"] += 1

    def _run(self):
        status, data = self.post("/api/join", {"name": self.name})
        if status != 200:
            self.stats["join_fail"] += 1
            self.stats["errors"].append(data.get("error", f"HTTP {status}"))
            return
        self.token = data["token"]
        self.stats["joined"] += 1
        c = self.conn()
        c.request("GET", f"/api/events?token={self.token}")
        r = c.getresponse()
        buf = b""
        while True:
            line = r.fp.readline()
            if not line:
                break
            buf += line
            if line in (b"\n", b"\r\n"):
                for ln in buf.decode().splitlines():
                    if ln.startswith("data: "):
                        self.on_state(json.loads(ln[6:]))
                buf = b""
                if self.last_phase in ("final", "kicked"):
                    break

    def on_state(self, s):
        self.last_phase = s.get("phase")
        if s.get("phase") == "question" and s["qi"] not in self.answered:
            self.answered.add(s["qi"])
            delay = s["readyMs"] / 1000 + random.uniform(0.3, s["question"]["time"] * 0.8)
            choice = random.randrange(len(s["question"]["options"]))
            threading.Timer(delay, self.answer, args=(s["qi"], choice)).start()
        if s.get("phase") == "final":
            self.stats["finished"] += 1
            self.stats["scores"].append(s["me"]["score"])

    def answer(self, qi, choice):
        t0 = time.perf_counter()
        try:
            status, _ = self.post("/api/answer", {"token": self.token, "qi": qi, "choice": choice})
        except OSError as e:
            self.stats["errors"].append(f"{type(e).__name__}: {e}")
            status = 0
        self.stats["latency"].append(time.perf_counter() - t0)
        self.stats["answers_ok" if status == 200 else "answers_fail"] += 1


def find_server(url):
    """Return (base_url, status) for a running quiz server, or exit with a clear message."""
    candidates = [url] if url else [f"http://127.0.0.1:{p}" for p in (80, 8080, 8000)]
    for base in candidates:
        try:
            return base, host(base, "/api/status")
        except (OSError, ValueError):
            continue
    where = url or "ports 80, 8080 or 8000 on this laptop"
    raise SystemExit(f"\nNo quiz server found at {where}.\n"
                     "Start it first (double-click start-quiz.bat) and keep that window open,\n"
                     "then run scripts\\simulate.py again from a second terminal.\n")


def host(base, path, body=None):
    u = urlparse(base)
    c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=30)
    if body is None:
        c.request("GET", path)
    else:
        c.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
    r = c.getresponse()
    data = json.loads(r.read() or b"{}")
    c.close()
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="server address (default: find it on this laptop)")
    ap.add_argument("--players", type=int, default=50)
    ap.add_argument("--drive", action="store_true", help="start a session and advance automatically")
    ap.add_argument("--quiz", default="sample-ai-basics")
    args = ap.parse_args()

    args.url, status = find_server(args.url)
    print(f"Quiz server found at {args.url}")
    stats = {"joined": 0, "join_fail": 0, "answers_ok": 0, "answers_fail": 0,
             "finished": 0, "latency": [], "scores": [], "errors": []}
    if args.drive:
        host(args.url, "/api/host/start", {"quizId": args.quiz})
    elif not status.get("open"):
        print("Waiting for you to click 'Open the room' on the host screen (Ctrl+C to cancel)...")
        while not host(args.url, "/api/status").get("open"):
            time.sleep(1)
    run_id = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=2))
    bots = [Bot(args.url, f"Bot {run_id}{i:03d}", stats) for i in range(args.players)]
    t0 = time.time()
    for b in bots:
        b.start()
    while stats["joined"] + stats["join_fail"] < args.players and time.time() - t0 < 30:
        time.sleep(0.2)
    print(f"joined {stats['joined']}/{args.players} in {time.time() - t0:.1f}s (failed {stats['join_fail']})")
    if stats["errors"]:
        common = max(set(stats["errors"]), key=stats["errors"].count)
        print(f"  most common problem ({stats['errors'].count(common)}x): {common}")

    if args.drive:
        time.sleep(1)
        quiz = host(args.url, f"/api/quizzes/{args.quiz}")
        host(args.url, "/api/host/next", {})  # lobby -> Q1
        for qi in range(len(quiz["questions"])):
            limit = quiz["questions"][qi]["time"] + 5
            start = time.time()
            while time.time() - start < limit and stats["answers_ok"] + stats["answers_fail"] < (qi + 1) * stats["joined"]:
                time.sleep(0.2)
            time.sleep(1)
            print(f"Q{qi + 1}: answers so far {stats['answers_ok']} ok / {stats['answers_fail']} failed "
                  f"({time.time() - start:.1f}s)")
            if host_phase(args.url) == "question":
                host(args.url, "/api/host/next", {})  # -> reveal
            # reveal -> leaderboard -> next question, or straight on (suspense), or final
            while host_phase(args.url) in ("reveal", "leaderboard"):
                host(args.url, "/api/host/next", {})
            time.sleep(0.3)
        time.sleep(2)
        lat = sorted(stats["latency"])
        if lat:
            print(f"answer latency p50={lat[len(lat) // 2] * 1000:.0f}ms p95={lat[int(len(lat) * .95)] * 1000:.0f}ms "
                  f"max={lat[-1] * 1000:.0f}ms")
        print(f"finished {stats['finished']}/{stats['joined']}  top score {max(stats['scores'] or [0])}")
        ok = stats["finished"] == stats["joined"] == args.players and stats["answers_fail"] == 0
        print("RESULT:", "PASS" if ok else "FAIL")
        raise SystemExit(0 if ok else 1)
    else:
        print("Bots are connected. Drive the quiz from the host screen; Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def host_phase(base):
    # The host event stream is the source of truth; peek via a short read.
    u = urlparse(base)
    c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=10)
    c.request("GET", "/api/host/events")
    r = c.getresponse()
    while True:
        line = r.fp.readline().decode()
        if line.startswith("data: "):
            c.close()
            return json.loads(line[6:])["phase"]


if __name__ == "__main__":
    main()
