"""Know Signal - out of range, never out of answers. A local, internet-free live quiz server.

Run:  python src/server.py [--port 80]
Host screen:  http://localhost/host   (only reachable from this laptop)
Players:      http://<laptop-ip>/      (shown as a QR code in the lobby)
"""

import argparse
import json
import os
import queue
import re
import socket
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import hotspot
from quiz_engine import Session, validate_quiz

ROOT = os.path.dirname(os.path.abspath(__file__))          # src/
PROJECT = os.path.dirname(ROOT)                            # project folder when running from source
FROZEN = getattr(sys, "frozen", False)
BUNDLE = getattr(sys, "_MEIPASS", ROOT)
STATIC = os.path.join(BUNDLE, "static")
SAMPLES = os.path.join(BUNDLE, "quizzes") if FROZEN else os.path.join(PROJECT, "quizzes")


def _documents_dir():
    """The user's real Documents folder (handles OneDrive redirection)."""
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
            return buf.value
    return os.path.join(os.path.expanduser("~"), "Documents")


if FROZEN or os.environ.get("KNOWSIGNAL_HOME"):
    # Installed app: user data lives outside Program Files so it survives updates.
    HOME = os.environ.get("KNOWSIGNAL_HOME") or os.path.join(_documents_dir(), "Know Signal")
    STATE = os.path.join(os.environ.get("LOCALAPPDATA", HOME), "KnowSignal")
    QUIZ_DIR = os.path.join(HOME, "quizzes")
    RESULTS_DIR = os.path.join(HOME, "results")
    CONFIG_PATH = os.path.join(STATE, "config.json")
else:
    # Running from source: quizzes, results and config sit in the project folder.
    HOME = STATE = PROJECT
    QUIZ_DIR = os.path.join(PROJECT, "quizzes")
    RESULTS_DIR = os.path.join(PROJECT, "results")
    CONFIG_PATH = os.path.join(PROJECT, "config.json")


def prepare_dirs():
    os.makedirs(QUIZ_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    # First run of the installed app: copy the sample quiz in.
    if os.path.abspath(QUIZ_DIR) != os.path.abspath(SAMPLES) and not os.listdir(QUIZ_DIR) and os.path.isdir(SAMPLES):
        import shutil
        for fn in os.listdir(SAMPLES):
            if fn.endswith(".json"):
                shutil.copy(os.path.join(SAMPLES, fn), QUIZ_DIR)

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json",
        ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}
PAGES = {"/": "play.html", "/host": "host.html", "/edit": "edit.html", "/favicon.ico": "favicon.svg"}
HOST_ONLY = ("/host", "/edit", "/api/host", "/api/quizzes", "/api/config", "/api/hotspot")


def local_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("127.0.0.1")
    # Windows Mobile Hotspot always uses 192.168.137.1; list it first.
    return sorted(ips, key=lambda ip: (not ip.startswith("192.168.137."), ip))


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"ssid": "", "password": ""}


SAVE_LOCK = threading.Lock()


def save_json(path, data):
    tmp = path + ".tmp"
    with SAVE_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # On Windows the replace fails while another thread is reading the file; retry briefly.
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)


class Hub:
    """Holds the active session and fans out server-sent events."""

    def __init__(self):
        self.session = None
        self.lock = threading.Lock()
        self.hosts = set()       # queues
        self.players = {}        # queue -> token

    def set_session(self, session):
        old = self.session
        self.session = session
        if old:
            self.broadcast_players(kicked=True)
        self.notify("phase")

    def notify(self, kind):
        s = self.session
        with self.lock:
            hosts = list(self.hosts)
            players = list(self.players.items())
        host_view = s.host_view() if s else {"phase": "none"}
        for q in hosts:
            q.put(("state", host_view))
        if kind in ("answer", "players"):
            return
        for q, token in players:
            q.put(("state", s.player_view(token) if s else {"phase": "none"}))
        if s and kind == "phase" and s.phase in ("reveal", "final"):
            autosave(s)

    def broadcast_players(self, kicked=False):
        with self.lock:
            players = list(self.players)
        for q in players:
            q.put(("state", {"phase": "kicked" if kicked else "none"}))

    def kick(self, token):
        with self.lock:
            targets = [q for q, t in self.players.items() if t == token]
        for q in targets:
            q.put(("state", {"phase": "kicked"}))


HUB = Hub()


def autosave(s):
    try:
        slug = re.sub(r"[^a-z0-9]+", "-", s.quiz["title"].lower()).strip("-")[:40] or "quiz"
        d = os.path.join(RESULTS_DIR, f"{s.created}-{slug}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "leaderboard.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write(s.leaderboard_csv())
        with open(os.path.join(d, "answers.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write(s.answers_csv())
    except OSError as e:
        print("autosave failed:", e, file=sys.stderr)


def quiz_path(qid):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", qid or ""):
        raise ValueError("bad quiz id")
    return os.path.join(QUIZ_DIR, qid + ".json")


def list_quizzes():
    out = []
    for fn in sorted(os.listdir(QUIZ_DIR)):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(QUIZ_DIR, fn), encoding="utf-8") as f:
                    q = json.load(f)
                out.append({"id": fn[:-5], "title": q.get("title", fn),
                            "count": len(q.get("questions", [])),
                            "mtime": os.path.getmtime(os.path.join(QUIZ_DIR, fn))})
            except (OSError, ValueError):
                pass
    return sorted(out, key=lambda q: -q["mtime"])


class Handler(BaseHTTPRequestHandler):
    server_version = "KnowSignal/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def is_local(self):
        return self.client_address[0] in self.server.local_addrs

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, msg, status=400):
        self.send_json({"error": msg}, status)

    def send_text(self, text, ctype, filename=None):
        body = ("\ufeff" + text).encode() if filename else text.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("payload too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def serve_file(self, name):
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self.send_error_json("not found", 404)
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(path)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ---------- routing ----------
    def do_GET(self):
        url = urlparse(self.path)
        p = url.path.rstrip("/") or "/"
        if p.startswith(HOST_ONLY) and not self.is_local():
            return self.send_error_json("Host pages are only available on the host laptop", 403)
        if p in PAGES:
            return self.serve_file(PAGES[p])
        if p.startswith("/static/"):
            return self.serve_file(p[len("/static/"):])
        if p == "/api/events":
            return self.sse(parse_qs(url.query).get("token", [""])[0])
        if p == "/api/host/events":
            return self.sse(None)
        if p == "/api/status":
            s = HUB.session
            return self.send_json({"open": bool(s and s.phase != "final"),
                                   "teams": bool(s and s.teams),
                                   "title": s.quiz["title"] if s else ""})
        if p == "/api/info":
            return self.send_json({"ips": local_ips(), "port": self.server.server_address[1],
                                   "config": load_config(), "app": FROZEN,
                                   "dataDir": HOME, "resultsDir": RESULTS_DIR})
        if p == "/api/hotspot":
            return self.send_json(hotspot.status())
        if p == "/api/quizzes":
            return self.send_json(list_quizzes())
        if p.startswith("/api/quizzes/"):
            try:
                with open(quiz_path(p.split("/")[-1]), encoding="utf-8") as f:
                    return self.send_json(json.load(f))
            except (OSError, ValueError):
                return self.send_error_json("quiz not found", 404)
        if p in ("/api/host/leaderboard.csv", "/api/host/answers.csv"):
            s = HUB.session
            if not s:
                return self.send_error_json("no session", 404)
            kind = p.split("/")[-1]
            text = s.leaderboard_csv() if kind == "leaderboard.csv" else s.answers_csv()
            return self.send_text(text, "text/csv; charset=utf-8", f"{s.created}-{kind}")
        self.send_error_json("not found", 404)

    def do_POST(self):
        p = urlparse(self.path).path.rstrip("/")
        if p.startswith(HOST_ONLY) and not self.is_local():
            return self.send_error_json("forbidden", 403)
        try:
            data = self.read_json()
        except ValueError:
            return self.send_error_json("bad json")
        try:
            return self.route_post(p, data)
        except ValueError as e:
            return self.send_error_json(str(e))
        except KeyError:
            return self.send_error_json("Your session expired - please rejoin", 410)
        except OSError as e:
            return self.send_error_json(f"Could not complete that: {e}", 500)

    def route_post(self, p, data):
        s = HUB.session
        if p == "/api/join":
            if not s:
                raise ValueError("The quiz hasn't been opened yet - wait for the host")
            player = s.join(data.get("name"))
            return self.send_json({"token": player.token, "name": player.name})
        if p == "/api/answer":
            if not s:
                raise KeyError()
            s.answer(data.get("token"), data.get("qi"), data.get("choice"))
            return self.send_json({"ok": True})
        if p == "/api/quizzes":
            quiz = validate_quiz(data)
            qid = data.get("id") or uuid.uuid4().hex[:10]
            quiz["id"] = qid
            save_json(quiz_path(qid), quiz)
            return self.send_json({"id": qid})
        if p == "/api/quizzes/delete":
            os.remove(quiz_path(data.get("id")))
            return self.send_json({"ok": True})
        if p == "/api/config":
            cfg = {"ssid": str(data.get("ssid", ""))[:32], "password": str(data.get("password", ""))[:63]}
            save_json(CONFIG_PATH, cfg)
            return self.send_json(cfg)
        if p == "/api/hotspot":
            if data.get("action") == "stop":
                return self.send_json(hotspot.stop())
            ssid = str(data.get("ssid", "")).strip()[:32]
            pw = str(data.get("password", ""))[:63]
            r = hotspot.start(ssid, pw)
            if r.get("ok") and r.get("ssid"):
                save_json(CONFIG_PATH, {"ssid": r["ssid"], "password": r.get("password", "")})
            return self.send_json(r)
        if p == "/api/host/quit":
            self.send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        if p == "/api/host/open-results":
            if os.name == "nt":
                os.makedirs(RESULTS_DIR, exist_ok=True)
                os.startfile(RESULTS_DIR)
            return self.send_json({"ok": True})
        if p == "/api/host/start":
            with open(quiz_path(data.get("quizId")), encoding="utf-8") as f:
                quiz = json.load(f)
            HUB.set_session(Session(quiz, teams=bool(data.get("teams")),
                                    suspense=bool(data.get("suspense", True)), on_change=HUB.notify))
            return self.send_json({"ok": True})
        if p == "/api/host/next":
            if not s:
                raise ValueError("no session")
            return self.send_json({"phase": s.advance()})
        if p == "/api/host/kick":
            if s and s.kick(data.get("token")):
                HUB.kick(data.get("token"))
            return self.send_json({"ok": True})
        if p == "/api/host/close":
            HUB.set_session(None)
            return self.send_json({"ok": True})
        self.send_error_json("not found", 404)

    # ---------- server-sent events ----------
    def sse(self, token):
        is_host = token is None
        if is_host and not self.is_local():
            return self.send_error_json("forbidden", 403)
        s = HUB.session
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = queue.Queue()
        with HUB.lock:
            if is_host:
                HUB.hosts.add(q)
            else:
                HUB.players[q] = token
        if s and not is_host:
            s.connected(token, +1)
        try:
            if is_host:
                q.put(("state", s.host_view() if s else {"phase": "none"}))
            else:
                q.put(("state", s.player_view(token) if s else {"phase": "none"}))
            self.wfile.write(b"retry: 1500\n\n")
            while True:
                try:
                    event, data = q.get(timeout=15)
                    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
                except queue.Empty:
                    event, msg = None, ": ping\n\n"
                self.wfile.write(msg.encode())
                self.wfile.flush()
                if event == "state" and data.get("phase") == "kicked":
                    break
        except (OSError, ConnectionError):
            pass
        finally:
            with HUB.lock:
                HUB.hosts.discard(q)
                HUB.players.pop(q, None)
            if s and not is_host:
                s.connected(token, -1)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256
    allow_reuse_address = False


def create_server(port=0):
    """Bind the quiz server (port 80, else 8080/8000). Returns the server, or None."""
    prepare_dirs()
    httpd = None
    for p in ([port] if port else [80, 8080, 8000]):
        try:
            httpd = Server(("0.0.0.0", p), Handler)
            break
        except OSError:
            continue
    if not httpd:
        return None
    httpd.local_addrs = {"127.0.0.1", "::1", *local_ips()}

    # Refresh local IPs periodically in case the hotspot starts after the server.
    def refresh():
        while True:
            time.sleep(5)
            httpd.local_addrs = {"127.0.0.1", "::1", *local_ips()}
    threading.Thread(target=refresh, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser(description="Know Signal quiz server")
    ap.add_argument("--port", type=int, default=0, help="default: 80, falling back to 8080")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    httpd = create_server(args.port)
    if not httpd:
        sys.exit("Could not open a port (tried 80, 8080, 8000). Close other servers or pass --port.")
    port = httpd.server_address[1]

    suffix = "" if port == 80 else f":{port}"
    print("\n  Know Signal is live. Out of range, never out of answers.")
    print(f"  Host screen : http://localhost{suffix}/host")
    print(f"  Quiz editor : http://localhost{suffix}/edit")
    for ip in local_ips():
        print(f"  Players     : http://{ip}{suffix}/")
    print("\n  Keep this window open. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(f"http://localhost{suffix}/host",)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopping...")


if __name__ == "__main__":
    main()
