import json
import unittest

from engine import rules

CFG = json.load(open("config.json"))["rules"]
_id = [0]


def g(date, h, a, hg, ag, season=2025):
    _id[0] += 1
    return {"id": _id[0], "date": f"{date}T15:00:00+00:00", "season": season, "league_id": 1,
            "home_id": h, "away_id": a, "home": f"T{h}", "away": f"T{a}", "hg": hg, "ag": ag}


FIX = {"home_id": 1, "away_id": 2, "home": "T1", "away": "T2", "date": "2026-03-01T15:00:00+00:00", "season": 2025}


def strong_home():
    """Team 1: 4W1D last 5, 12 goals; beat 10 and 11, team 2 drew 10 and lost 11; won last 2 H2H."""
    return [
        g("2026-02-20", 1, 10, 3, 0), g("2026-02-13", 11, 1, 1, 2), g("2026-02-06", 1, 12, 2, 2),
        g("2026-01-30", 1, 13, 3, 1), g("2026-01-23", 14, 1, 0, 2),
        g("2026-02-21", 2, 10, 1, 1), g("2026-02-14", 11, 2, 2, 0), g("2026-02-07", 2, 15, 1, 0),
        g("2026-01-31", 16, 2, 0, 0), g("2026-01-24", 2, 17, 2, 1),
        g("2025-11-01", 1, 2, 2, 0), g("2025-04-01", 2, 1, 0, 1, season=2024),
    ]


class Rules(unittest.TestCase):
    def test_home_three_of_three_is_straight_win(self):
        ev = rules.evaluate(FIX, strong_home(), CFG)
        self.assertEqual((ev["verdict"], ev["backed"]), ("1", "home"))
        self.assertEqual(ev["home"]["gate"]["goals"], 12)
        self.assertEqual(ev["home"]["form"]["string"], "WWDWW")

    def test_gate_fail_cuts(self):
        games = [x for x in strong_home()]
        for x in games:  # team 1 home goals -> 1 each, so 1+2+1+1+2 = 7 in last 5
            if x["home_id"] == 1:
                x["hg"] = 1
        ev = rules.evaluate(FIX, games, CFG)
        self.assertFalse(ev["home"]["gate"]["pass"])
        self.assertIsNone(ev["verdict"])

    def test_home_two_of_three_is_1x(self):
        games = [x for x in strong_home() if not ({x["home_id"], x["away_id"]} == {1, 2} and x["season"] == 2024)]
        ev = rules.evaluate(FIX, games, CFG)  # only 1 H2H meeting -> rule 2 fails
        self.assertFalse(ev["home"]["r2"])
        self.assertEqual(ev["verdict"], "1X")

    def test_away_mirror_is_x2_and_away_two_is_cut(self):
        fx = dict(FIX, home_id=2, away_id=1, home="T2", away="T1")
        ev = rules.evaluate(fx, strong_home(), CFG)
        self.assertEqual((ev["verdict"], ev["backed"]), ("X2", "away"))
        games = [x for x in strong_home() if not ({x["home_id"], x["away_id"]} == {1, 2} and x["season"] == 2024)]
        ev = rules.evaluate(fx, games, CFG)
        self.assertIsNone(ev["verdict"])
        self.assertIn("Away 2/3", ev["reason"])

    def test_common_opponents_mixed_fails(self):
        games = strong_home() + [g("2026-02-25", 2, 13, 3, 0)]  # team 2 beat 13 (team 1 also beat 13) -> level
        games += [g("2026-02-26", 2, 14, 2, 0)]  # team 2 beat 14, team 1 beat 14 -> level
        games += [g("2026-02-27", 2, 12, 3, 0)]  # team 2 beat 12, team 1 drew 12 -> team 2 better
        ev = rules.evaluate(FIX, games, CFG)
        self.assertFalse(ev["home"]["r1"])
        self.assertFalse(ev["away"]["r1"])

    def test_form_runs(self):
        def run(s):
            res = []
            for i, c in enumerate(s):
                hg, ag = {"W": (1, 0), "D": (0, 0), "L": (0, 1)}[c]
                res.append(g(f"2026-02-{20 - i:02d}", 1, 30 + i, hg, ag))
            return rules.form(res, 1, CFG)["pass"]
        for ok in ["WWWWW", "WWWWD", "WWWWL", "WWWDD", "WWWDL"]:
            self.assertTrue(run(ok), ok)
        for bad in ["WWDDD", "WWWLL", "WWLDD", "WWDLL"]:
            self.assertFalse(run(bad), bad)

    def test_old_h2h_outside_window_ignored(self):
        games = strong_home() + [g("2023-03-01", 1, 2, 5, 0, season=2022)]
        hh = rules.head_to_head(games, 1, 2, {2025, 2024}, FIX["date"], CFG)
        self.assertEqual(len(hh["meetings"]), 2)


if __name__ == "__main__":
    unittest.main()
