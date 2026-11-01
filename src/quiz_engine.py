"""Quiz session state machine. Pure logic, no networking, so it can be unit-tested."""

import csv
import io
import secrets
import threading
import time

READY_SECONDS = 3.0
GRACE_SECONDS = 0.5
MAX_NAME_LEN = 20
LETTERS = "ABCD"

PHASES = ("lobby", "question", "reveal", "leaderboard", "final")


def score_for(elapsed, limit):
    """Correct answers earn 1000 at t=0 down to 500 at the buzzer."""
    frac = min(max(elapsed / limit, 0.0), 1.0)
    return int(round(1000 * (1 - frac / 2)))


def validate_quiz(quiz):
    if not isinstance(quiz, dict):
        raise ValueError("Quiz must be an object")
    title = str(quiz.get("title", "")).strip()
    if not title:
        raise ValueError("Quiz needs a title")
    questions = quiz.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Quiz needs at least one question")
    clean = []
    for i, q in enumerate(questions, 1):
        text = str(q.get("text", "")).strip()
        opts = [str(o).strip() for o in q.get("options", [])]
        if not text:
            raise ValueError(f"Question {i} has no text")
        if not 2 <= len(opts) <= 4 or any(not o for o in opts):
            raise ValueError(f"Question {i} needs 2-4 non-empty options")
        correct = q.get("correct")
        if not isinstance(correct, int) or not 0 <= correct < len(opts):
            raise ValueError(f"Question {i} needs a correct option")
        t = int(q.get("time", 20))
        if not 5 <= t <= 120:
            raise ValueError(f"Question {i} time must be 5-120 seconds")
        clean.append({"text": text, "options": opts, "correct": correct, "time": t})
    return {"id": quiz.get("id"), "title": title, "questions": clean}


class Player:
    def __init__(self, name):
        self.token = secrets.token_urlsafe(12)
        self.name = name
        self.score = 0
        self.answers = {}  # qi -> {choice, ms, points, correct}
        self.connections = 0


class Session:
    def __init__(self, quiz, teams=False, suspense=True, clock=time.monotonic, on_change=None):
        self.quiz = validate_quiz(quiz)
        self.teams = teams
        self.suspense = suspense
        self.clock = clock
        self.on_change = on_change or (lambda kind: None)
        self.lock = threading.RLock()
        self.phase = "lobby"
        self.qi = -1
        self.players = {}
        self.ready_until = 0.0
        self.ends_at = 0.0
        self.prev_ranks = {}
        self._timer = None
        self.created = time.strftime("%Y%m%d-%H%M%S")

    # ---------- players ----------
    def join(self, name):
        name = " ".join(str(name or "").split())[:MAX_NAME_LEN]
        if not name:
            raise ValueError("Enter a name")
        with self.lock:
            if self.phase == "final":
                raise ValueError("This quiz has ended")
            if any(p.name.lower() == name.lower() for p in self.players.values()):
                raise ValueError("That name is taken - try another")
            p = Player(name)
            self.players[p.token] = p
        self.on_change("players")
        return p

    def kick(self, token):
        with self.lock:
            p = self.players.pop(token, None)
        if p:
            self.on_change("players")
        return p

    def connected(self, token, delta):
        with self.lock:
            p = self.players.get(token)
            if p:
                p.connections = max(0, p.connections + delta)

    # ---------- flow ----------
    @property
    def total(self):
        return len(self.quiz["questions"])

    @property
    def question(self):
        if 0 <= self.qi < self.total:
            return self.quiz["questions"][self.qi]
        return None

    def after_reveal(self):
        """What follows the answer reveal for the current question."""
        if self.qi + 1 >= self.total:
            return "final"
        if self.suspense and self.qi + 2 >= self.total:
            return "question"  # no leaderboard after the penultimate question
        return "leaderboard"

    def hide_ranks(self):
        """In suspense mode, standings stay secret from the penultimate question on."""
        return self.suspense and self.total >= 2 and self.qi + 2 >= self.total

    def fastest(self):
        best = None
        for p in self.players.values():
            a = p.answers.get(self.qi)
            if a and a["correct"] and (best is None or a["ms"] < best[1]):
                best = (p.token, a["ms"])
        return best[0] if best else None

    def advance(self):
        """Host pressed Next. Returns the new phase."""
        with self.lock:
            if self.phase == "lobby" or self.phase == "leaderboard":
                if self.qi + 1 >= self.total:
                    self.phase = "final"
                else:
                    self._start_question(self.qi + 1)
            elif self.phase == "question":
                self._end_question()
            elif self.phase == "reveal":
                after = self.after_reveal()
                if after == "question":
                    self._start_question(self.qi + 1)
                else:
                    self.phase = after
            phase = self.phase
        self.on_change("phase")
        return phase

    def _start_question(self, qi):
        self.prev_ranks = {t: r for r, t in enumerate(self._ranked_tokens(), 1)}
        self.qi = qi
        self.phase = "question"
        now = self.clock()
        self.ready_until = now + READY_SECONDS
        self.ends_at = self.ready_until + self.question["time"]
        self._schedule(self.ends_at - now + GRACE_SECONDS)

    def _schedule(self, delay):
        if self._timer:
            self._timer.cancel()
        qi = self.qi
        self._timer = threading.Timer(delay, self._timeout, args=(qi,))
        self._timer.daemon = True
        self._timer.start()

    def _timeout(self, qi):
        with self.lock:
            if self.phase != "question" or self.qi != qi:
                return
            self._end_question()
        self.on_change("phase")

    def _end_question(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.phase = "reveal"

    def answer(self, token, qi, choice):
        with self.lock:
            p = self.players.get(token)
            if not p:
                raise KeyError("unknown player")
            if self.phase != "question" or qi != self.qi:
                raise ValueError("Not accepting answers right now")
            now = self.clock()
            if now < self.ready_until:
                raise ValueError("Wait for the options")
            if now > self.ends_at + GRACE_SECONDS:
                raise ValueError("Time's up")
            if qi in p.answers:
                raise ValueError("Already answered")
            q = self.question
            if not isinstance(choice, int) or not 0 <= choice < len(q["options"]):
                raise ValueError("Invalid option")
            elapsed = min(now - self.ready_until, q["time"])
            correct = choice == q["correct"]
            pts = score_for(elapsed, q["time"]) if correct else 0
            p.answers[qi] = {"choice": choice, "ms": int(elapsed * 1000),
                             "points": pts, "correct": correct}
            p.score += pts
            everyone = all(qi in x.answers for x in self.players.values()
                           if x.connections > 0 or qi in x.answers)
            if everyone:
                self._end_question()
        self.on_change("phase" if everyone else "answer")

    # ---------- views ----------
    def _ranked_tokens(self):
        return [p.token for p in sorted(self.players.values(),
                                        key=lambda p: (-p.score, p.name.lower()))]

    def ranks(self):
        return {t: r for r, t in enumerate(self._ranked_tokens(), 1)}

    def remaining(self):
        now = self.clock()
        return {"readyMs": int(max(0, self.ready_until - now) * 1000),
                "remainingMs": int(max(0, self.ends_at - now) * 1000)}

    def distribution(self):
        q = self.question
        counts = [0] * len(q["options"]) if q else []
        for p in self.players.values():
            a = p.answers.get(self.qi)
            if a:
                counts[a["choice"]] += 1
        return counts

    def host_view(self):
        with self.lock:
            v = {"phase": self.phase, "qi": self.qi, "total": self.total,
                 "title": self.quiz["title"], "teams": self.teams,
                 "playerCount": len(self.players)}
            if self.phase == "lobby":
                v["players"] = [{"token": p.token, "name": p.name}
                                for p in self.players.values()]
            q = self.question
            if q and self.phase in ("question", "reveal"):
                v["question"] = {"text": q["text"], "options": q["options"], "time": q["time"]}
                v["answered"] = sum(1 for p in self.players.values() if self.qi in p.answers)
            if self.phase == "question":
                v.update(self.remaining())
            if self.phase == "reveal":
                v["question"]["correct"] = q["correct"]
                v["distribution"] = self.distribution()
                v["afterReveal"] = self.after_reveal()
                f = self.fastest()
                if f:
                    v["fastest"] = {"name": self.players[f].name, "ms": self.players[f].answers[self.qi]["ms"]}
            if self.phase in ("leaderboard", "final"):
                ranks = self.ranks()
                fastest = self.fastest()
                shown = {t for t, r in ranks.items() if r <= 10}
                shown |= {t for t, r in self.prev_ranks.items() if r <= 10 and t in ranks}
                rows = []
                for t in shown:
                    p = self.players[t]
                    gained = p.answers.get(self.qi, {}).get("points", 0)
                    rows.append({"name": p.name, "score": p.score, "rank": ranks[t],
                                 "prevScore": p.score - gained, "prevRank": self.prev_ranks.get(t),
                                 "gained": gained, "fastest": t == fastest})
                v["leaderboard"] = sorted(rows, key=lambda r: r["rank"])
            return v

    def player_view(self, token):
        with self.lock:
            if not token:
                return {"phase": "none"}
            p = self.players.get(token)
            if not p:
                return {"phase": "kicked"}
            v = {"phase": self.phase, "qi": self.qi, "total": self.total,
                 "title": self.quiz["title"], "teams": self.teams,
                 "me": {"name": p.name, "score": p.score}}
            q = self.question
            if q and self.phase == "question":
                v["question"] = {"text": q["text"], "options": q["options"], "time": q["time"]}
                v.update(self.remaining())
                a = p.answers.get(self.qi)
                v["me"]["choice"] = a["choice"] if a else None
            if q and self.phase in ("reveal", "leaderboard", "final") and self.qi >= 0:
                a = p.answers.get(self.qi)
                v["me"]["last"] = {"answered": bool(a), "correct": bool(a and a["correct"]),
                                   "points": a["points"] if a else 0,
                                   "correctText": q["options"][q["correct"]],
                                   "ms": a["ms"] if a else None,
                                   "fastest": self.fastest() == token}
            if self.phase in ("reveal", "leaderboard", "final"):
                v["me"]["of"] = len(self.players)
                if self.phase == "final" or not self.hide_ranks():
                    v["me"]["rank"] = self.ranks()[token]
            return v

    # ---------- export ----------
    def leaderboard_csv(self):
        with self.lock:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["rank", "team" if self.teams else "name", "score",
                        "correct", "answered", "questions_asked"])
            ranks = self.ranks()
            asked = max(0, self.qi + 1)
            for p in sorted(self.players.values(), key=lambda p: ranks[p.token]):
                w.writerow([ranks[p.token], p.name, p.score,
                            sum(1 for a in p.answers.values() if a["correct"]),
                            len(p.answers), asked])
            return buf.getvalue()

    def answers_csv(self):
        with self.lock:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["team" if self.teams else "name", "question_no", "question",
                        "answer", "answer_text", "correct_answer", "is_correct",
                        "response_ms", "points"])
            for p in sorted(self.players.values(), key=lambda p: p.name.lower()):
                for qi in range(max(0, self.qi + 1)):
                    q = self.quiz["questions"][qi]
                    a = p.answers.get(qi)
                    w.writerow([p.name, qi + 1, q["text"],
                                LETTERS[a["choice"]] if a else "",
                                q["options"][a["choice"]] if a else "",
                                LETTERS[q["correct"]],
                                a["correct"] if a else False,
                                a["ms"] if a else "", a["points"] if a else 0])
            return buf.getvalue()
