from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import v124_historical_reconstruction as hist
from v11 import v124_weight_optimizer as opt


class HistoricalReconstructionTests(unittest.TestCase):
    def row(self, i=0):
        return {
            "game_pk": 900000+i,
            "game_date": f"2026-04-{1+i:02d}T18:00:00Z",
            "home": "Home Club", "away": "Away Club",
            "home_score": 5, "away_score": 3,
            "league": {"ops": .710, "era": 4.35, "rpg": 4.4},
            "starters": {"home_id": 11, "away_id": 22, "home_hand": "R", "away_hand": "L"},
            "v10": {"home_struct": 4.6, "away_struct": 4.1},
            "rl_proxy": {"name": "Home Club", "point": -1.5, "result": "W"},
        }

    def box(self):
        def player(pid, name, order, batting=None, pitching=None):
            return {
                "person": {"id": pid, "fullName": name},
                "battingOrder": str(order) if order else None,
                "stats": {"batting": batting or {}, "pitching": pitching or {}},
            }
        home_players = {
            "ID1": player(101, "Hitter H", 100, {"atBats": 4, "hits": 2, "doubles": 1, "baseOnBalls": 1}),
            "ID11": player(11, "Starter H", None, pitching={"inningsPitched": "6.0", "earnedRuns": 2, "hits": 5, "baseOnBalls": 1, "homeRuns": 1, "strikeOuts": 7, "numberOfPitches": 91}),
            "ID12": player(12, "Reliever H", None, pitching={"inningsPitched": "1.0", "earnedRuns": 0, "hits": 1, "baseOnBalls": 0, "homeRuns": 0, "strikeOuts": 2, "numberOfPitches": 16}),
        }
        away_players = {
            "ID2": player(201, "Hitter A", 100, {"atBats": 4, "hits": 1, "baseOnBalls": 0}),
            "ID22": player(22, "Starter A", None, pitching={"inningsPitched": "5.0", "earnedRuns": 4, "hits": 7, "baseOnBalls": 2, "homeRuns": 1, "strikeOuts": 4, "numberOfPitches": 88}),
            "ID23": player(23, "Reliever A", None, pitching={"inningsPitched": "1.0", "earnedRuns": 1, "hits": 2, "baseOnBalls": 1, "homeRuns": 0, "strikeOuts": 1, "numberOfPitches": 22}),
        }
        return {
            "teams": {
                "home": {"team": {"id": 1}, "players": home_players},
                "away": {"team": {"id": 2}, "players": away_players},
            }
        }

    def test_state_is_updated_only_after_prediction_point(self):
        state = hist.State()
        self.assertIsNone(hist._ops(state.batting[101]))
        state.update(self.row(), self.box())
        self.assertGreater(hist._ops(state.batting[101]), .5)
        self.assertGreater(hist._pitch_stats(state.pitching[11])["inningsPitched"], 5.9)
        self.assertIn(12, state.team_relievers[1])

    def test_reconstruction_has_no_odds_or_weather_training(self):
        state = hist.State()
        row, box = self.row(), self.box()
        result = hist._build_result(row, box, state)
        with patch("v11.predictive_v124.statcast_module", return_value={"name": "statcast", "status": "UNAVAILABLE", "coverage": 0.0, "home_factor": 1.0, "away_factor": 1.0}):
            modules = hist._modules(result, row, state, use_statcast=False)
        self.assertEqual(modules["weather_park"]["coverage"], 0.0)
        self.assertEqual([x["market"] for x in result["options"]], ["ML", "RUNLINE"])

    def test_warmstart_keeps_frozen_test_out_of_weight_fit(self):
        rows = []
        for i in range(100):
            y = i % 3 != 0
            home_mu, away_mu = 4.5, 4.3
            result = {
                "ctx": {"home": "Home", "away": "Away"},
                "features": {"run_dispersion": 7.5, "run_environment_sigma": .08},
                "options": [{"market": "ML", "name": "Home", "point": None}],
            }
            base = hist._variant_options(result, home_mu, away_mu)
            good_h, good_a = ((4.9, 4.0) if y else (4.0, 4.9))
            variants = {"baseline_historical_proxy": {"home_mu": home_mu, "away_mu": away_mu, "options": base}}
            modules = {}
            for name in opt.MODULES:
                h, a = (good_h, good_a) if name == "starter_ip" else (home_mu, away_mu)
                variants[f"only_{name}"] = {"home_mu": h, "away_mu": a, "home_factor": h/home_mu, "away_factor": a/away_mu, "options": hist._variant_options(result, h, a)}
                modules[name] = {"status": "ACTIVE", "coverage": 1.0, "home_factor": h/home_mu, "away_factor": a/away_mu}
            rows.append({
                "game_pk": 700000+i, "game_date": f"2026-06-{1+i//4:02d}T00:00:00Z",
                "home_score": 6 if y else 2, "away_score": 2 if y else 6,
                "options": [{"market": "ML", "name": "Home", "point": None, "result": "WIN" if y else "LOSS"}],
                "shadow_v124": {"enabled": True, "base_home_mu": home_mu, "base_away_mu": away_mu, "modules": modules, "variants": variants},
            })
        with patch.object(hist, "HIST_MIN_GAMES", 75), patch.object(opt, "_BOOTSTRAPS", 10):
            model = hist.build_warmstart(rows)
        self.assertGreater(model["train_games"], 74)
        self.assertGreater(model["frozen_test_games"], 0)
        self.assertFalse(model["frozen_test"]["used_for_weight_fitting"])
        self.assertFalse(model["guardrails"]["historical_odds_used"])
        self.assertFalse(model["guardrails"]["roi_used_for_training"])
        self.assertFalse(model["guardrails"]["affects_v12_selection"])


if __name__ == "__main__":
    unittest.main()
