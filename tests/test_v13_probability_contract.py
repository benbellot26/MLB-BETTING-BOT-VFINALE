from __future__ import annotations

import unittest

from v11 import calibration_baseball_v13 as cal
from v11 import probability_contract_v13 as contract
from v11 import validation_v13
from v11 import v13_runtime
from v11 import v13_train


class V13ProbabilityContractTests(unittest.TestCase):
    def test_market_never_changes_baseball_probability_without_calibrator(self):
        opt = {
            "market":"ML", "p_learned":.62, "p_structural":.60,
            "p_market":.51, "sharp_weight":.30, "p_effective":.54,
            "p_push_model":0.0, "model_uncertainty":.05,
        }
        out = v13_runtime.upgrade_option(opt, "FINAL", {"calibrators":{}})
        self.assertAlmostEqual(out["p_baseball_raw"], .62)
        self.assertAlmostEqual(out["p_baseball_calibrated"], .62)
        self.assertAlmostEqual(out["p_effective"], .62)
        self.assertAlmostEqual(out["p_market"], .51)
        self.assertAlmostEqual(out["model_market_gap"], .11)
        self.assertNotEqual(out["p_posterior"], out["p_effective"])

    def test_contract_rejects_market_derived_baseball_source(self):
        payload = contract.option_contract_payload(
            p_baseball_raw=.6, p_baseball_calibrated=.58, p_market=.55,
            p_posterior=.57, calibration_source="test"
        )
        payload["baseball_probability_source"] = "sharp-market-blend"
        with self.assertRaises(ValueError):
            contract.assert_no_market_leakage(payload)

    def test_training_compatibility_is_independent_of_software_version(self):
        rows = []
        for version in ("12.3.1-old", "12.3.2-new"):
            rows.append({
                "game_pk":version, "phase":"FINAL",
                "analyzed_at":"2026-06-01T16:00:00+00:00",
                "game_date":"2026-06-01T20:00:00+00:00",
                "home_score":5, "away_score":3, "engine_version":version,
                "options":[{"market":"ML","name":"A","p_learned":.60,"result":"WIN"}],
            })
        eligible = v13_train.eligible_probability_rows(rows)
        self.assertEqual(len(eligible), 2)

    def test_training_refuses_market_blended_only_rows(self):
        rows = [{
            "game_pk":"1", "phase":"FINAL",
            "analyzed_at":"2026-06-01T16:00:00+00:00",
            "game_date":"2026-06-01T20:00:00+00:00",
            "home_score":5, "away_score":3,
            "options":[{"market":"ML","name":"A","p_effective":.60,"p_market":.57,"result":"WIN"}],
        }]
        self.assertEqual(v13_train.eligible_probability_rows(rows), [])

    def test_strict_validation_requires_positive_bootstrap_lower_bound(self):
        days = {f"2026-06-{i:02d}":[.003,.002,.004] for i in range(1,21)}
        windows = [{"test_games":40,"brier_improvement":.002,"logloss_improvement":.001} for _ in range(5)]
        gate = validation_v13.strict_promotion_gate(
            compatible_games=900,
            outer_holdout_games=250,
            walk_forward_windows=windows,
            paired_brier_deltas_by_day=days,
            logloss_gain=.001,
            market_metrics={"ML":{"n":150,"baseline_brier":.24,"candidate_brier":.239}},
            calibration_metrics={"ece":.02,"slope":1.0,"intercept":0.0},
        )
        self.assertTrue(gate["passes"])

    def test_calibration_identity_when_evidence_is_insufficient(self):
        result = cal.fit_calibrator([(.60,1),(.40,0)]*20, minimum=100)
        self.assertFalse(result["active"])
        self.assertEqual(result["status"], "COLLECTING")


if __name__ == "__main__":
    unittest.main()
