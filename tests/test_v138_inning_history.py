from __future__ import annotations

import unittest

from v11 import v138_inning_history as inning


class V138InningHistoryTests(unittest.TestCase):
    def _game(self, i: int, extra: bool) -> dict:
        n = 10 if extra else 9
        innings = []
        for j in range(n):
            innings.append({"home": {"runs": 1 if (i + j) % 5 == 0 else 0},
                            "away": {"runs": 1 if (i + j) % 7 == 0 else 0}})
        hs = sum(x["home"]["runs"] for x in innings)
        aws = sum(x["away"]["runs"] for x in innings)
        if extra and hs == aws:
            hs += 1
            innings[-1]["home"]["runs"] += 1
        if not extra and hs == aws:
            hs += 1
            innings[-1]["home"]["runs"] += 1
        return {
            "gamePk": 100000 + i,
            "gameType": "R",
            "gameDate": f"2025-06-{(i % 27) + 1:02d}T19:00:00Z",
            "officialDate": f"2025-06-{(i % 27) + 1:02d}",
            "status": {"abstractGameState": "Final", "codedGameState": "F"},
            "teams": {"home": {"score": hs}, "away": {"score": aws}},
            "linescore": {"currentInning": n, "innings": innings},
        }

    def test_200_authenticated_extras_activate_shrunk_prior(self):
        games = [self._game(i, i < 200) for i in range(300)]
        payload = inning.collect(games, per_season_inning_target=300, fetch_feed=False)
        prior = payload["extra_inning_prior"]
        profile = payload["inning_profile"]
        self.assertEqual(len(payload["extras"]), 200)
        self.assertTrue(prior["active"])
        self.assertEqual(prior["n"], 200)
        self.assertTrue(.45 <= prior["home_probability"] <= .55)
        self.assertTrue(profile["active"])
        self.assertEqual(profile["n"], 300)
        self.assertAlmostEqual(sum(profile["home_shares"]), 1.0, places=7)
        self.assertAlmostEqual(sum(profile["away_shares"]), 1.0, places=7)

    def test_non_extra_and_nonfinal_games_never_enter_extra_prior(self):
        game = self._game(1, False)
        self.assertIsNone(inning.extract_extra(game))
        game["status"] = {"abstractGameState": "Live"}
        self.assertIsNone(inning.extract_extra(game))


if __name__ == "__main__":
    unittest.main()
