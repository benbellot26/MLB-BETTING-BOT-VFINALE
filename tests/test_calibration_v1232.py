from __future__ import annotations

import unittest

from v11.v123_runtime import activate

activate()

from v11 import config, pro_model
from v11 import calibration_v1232 as cal


class CalibrationChallengerV1232Tests(unittest.TestCase):
    def test_runtime_keeps_v1232_production_generation(self):
        self.assertTrue(config.VERSION.startswith("12.3.2"))
        self.assertEqual(pro_model.CALIBRATION_GENERATION, "hierarchical-challenger-v2")

    def test_reliability_metrics_are_zero_when_frequency_matches_probability(self):
        examples = [(0.60, 1)]*6 + [(0.60, 0)]*4
        metrics = cal.reliability_metrics(examples)
        self.assertEqual(metrics["n"], 10)
        self.assertAlmostEqual(metrics["ece"], 0.0, places=12)
        self.assertAlmostEqual(metrics["mce"], 0.0, places=12)

    def test_beta_identity_parameters_preserve_probability(self):
        beta_identity = {"active": True, "method": "beta", "a": 1.0, "b": 1.0, "c": 0.0}
        for p in (.15, .35, .50, .65, .85):
            self.assertAlmostEqual(cal.apply_calibrator(beta_identity, p), p, places=10)

    def test_global_market_calibrator_is_fallback_and_phase_has_priority(self):
        global_side = {"active": True, "method": "platt", "a": -0.20, "b": 0.80}
        model = {
            "active": True,
            "phase_models": {"EARLY": {"calibration": {"ML": {"side": {"active": False}}}}},
            "global_calibration": {"ML": {"side": global_side, "push": {"active": False}}},
        }
        q1, _, _, source = pro_model.calibrate_triplet("ML", .70, .30, model=model, phase="EARLY")
        self.assertEqual(source, "champion:global:platt")
        self.assertNotAlmostEqual(q1, .70)

        phase_side = {"active": True, "method": "platt", "a": 0.10, "b": 0.90}
        model["phase_models"]["EARLY"]["calibration"]["ML"]["side"] = phase_side
        q2, _, _, source2 = pro_model.calibrate_triplet("ML", .70, .30, model=model, phase="EARLY")
        self.assertEqual(source2, "champion:phase:platt")
        self.assertNotAlmostEqual(q2, q1)

    def test_research_runline_pair_excludes_alternate_spreads(self):
        row = {
            "home": "Home",
            "away": "Away",
            "options": [
                {"market": "RUNLINE", "name": "Home", "point": -1.5, "refs": 2,
                 "sharp_effective_n": 1.8, "reference_market": {"market_key": "spreads"}},
                {"market": "RUNLINE", "name": "Away", "point": 1.5, "refs": 2,
                 "sharp_effective_n": 1.8, "reference_market": {"market_key": "spreads"}},
                {"market": "RUNLINE", "name": "Home", "point": 1.5, "refs": 4,
                 "sharp_effective_n": 3.5, "reference_market": {"market_key": "alternate_spreads"}},
                {"market": "RUNLINE", "name": "Away", "point": -1.5, "refs": 4,
                 "sharp_effective_n": 3.5, "reference_market": {"market_key": "alternate_spreads"}},
            ],
        }
        a, b = cal.research_market_pair(row, "RUNLINE")
        self.assertEqual(a["point"], -1.5)
        self.assertEqual(b["point"], 1.5)

    def test_calibration_can_train_without_winamax_execution(self):
        row = {
            "home": "Home",
            "away": "Away",
            "options": [
                {"market": "TOTAL", "name": "Over", "point": 8.5, "refs": 3, "execution_available": False,
                 "reference_market": {"market_key": "totals"}},
                {"market": "TOTAL", "name": "Under", "point": 8.5, "refs": 3, "execution_available": False,
                 "reference_market": {"market_key": "totals"}},
            ],
        }
        a, b = cal.research_market_pair(row, "TOTAL")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertFalse(a["execution_available"])

    def test_overconfident_probabilities_select_a_real_challenger_on_holdout(self):
        rows = []
        for i in range(200):
            home_win = i % 5 in (0, 1, 2)  # stable 60% event rate
            rows.append({
                "home": "Home",
                "away": "Away",
                "options": [
                    {"market": "ML", "name": "Home", "p_model": .80, "p_effective": .80,
                     "p_push": 0.0, "result": "WIN" if home_win else "LOSS"},
                    {"market": "ML", "name": "Away", "p_model": .20, "p_effective": .20,
                     "p_push": 0.0, "result": "LOSS" if home_win else "WIN"},
                ],
            })
        fitted = cal._fit_calibration_v2(rows, "ML")
        self.assertTrue(fitted["side"]["active"])
        self.assertIn(fitted["side"]["method"], {"platt", "beta"})
        self.assertGreaterEqual(fitted["side"]["brier_gain"], config.MIN_CALIBRATION_BRIER_GAIN)
        self.assertLessEqual(
            fitted["side"]["candidate"]["logloss"],
            fitted["side"]["base"]["logloss"] + 1e-12,
        )

    def test_component_builder_exposes_global_calibration(self):
        built = pro_model._build_components([])
        self.assertEqual(built["calibration_generation"], "hierarchical-challenger-v2")
        self.assertEqual(set(built["global_calibration"]), {"ML", "RUNLINE", "TOTAL"})


if __name__ == "__main__":
    unittest.main()
