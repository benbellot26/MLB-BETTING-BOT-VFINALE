from __future__ import annotations

import unittest
from unittest.mock import patch

from v14 import MODEL_GENERATION, VERSION
from v14.all_stats_context import MAX_TEAM_DELTA, all_stats_overlay_from_feature_row
from v14.pipeline import _finish_prediction


class AllStatsContextTests(unittest.TestCase):
    def _row(self) -> dict:
        return {
            "game_pk": "1",
            "game_date": "2026-08-31T18:00:00+00:00",
            "as_of": "2026-08-31T17:30:00+00:00",
            "point_in_time": True,
            "point_in_time_validation_reasons": [],
            "data_quality": {"eligible": True},
            "context": {
                "home_id": 1,
                "away_id": 2,
                "home_starter": {"id": 11, "gamesStarted": 20, "inningsPerStart": 5.8},
                "away_starter": {"id": 22, "gamesStarted": 20, "inningsPerStart": 5.4},
                "home_lineup": {"players": [{"id": i} for i in range(101, 110)], "confirmed": True},
                "away_lineup": {"players": [{"id": i} for i in range(201, 210)], "confirmed": True},
            },
            "features": {
                "operational": {
                    "home": {"timezone_shift_hours_approx": 1.7, "timezone_shift_hours_exact": 2.1},
                    "away": {"timezone_shift_hours_approx": 2.2, "timezone_shift_hours_exact": 1.8},
                },
                "environment": {"available": True, "temperature_f": 78, "roof": "open"},
            },
        }

    def _statcast(self) -> dict:
        return {
            "freshness": "FRESH",
            "home": {
                "lineup": {"xwoba": .360, "hard_hit_rate": .44, "barrel_rate": .12, "k_minus_bb_rate": .08},
                "starter": {"xwoba_allowed": .295, "hard_hit_rate_allowed": .34, "barrel_rate_allowed": .06, "k_minus_bb_rate": .17, "avg_release_speed": 95.0},
                "bullpen": {"xwoba_allowed": .300, "hard_hit_rate_allowed": .35, "barrel_rate_allowed": .07, "k_minus_bb_rate": .16},
            },
            "away": {
                "lineup": {"xwoba": .310, "hard_hit_rate": .36, "barrel_rate": .07, "k_minus_bb_rate": .14},
                "starter": {"xwoba_allowed": .360, "hard_hit_rate_allowed": .45, "barrel_rate_allowed": .12, "k_minus_bb_rate": .07, "avg_release_speed": 91.0},
                "bullpen": {"xwoba_allowed": .350, "hard_hit_rate_allowed": .43, "barrel_rate_allowed": .11, "k_minus_bb_rate": .08},
            },
        }

    def test_unsafe_row_is_neutral(self):
        row = self._row()
        row["point_in_time"] = False
        out = all_stats_overlay_from_feature_row(row, 4.5, 4.5)
        self.assertFalse(out["eligible"])
        self.assertEqual(out["home_mu"], 4.5)
        self.assertEqual(out["away_mu"], 4.5)
        self.assertFalse(out["market_probability_used_as_feature"])

    def test_advanced_stats_move_runs_with_caps(self):
        artifact = {"schema": "pulsar-v14-statcast-id-priors-v2", "point_in_time": True}
        matchup = {
            "status": "READY_SHADOW",
            "home_offense": {"matchup_xwoba": .370, "handedness_xwoba": .360},
            "away_offense": {"matchup_xwoba": .315, "handedness_xwoba": .310},
        }
        defense = {
            "status": "READY_SHADOW",
            "home": {"status": "READY_SHADOW", "defense_factor": .97, "catcher_factor": .99, "baserunning_run_adjustment": .05},
            "away": {"status": "READY_SHADOW", "defense_factor": 1.03, "catcher_factor": 1.01, "baserunning_run_adjustment": -.03},
        }
        with patch("v14.all_stats_context._cached_statcast_priors", return_value=artifact), \
             patch("v14.all_stats_context.build_shadow_features", return_value=self._statcast()), \
             patch("v14.all_stats_context.pitch_matchup", return_value=matchup), \
             patch("v14.all_stats_context._cached_defense_priors", return_value={"point_in_time": True}), \
             patch("v14.all_stats_context.defense_baserunning", return_value=defense), \
             patch("v14.all_stats_context.environment_physics", return_value={"status": "READY_SHADOW", "promotion_ready": True, "flight_environment_index": .5}):
            out = all_stats_overlay_from_feature_row(self._row(), 4.5, 4.5)
        self.assertTrue(out["eligible"])
        self.assertGreater(out["home_delta"], out["away_delta"])
        self.assertLessEqual(abs(out["home_delta"]), MAX_TEAM_DELTA)
        self.assertLessEqual(abs(out["away_delta"]), MAX_TEAM_DELTA)
        self.assertIn("home_offense_statcast_matchup_baserunning", out["active_components"])
        self.assertIn("away_pitching_statcast_depth", out["active_components"])
        self.assertFalse(out["market_probability_used_as_feature"])

    def test_exact_timezone_only_corrects_approximation(self):
        artifact = {"schema": "pulsar-v14-statcast-id-priors-v2", "point_in_time": True}
        empty_statcast = {"freshness": "FRESH", "home": {}, "away": {}}
        with patch("v14.all_stats_context._cached_statcast_priors", return_value=artifact), \
             patch("v14.all_stats_context.build_shadow_features", return_value=empty_statcast), \
             patch("v14.all_stats_context.pitch_matchup", return_value={"status": "COLLECTING"}), \
             patch("v14.all_stats_context._cached_defense_priors", return_value={}), \
             patch("v14.all_stats_context.defense_baserunning", return_value={"status": "COLLECTING"}), \
             patch("v14.all_stats_context.environment_physics", return_value={"status": "COLLECTING", "promotion_ready": False}):
            out = all_stats_overlay_from_feature_row(self._row(), 4.5, 4.5)
        # Home exact shift crosses the 2h threshold -> add the missing -0.8% penalty.
        self.assertAlmostEqual(out["home_delta"], -.008, places=9)
        # Away approximate shift crossed 2h but exact does not -> remove the old -0.8% penalty.
        self.assertAlmostEqual(out["away_delta"], .008, places=9)

    def test_pipeline_applies_advanced_overlay_after_context(self):
        with patch("v14.pipeline.context_overlay_from_feature_row", return_value={"eligible": True, "home_mu": 4.0, "away_mu": 4.0, "home_delta": 0.0, "away_delta": 0.0, "components": {}}), \
             patch("v14.pipeline.all_stats_overlay_from_feature_row", return_value={"schema": "pulsar-v14-all-stats-context-v1", "eligible": True, "home_mu": 4.12, "away_mu": 3.88, "home_delta": .03, "away_delta": -.03, "active_components": ["statcast"], "components": {}, "statcast_freshness": "FRESH", "market_probability_used_as_feature": False}):
            out = _finish_prediction(
                structural_base={"home_mu": 4.0, "away_mu": 4.0, "active_layers": []},
                game_pk="1",
                game_date="2026-08-31T18:00:00+00:00",
                analyzed_at="2026-08-31T17:30:00+00:00",
                home="Home",
                away="Away",
                total_line=8.5,
                phase="FINAL",
                feature_row=None,
                dispersion=1.18,
                environment_sigma=.04,
                extra_innings_home_probability=.5,
                source_generation="test",
            )
        self.assertAlmostEqual(out["run_projection"]["home_mu"], 4.12)
        self.assertAlmostEqual(out["run_projection"]["away_mu"], 3.88)
        self.assertEqual(out["advanced_stats_adjustment"]["active_components"], ["statcast"])
        self.assertEqual(out["model_generation"], MODEL_GENERATION)
        self.assertEqual(out["software_version"], VERSION)
        self.assertFalse(out["market_probability_used_as_feature"])


if __name__ == "__main__":
    unittest.main()
