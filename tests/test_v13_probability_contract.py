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
        out = v13_runtime.upgrade_option(opt, "FINAL", {"calibrators":{}}, data_quality=.8)
        self.assertAlmostEqual(out["p_baseball_raw"], .62)
        self.assertAlmostEqual(out["p_baseball_calibrated"], .62)
        self.assertAlmostEqual(out["p_effective"], .62)
        self.assertAlmostEqual(out["p_market"], .51)
        self.assertAlmostEqual(out["model_market_gap"], .11)
        self.assertNotEqual(out["p_posterior"], out["p_effective"])
        self.assertAlmostEqual(out["probability_uncertainty_v13"]["data_quality"], .8)

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
            row={
                "game_pk":version, "phase":"FINAL",
                "analyzed_at":"2026-06-01T16:00:00+00:00",
                "game_date":"2026-06-01T20:00:00+00:00",
                "home_score":5, "away_score":3, "engine_version":version,
                "options":[{"market":"ML","name":"A","p_learned":.60,"result":"WIN"}],
            }
            contract.attach_contract(row)
            rows.append(row)
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

    def test_phase_calibration_keeps_each_phase_but_market_count_stays_one_game(self):
        rows=[
            {"game_pk":"1","phase":"EARLY","game_date":"2026-06-01T20:00:00Z","analyzed_at":"2026-06-01T10:00:00Z",
             "options":[{"market":"ML","name":"Home","point":None,"p_baseball_raw":.55,"result":"WIN"}]},
            {"game_pk":"1","phase":"FINAL","game_date":"2026-06-01T20:00:00Z","analyzed_at":"2026-06-01T19:30:00Z",
             "options":[{"market":"ML","name":"Home","point":None,"p_baseball_raw":.61,"result":"WIN"}]},
        ]
        buckets=cal.examples_from_rows(rows)
        self.assertEqual(len(buckets["MARKET:ML"]),1)
        self.assertAlmostEqual(buckets["MARKET:ML"][0][0],.61)
        self.assertEqual(len(buckets["PHASE:EARLY:ML"]),1)
        self.assertEqual(len(buckets["PHASE:FINAL:ML"]),1)

    def test_identity_interval_uses_phase_evidence_not_larger_market_count(self):
        model={"calibrators":{"MARKET:ML":{"n":40},"PHASE:EARLY:ML":{"n":30},"PHASE:FINAL:ML":{"n":7}}}
        p,source,n=cal.calibrate(.61,"ML","FINAL",model)
        self.assertAlmostEqual(p,.61)
        self.assertEqual(source,"identity")
        self.assertEqual(n,7)
        counts=cal.evidence_counts(model,"ML","FINAL")
        self.assertEqual(counts["phase_n"],7)
        self.assertEqual(counts["market_n"],40)

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
