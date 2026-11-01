import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from quiz_engine import READY_SECONDS, Session, score_for, validate_quiz  # noqa: E402

QUIZ = {"title": "T", "questions": [
    {"text": "Q1", "options": ["a", "b", "c", "d"], "correct": 1, "time": 20},
    {"text": "Q2", "options": ["x", "y"], "correct": 0, "time": 10},
]}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(**kw):
    clock = Clock()
    s = Session(QUIZ, clock=clock, **kw)
    return s, clock


class ScoringTests(unittest.TestCase):
    def test_score_range(self):
        self.assertEqual(score_for(0, 20), 1000)
        self.assertEqual(score_for(20, 20), 500)
        self.assertEqual(score_for(10, 20), 750)
        self.assertEqual(score_for(99, 20), 500)


class ValidationTests(unittest.TestCase):
    def test_rejects_bad_quizzes(self):
        for bad in [{}, {"title": "x", "questions": []},
                    {"title": "x", "questions": [{"text": "q", "options": ["a"], "correct": 0}]},
                    {"title": "x", "questions": [{"text": "q", "options": ["a", "b"], "correct": 2}]},
                    {"title": "x", "questions": [{"text": "", "options": ["a", "b"], "correct": 0}]}]:
            with self.assertRaises(ValueError):
                validate_quiz(bad)

    def test_accepts_and_cleans(self):
        q = validate_quiz({"title": " T ", "questions": [{"text": " q ", "options": [" a", "b "], "correct": 1}]})
        self.assertEqual(q["title"], "T")
        self.assertEqual(q["questions"][0], {"text": "q", "options": ["a", "b"], "correct": 1, "time": 20})


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.s, self.clock = make(suspense=False)
        self.a = self.s.join("Asha")
        self.b = self.s.join("Bilal")
        for p in (self.a, self.b):
            self.s.connected(p.token, +1)

    def tearDown(self):
        if self.s._timer:
            self.s._timer.cancel()

    def test_unique_names(self):
        with self.assertRaises(ValueError):
            self.s.join("asha")
        with self.assertRaises(ValueError):
            self.s.join("   ")

    def test_full_game(self):
        s, c = self.s, self.clock
        self.assertEqual(s.advance(), "question")
        with self.assertRaises(ValueError):
            s.answer(self.a.token, 0, 1)  # still in "get ready"
        c.t += READY_SECONDS + 2
        s.answer(self.a.token, 0, 1)
        self.assertEqual(self.a.score, score_for(2, 20))
        with self.assertRaises(ValueError):
            s.answer(self.a.token, 0, 0)  # answers are final
        self.assertEqual(s.phase, "question")
        s.answer(self.b.token, 0, 0)  # wrong; everyone answered -> reveal
        self.assertEqual(s.phase, "reveal")
        self.assertEqual(self.b.score, 0)
        self.assertEqual(s.host_view()["distribution"], [1, 1, 0, 0])
        self.assertEqual(s.advance(), "leaderboard")
        lb = s.host_view()["leaderboard"]
        self.assertEqual([r["name"] for r in lb], ["Asha", "Bilal"])
        self.assertEqual(s.advance(), "question")
        self.assertEqual(s.qi, 1)
        self.assertEqual(s.advance(), "reveal")  # host skips the timer
        self.assertEqual(s.advance(), "final")
        me = s.player_view(self.b.token)["me"]
        self.assertEqual((me["rank"], me["of"]), (2, 2))
        self.assertFalse(me["last"]["answered"])

    def test_late_answer_rejected(self):
        self.s.advance()
        self.clock.t += READY_SECONDS + 21
        with self.assertRaises(ValueError):
            self.s.answer(self.a.token, 0, 1)

    def test_disconnected_players_do_not_block_early_end(self):
        self.s.connected(self.b.token, -1)
        self.s.advance()
        self.clock.t += READY_SECONDS + 1
        self.s.answer(self.a.token, 0, 1)
        self.assertEqual(self.s.phase, "reveal")

    def test_player_view_hides_correct_answer_during_question(self):
        self.s.advance()
        v = self.s.player_view(self.a.token)
        self.assertNotIn("correct", v["question"])
        self.assertEqual(self.s.player_view("nope")["phase"], "kicked")
        self.assertEqual(self.s.player_view("")["phase"], "none")

    def test_csv_exports(self):
        self.s.advance()
        self.clock.t += READY_SECONDS + 1
        self.s.answer(self.a.token, 0, 1)
        self.s.advance()
        lb = self.s.leaderboard_csv().splitlines()
        self.assertTrue(lb[1].startswith("1,Asha,"))
        ans = self.s.answers_csv().splitlines()
        self.assertEqual(len(ans), 3)
        self.assertIn("Asha,1,Q1,B,b,B,True,1000", ans[1])

    def test_kick(self):
        self.s.kick(self.b.token)
        self.assertEqual(self.s.player_view(self.b.token)["phase"], "kicked")
        self.s.join("Bilal")  # name freed


class SuspenseAndLeaderboardTests(unittest.TestCase):
    QUIZ4 = {"title": "T", "questions": [
        {"text": f"Q{i}", "options": ["a", "b"], "correct": 0, "time": 20} for i in range(4)]}

    def setUp(self):
        self.clock = Clock()
        self.s = Session(self.QUIZ4, clock=self.clock)  # suspense on by default
        self.a, self.b = self.s.join("Asha"), self.s.join("Bilal")
        for p in (self.a, self.b):
            self.s.connected(p.token, +1)

    def tearDown(self):
        if self.s._timer:
            self.s._timer.cancel()

    def play(self, a_delay, b_choice, b_delay):
        self.assertEqual(self.s.phase, "question")
        self.clock.t += READY_SECONDS + a_delay
        self.s.answer(self.a.token, self.s.qi, 0)
        self.clock.t += b_delay
        self.s.answer(self.b.token, self.s.qi, b_choice)
        self.assertEqual(self.s.phase, "reveal")

    def test_no_leaderboard_after_penultimate_and_ranks_hidden(self):
        s = self.s
        s.advance()
        phases = []
        for _ in range(4):
            self.play(1, 0, 1)
            if s.qi >= 2:
                self.assertNotIn("rank", s.player_view(self.a.token)["me"])
            else:
                self.assertIn("rank", s.player_view(self.a.token)["me"])
            phases.append(s.advance())
            if phases[-1] == "leaderboard":
                s.advance()
        self.assertEqual(phases, ["leaderboard", "leaderboard", "question", "final"])
        self.assertEqual(s.player_view(self.a.token)["me"]["rank"], 1)

    def test_opt_out_shows_every_leaderboard(self):
        s = Session(self.QUIZ4, suspense=False, clock=self.clock)
        s.join("X")
        s.advance()
        s.qi = 2
        s.phase = "reveal"
        self.assertEqual(s.after_reveal(), "leaderboard")

    def test_fastest_and_previous_scores(self):
        s = self.s
        s.advance()
        self.play(5, 0, 1)            # Asha first; Bilal later but also correct
        s.advance()
        s.advance()                    # Q2
        self.clock.t += READY_SECONDS + 1
        s.answer(self.b.token, 1, 0)   # Bilal fastest this round
        self.clock.t += 2
        s.answer(self.a.token, 1, 0)
        s.advance()                    # leaderboard
        rows = {r["name"]: r for r in s.host_view()["leaderboard"]}
        self.assertTrue(rows["Bilal"]["fastest"])
        self.assertFalse(rows["Asha"]["fastest"])
        for r in rows.values():
            self.assertEqual(r["prevScore"] + r["gained"], r["score"])
            self.assertIsNotNone(r["prevRank"])
        self.assertTrue(s.player_view(self.b.token)["me"]["last"]["fastest"])


if __name__ == "__main__":
    unittest.main()
