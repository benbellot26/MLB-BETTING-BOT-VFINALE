from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import v124_historical_daily_reconstruction as daily
from v11 import v124_historical_reconstruction as base


class HistoricalDailyFreezeTests(unittest.TestCase):
    def test_same_date_games_do_not_see_each_others_results(self):
        rows = [
            {"game_pk": 1, "game_date": "2026-05-01T17:00:00Z", "home": "H1", "away": "A1", "home_score": 5, "away_score": 3,
             "v10": {"home_struct": 4.5, "away_struct": 4.2}, "starters": {}},
            {"game_pk": 2, "game_date": "2026-05-01T23:00:00Z", "home": "H2", "away": "A2", "home_score": 4, "away_score": 2,
             "v10": {"home_struct": 4.4, "away_struct": 4.1}, "starters": {}},
            {"game_pk": 3, "game_date": "2026-05-02T18:00:00Z", "home": "H3", "away": "A3", "home_score": 2, "away_score": 1,
             "v10": {"home_struct": 4.3, "away_struct": 4.0}, "starters": {}},
        ]
        boxes = {str(i): {"teams": {"home": {"team": {"id": i*10+1}, "players": {}}, "away": {"team": {"id": i*10+2}, "players": {}}}} for i in (1, 2, 3)}
        seen = []

        def fake_build(row, box, state):
            seen.append((row["game_pk"], sum(v["gamesPitched"] for v in state.pitching.values())))
            return {"ctx": {"home": row["home"]}, "features": {}, "options": [{"market": "ML", "name": row["home"], "point": None}]}

        neutral = {name: {"status": "UNAVAILABLE", "coverage": 0.0, "home_factor": 1.0, "away_factor": 1.0} for name in base.MODULES}
        with patch.object(base, "_build_result", side_effect=fake_build), \
             patch.object(base, "_modules", return_value=neutral), \
             patch.object(base, "_variant_options", return_value=[{"market": "ML", "name": "X", "point": None, "p_effective": .5}]), \
             patch.object(base.State, "update", autospec=True) as update:
            # Make updates observable without relying on MLB boxscore details.
            def mutate(self, row, box):
                self.pitching[row["game_pk"]]["gamesPitched"] += 1
            update.side_effect = mutate
            out, failures = daily.reconstruct(rows, boxes, use_statcast=False)

        self.assertFalse(failures)
        self.assertEqual(len(out), 3)
        self.assertEqual(seen[0], (1, 0))
        self.assertEqual(seen[1], (2, 0), "second game on same date must still see J-1 state")
        self.assertEqual(seen[2], (3, 2), "next date may see both prior-date games")
        self.assertTrue(all(r["historical_reconstruction"]["same_day_results_visible"] is False for r in out))


if __name__ == "__main__":
    unittest.main()
