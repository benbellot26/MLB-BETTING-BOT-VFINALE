from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import shadow_v115


class V115ShadowTests(unittest.TestCase):
    def test_probability_engine_is_frozen_v115_shape(self):
        self.assertTrue(shadow_v115.VERSION.startswith("11.5-"))
        self.assertEqual(shadow_v115.SOURCE_COMMIT, "34b35283d043c6ec9a004013945a23a7da356a77")
        self.assertAlmostEqual(shadow_v115.RUN_DISPERSION, 7.5)
        self.assertEqual(shadow_v115.MAX_RUNS_MATRIX, 22)
        self.assertGreater(shadow_v115.prob_home_win(5.0, 4.0), .5)

    def test_compare_tracks_consensus_v12_only_v11_only_and_gap(self):
        v12 = {"options": [
            {"market": "RUNLINE", "name": "A", "point": 1.5, "p_effective": .62},
            {"market": "RUNLINE", "name": "B", "point": -1.5, "p_effective": .49},
            {"market": "ML", "name": "A", "point": None, "p_effective": .61},
            {"market": "TOTAL", "name": "Over", "point": 8.5, "p_effective": .48},
        ]}
        shadow = {"options": [
            {"market": "RUNLINE", "name": "A", "point": 1.5, "p_effective": .58},
            {"market": "RUNLINE", "name": "B", "point": -1.5, "p_effective": .42},
            {"market": "ML", "name": "A", "point": None, "p_effective": .50},
            {"market": "TOTAL", "name": "Over", "point": 8.5, "p_effective": .60},
        ]}
        cmp = shadow_v115.compare(v12, shadow)
        self.assertEqual(cmp["exact_common_options"], 4)
        self.assertEqual(cmp["consensus_gt55"], 1)
        self.assertEqual(cmp["v12_only_gt55"], 1)
        self.assertEqual(cmp["v11_only_gt55"], 1)
        self.assertEqual(cmp["strong_disagreement"], 2)

    def test_analyze_uses_standard_featured_lines_not_alternate_spreads(self):
        game = {"gamePk": 1, "gameDate": "2026-08-15T20:00:00Z"}
        event = {"bookmakers": [{
            "key": "pinnacle",
            "markets": [
                {"key": "spreads", "outcomes": [
                    {"name": "Home", "point": -1.5, "price": 2.0},
                    {"name": "Away", "point": 1.5, "price": 1.8},
                ]},
                {"key": "alternate_spreads", "outcomes": [
                    {"name": "Home", "point": 1.5, "price": 1.4},
                    {"name": "Away", "point": -1.5, "price": 3.0},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "point": 8.5, "price": 1.9},
                    {"name": "Under", "point": 8.5, "price": 1.9},
                ]},
            ],
        }]}
        ctx = {
            "home": "Home", "away": "Away", "home_sp": "H", "away_sp": "A",
            "home_lineup": {"count": 9}, "away_lineup": {"count": 9},
        }
        empty_sharp = {"p": None, "n": 0, "books": [], "dispersion": None, "max_age_min": None, "robustness": 0.0}
        with patch.object(shadow_v115, "_project_runs", return_value=(4.8, 4.1, ctx)), \
             patch.object(shadow_v115, "sharp_consensus", return_value=empty_sharp), \
             patch("v11.shadow_v115.core.phase_for_game", return_value="FINAL"):
            result = shadow_v115.analyze(game, event, as_of="2026-08-15T18:30:00Z")
        runlines = [x for x in result["options"] if x["market"] == "RUNLINE"]
        self.assertEqual(len(runlines), 2)
        points = {(x["name"], x["point"]) for x in runlines}
        self.assertEqual(points, {("Home", -1.5), ("Away", 1.5)})
        self.assertEqual(len(result["options"]), 6)

    def test_metrics_are_research_only_and_use_latest_settled_game(self):
        row = {
            "game_pk": 1, "analyzed_at": "2026-08-15T18:00:00Z", "result_status": "FINAL",
            "options": [
                {"market": "RUNLINE", "name": "A", "point": 1.5, "p_effective": .62, "result": "WIN"},
                {"market": "ML", "name": "A", "point": None, "p_effective": .61, "result": "LOSS"},
            ],
            "shadow_v115": {"enabled": True, "options": [
                {"market": "RUNLINE", "name": "A", "point": 1.5, "p_effective": .59},
                {"market": "ML", "name": "A", "point": None, "p_effective": .49},
            ]},
        }
        report = shadow_v115.metrics([row])
        self.assertEqual(report["settled_games"], 1)
        self.assertEqual(report["overall"]["consensus_gt55"]["wins"], 1)
        self.assertEqual(report["overall"]["v12_only_gt55"]["losses"], 1)
        self.assertFalse(report["activation"]["affects_v12_selection"])
        self.assertEqual(report["activation"]["minimum_games_before_any_use"], 50)


if __name__ == "__main__":
    unittest.main()
