from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import predictive_v124 as v124


class PredictiveV124Tests(unittest.TestCase):
    def result(self):
        home_players = [
            {"id": 100+i, "name": f"H{i}", "batting_order": (i+1)*100, "ops": .760+.015*i}
            for i in range(9)
        ]
        away_players = [
            {"id": 200+i, "name": f"A{i}", "batting_order": (i+1)*100, "ops": .690-.008*i}
            for i in range(9)
        ]
        return {
            "game": {"gameDate": "2026-08-15T23:10:00Z"},
            "phase": "FINAL",
            "hmu": 4.8,
            "amu": 4.1,
            "ctx": {
                "home": "Boston Red Sox", "away": "New York Yankees",
                "home_id": 111, "away_id": 147,
                "home_lineup": {"count": 9, "players": home_players},
                "away_lineup": {"count": 9, "players": away_players},
                "home_starter": {"id": 10, "name": "Home SP", "era": 3.70, "whip": 1.20, "innings": 120,
                                 "k9": 9.3, "bb9": 2.7, "hr9": 1.0},
                "away_starter": {"id": 20, "name": "Away SP", "era": 4.40, "whip": 1.35, "innings": 105,
                                 "k9": 8.0, "bb9": 3.5, "hr9": 1.3},
            },
            "features": {
                "home_mu": 4.8, "away_mu": 4.1,
                "park_factor": 1.03,
                "run_dispersion": 7.5, "run_environment_sigma": .08,
                "weather": {"available": True, "temperature_c": 28, "humidity_pct": 62,
                            "wind_kph": 18, "wind_direction_deg": 210},
                "bullpen": {
                    "home": {"coverage": 1.0, "relievers": [{"id": 31, "pitches_3d": 8, "days_used": 1},
                                                               {"id": 32, "pitches_3d": 35, "days_used": 2}]},
                    "away": {"coverage": .9, "relievers": [{"id": 41, "pitches_3d": 18, "days_used": 1},
                                                              {"id": 42, "pitches_3d": 48, "days_used": 3}]},
                },
            },
            "options": [
                {"market": "ML", "name": "Boston Red Sox", "point": None, "p_effective": .60,
                 "p_win": .60, "p_push": 0, "p_market": .56, "sharp_weight": .18},
                {"market": "ML", "name": "New York Yankees", "point": None, "p_effective": .40,
                 "p_win": .40, "p_push": 0, "p_market": .44, "sharp_weight": .18},
                {"market": "RUNLINE", "name": "Boston Red Sox", "point": -1.5, "p_effective": .47,
                 "p_win": .47, "p_push": 0, "p_market": .45, "sharp_weight": .18},
                {"market": "RUNLINE", "name": "New York Yankees", "point": 1.5, "p_effective": .53,
                 "p_win": .53, "p_push": 0, "p_market": .55, "sharp_weight": .18},
                {"market": "TOTAL", "name": "Over", "point": 8.5, "p_effective": .57,
                 "p_win": .57, "p_push": 0, "p_market": .54, "sharp_weight": .18},
                {"market": "TOTAL", "name": "Under", "point": 8.5, "p_effective": .43,
                 "p_win": .43, "p_push": 0, "p_market": .46, "sharp_weight": .18},
            ],
        }

    def test_implementation_report_is_explicit(self):
        report = v124.implementation_report()
        self.assertEqual(report["1_platoon_handedness"]["status"], "ADDED")
        self.assertEqual(report["6_weather_park_interaction"]["status"], "PARTIAL")
        self.assertEqual(report["8_model_ensemble"]["status"], "ADDED_RESEARCH_ONLY")

    def test_platoon_uses_split_and_pitcher_hand(self):
        r = self.result()
        def person(pid):
            return {"pitch_hand": "R"}
        def split(pid, group, sit):
            return {"ops": .900 if pid < 200 else .620, "plateAppearances": 180}
        with patch.object(v124, "_person", side_effect=person), patch.object(v124, "_split_stats", side_effect=split):
            out = v124.platoon_module(r, True)
        self.assertEqual(out["status"], "ACTIVE")
        self.assertGreater(out["home_factor"], 1.0)
        self.assertLess(out["away_factor"], 1.0)

    def test_lineup_player_is_non_linear_and_bounded(self):
        out = v124.lineup_player_module(self.result(), True)
        self.assertGreaterEqual(out["coverage"], .99)
        self.assertTrue(.97 <= out["home_factor"] <= 1.03)
        self.assertTrue(.97 <= out["away_factor"] <= 1.03)
        self.assertGreater(out["home_factor"], out["away_factor"])

    def test_expected_starter_ip_is_bounded(self):
        with patch.object(v124.core, "player_stats", return_value={"inningsPitched": "150.0", "gamesStarted": 25,
                                                                  "gamesPitched": 25}):
            ip, meta = v124.expected_starter_ip({"id": 1, "era": 3.50, "whip": 1.15})
        self.assertTrue(4.0 <= ip <= 6.7)
        self.assertEqual(meta["starts"], 25)

    def test_bullpen_player_level_uses_fatigue(self):
        r = self.result()
        with patch.object(v124, "_reliever_quality", return_value=1.10), \
             patch.object(v124, "expected_starter_ip", return_value=(5.0, {})):
            out = v124.bullpen_player_module(r, True)
        self.assertEqual(out["status"], "ACTIVE")
        self.assertGreater(out["home_factor"], 1.0)
        self.assertGreater(out["away_factor"], 1.0)

    def test_weather_roof_fails_neutral(self):
        r = self.result()
        r["ctx"]["home"] = "Toronto Blue Jays"
        out = v124.weather_park_module(r, True)
        self.assertEqual(out["status"], "ROOF_NEUTRAL")
        self.assertEqual(out["home_factor"], 1.0)
        self.assertEqual(out["away_factor"], 1.0)

    def test_uncertainty_has_six_components(self):
        r = self.result()
        v11 = {"options": [{"market": "ML", "name": "Boston Red Sox", "point": None, "p_effective": .52}]}
        out = v124.uncertainty_module(r, v11, {"coverage": .5}, True)
        self.assertEqual(out["status"], "ACTIVE")
        self.assertEqual(set(out["components"]), {"starter", "lineup", "bullpen", "statcast", "market", "cross_model"})
        self.assertTrue(.012 <= out["uncertainty"] <= .12)

    def test_price_variant_preserves_option_surface(self):
        r = self.result()
        out = v124.price_variant(r, 5.0, 4.0, .04)
        self.assertEqual(len(out), len(r["options"]))
        self.assertTrue(all(.001 <= x["p_effective"] <= .999 for x in out))

    def test_analyze_is_research_only_and_has_ablations(self):
        r = self.result()
        neutral = lambda name: {"name": name, "enabled": True, "status": "ACTIVE", "home_factor": 1.01,
                                "away_factor": .99, "coverage": 1.0}
        with patch.object(v124, "platoon_module", return_value=neutral("platoon")), \
             patch.object(v124, "statcast_module", return_value=neutral("statcast")), \
             patch.object(v124, "bullpen_player_module", return_value=neutral("bullpen_player")), \
             patch.object(v124, "lineup_player_module", return_value=neutral("lineup_player")), \
             patch.object(v124, "starter_ip_module", return_value=neutral("starter_ip")), \
             patch.object(v124, "weather_park_module", return_value=neutral("weather_park")), \
             patch.object(v124, "uncertainty_module", return_value={**neutral("uncertainty"), "uncertainty": .04}):
            out = v124.analyze(r, {"options": []})
        self.assertFalse(out["affects_v12_selection"])
        self.assertIn("all_core", out["variants"])
        self.assertIn("ensemble", out["variants"])
        self.assertIn("only_platoon", out["variants"])
        self.assertEqual(len(out["variants"]["all_core"]["options"]), len(r["options"]))

    def test_metrics_scores_settled_variants(self):
        r = self.result()
        for i, opt in enumerate(r["options"]):
            opt["result"] = "WIN" if i % 2 == 0 else "LOSS"
        row = {
            "options": r["options"],
            "shadow_v124": {
                "enabled": True,
                "variants": {"baseline_v1232": {"options": r["options"]}},
            },
        }
        report = v124.metrics([row])
        self.assertEqual(report["settled_games"], 1)
        self.assertEqual(report["variants"]["baseline_v1232"]["n"], 6)
        self.assertFalse(report["activation"]["affects_v12_selection"])


if __name__ == "__main__":
    unittest.main()
