from __future__ import annotations

import unittest

from v11 import v124_historical_validation as validation
from v11 import v124_historical_warmstart as warm
from v11 import v124_weight_optimizer as opt


class HistoricalWarmstartTests(unittest.TestCase):
    def native(self, n, weight=.8):
        return {
            "status": "COLLECTING" if n < 75 else "EXPERIMENTAL_SHADOW",
            "stage": "COLLECT" if n < 75 else "EXPERIMENTAL",
            "settled_games": n,
            "weights": {name: (weight if name == "starter_ip" else .1) for name in opt.MODULES},
            "active_for_v124_shadow": n >= 75,
            "modules": {}, "research_only": True, "affects_v12_selection": False,
            "promotion": {"automatic": False},
        }

    def historical(self, eligible=True):
        return {
            "schema": warm.SCHEMA, "status": "ELIGIBLE" if eligible else "DIAGNOSTIC_ONLY",
            "eligible_for_warm_start": eligible,
            "historical_reconstructed_games": 1801,
            "weights": {name: (1.0 if name == "starter_ip" else .2) for name in opt.MODULES},
            "coverage": {name: (0.0 if name == "weather_park" else .8) for name in opt.MODULES},
            "walk_forward": {"status": "ACTIVE"},
            "frozen_test": {"brier_improvement": .003, "logloss_improvement": .005},
            "modules": {"starter_ip": {"verdict": "KEEP"}},
        }

    def gate_candidate(self, wf_brier=.003, wf_logloss=.004, frozen_brier=.002, frozen_logloss=.003):
        return {
            "historical_reconstructed_games": 1801,
            "minimum_games": 600,
            "walk_forward": {
                "status": "ACTIVE", "windows": 20,
                "baseline": {"brier": .251, "logloss": .695, "team_run_mae": 2.54, "total_run_mae": 3.63},
                "optimized": {"brier": .251-wf_brier, "logloss": .695-wf_logloss, "team_run_mae": 2.53, "total_run_mae": 3.62},
            },
            "frozen_test": {
                "brier_improvement": frozen_brier,
                "logloss_improvement": frozen_logloss,
                "team_run_mae_improvement": .01,
                "used_for_weight_fitting": False,
            },
            "guardrails": {"historical_odds_used": False, "roi_used_for_training": False, "affects_v12_selection": False},
        }

    def compose(self, n, eligible=True):
        return warm.compose(self.native(n), self.historical(eligible), opt.MODULES, opt.MAX_WEIGHT, opt.MIN_GAMES, opt.WALK_FORWARD_READY_GAMES)

    def test_oos_gate_accepts_only_non_regressing_walkforward_and_frozen_test(self):
        model = validation.harden(self.gate_candidate())
        self.assertTrue(model["eligible_for_warm_start"])
        self.assertTrue(model["out_of_sample_gate"]["passes"])

    def test_oos_gate_rejects_walkforward_probability_regression(self):
        model = validation.harden(self.gate_candidate(wf_brier=-.001))
        self.assertFalse(model["eligible_for_warm_start"])
        self.assertFalse(model["out_of_sample_gate"]["checks"]["walk_forward_brier_non_regression"])

    def test_oos_gate_rejects_frozen_probability_regression(self):
        model = validation.harden(self.gate_candidate(frozen_logloss=-.001))
        self.assertFalse(model["eligible_for_warm_start"])
        self.assertFalse(model["out_of_sample_gate"]["checks"]["frozen_logloss_non_regression"])

    def test_historical_weights_can_activate_only_shadow_before_75_native(self):
        model = self.compose(0)
        self.assertEqual(model["native_settled_games"], 0)
        self.assertEqual(model["historical_reconstructed_games"], 1801)
        self.assertEqual(model["weight_source"], "HISTORICAL_WARM_START")
        self.assertEqual(model["weights"]["starter_ip"], 1.0)
        self.assertTrue(model["active_for_v124_shadow"])
        self.assertFalse(model["affects_v12_selection"])
        self.assertFalse(model["promotion"]["automatic"])

    def test_native_counter_is_not_inflated_by_historical_games(self):
        model = self.compose(40)
        self.assertEqual(model["settled_games"], 40)
        self.assertEqual(model["native_settled_games"], 40)
        self.assertEqual(model["historical_reconstructed_games"], 1801)

    def test_75_native_games_blend_with_historical_prior(self):
        model = self.compose(75)
        self.assertEqual(model["weight_source"], "BLENDED_HISTORICAL_NATIVE")
        self.assertAlmostEqual(model["native_weight_share"], .5, places=6)
        self.assertAlmostEqual(model["weights"]["starter_ip"], .9, places=6)

    def test_150_native_games_fully_replace_historical_weights(self):
        model = self.compose(150)
        self.assertEqual(model["weight_source"], "NATIVE_DOMINANT")
        self.assertEqual(model["native_weight_share"], 1.0)
        self.assertAlmostEqual(model["weights"]["starter_ip"], .8, places=6)

    def test_ineligible_historical_artifact_never_activates_shadow(self):
        model = self.compose(0, eligible=False)
        self.assertEqual(model["weight_source"], "NO_ELIGIBLE_WARM_START")
        self.assertFalse(model["active_for_v124_shadow"])
        self.assertTrue(all(v == 0.0 or v == .1 or v == .8 for v in model["weights"].values()))


if __name__ == "__main__":
    unittest.main()
