from __future__ import annotations

import unittest

from v11 import probability_contract_v13 as contract
from v11 import v13_historical_backfill as backfill


class V13HistoricalBackfillRegressionTests(unittest.TestCase):
    def test_baseline_probability_supports_ml_runline_and_total(self):
        common=("Home",4.8,4.2,7.5,.08)
        cases=[
            {"market":"ML","name":"Home","point":None},
            {"market":"ML","name":"Away","point":None},
            {"market":"RUNLINE","name":"Home","point":-1.5},
            {"market":"RUNLINE","name":"Away","point":1.5},
            {"market":"TOTAL","name":"Over","point":8.5},
            {"market":"TOTAL","name":"Under","point":8.5},
        ]
        for opt in cases:
            with self.subTest(opt=opt):
                p,push=backfill._baseline_probability(opt,*common)
                self.assertIsNotNone(p)
                self.assertIsNotNone(push)
                self.assertGreater(float(p),0.0)
                self.assertLess(float(p),1.0)
                self.assertGreaterEqual(float(push),0.0)
                self.assertLess(float(push),1.0)

    def test_conditional_binary_probability_matches_live_push_semantics(self):
        p,push=backfill._conditional_binary_probability(.48,.10)
        self.assertAlmostEqual(push,.10)
        self.assertAlmostEqual(p,.48/.90,places=12)

    def test_integer_total_replay_probability_is_win_given_no_push(self):
        opt={"market":"TOTAL","name":"Over","point":8.0}
        p,push=backfill._baseline_probability(opt,"Home",4.8,4.2,7.5,.08)
        raw,raw_push=backfill.engine.prob_total_parts(4.8,4.2,"over",8.0,dispersion=7.5,env_sigma=.08)
        self.assertGreater(raw_push,0.0)
        self.assertAlmostEqual(push,raw_push,places=12)
        self.assertAlmostEqual(p,raw/(1-raw_push),places=12)

    def test_half_point_total_has_zero_push_and_no_conditioning_change(self):
        opt={"market":"TOTAL","name":"Over","point":8.5}
        p,push=backfill._baseline_probability(opt,"Home",4.8,4.2,7.5,.08)
        raw,raw_push=backfill.engine.prob_total_parts(4.8,4.2,"over",8.5,dispersion=7.5,env_sigma=.08)
        self.assertAlmostEqual(raw_push,0.0,places=12)
        self.assertAlmostEqual(push,0.0,places=12)
        self.assertAlmostEqual(p,raw,places=12)

    def test_integer_runline_replay_probability_is_win_given_no_push(self):
        opt={"market":"RUNLINE","name":"Home","point":-1.0}
        p,push=backfill._baseline_probability(opt,"Home",4.8,4.2,7.5,.08)
        raw,raw_push=backfill.engine.prob_cover_parts(4.8,4.2,"home",-1.0,dispersion=7.5,env_sigma=.08)
        self.assertGreater(raw_push,0.0)
        self.assertAlmostEqual(push,raw_push,places=12)
        self.assertAlmostEqual(p,raw/(1-raw_push),places=12)

    def test_evidence_gate_rejects_missing_or_stale_generation(self):
        ok,reason=backfill._calibration_evidence_status(True,None,3)
        self.assertFalse(ok)
        self.assertEqual(reason,"BASELINE_GENERATION_MISSING_OR_MISMATCH")
        ok,reason=backfill._calibration_evidence_status(True,"older-generation",3)
        self.assertFalse(ok)
        self.assertEqual(reason,"BASELINE_GENERATION_MISSING_OR_MISMATCH")

    def test_evidence_gate_requires_complete_baseline_and_options(self):
        ok,reason=backfill._calibration_evidence_status(False,contract.MODEL_GENERATION_FINGERPRINT,3)
        self.assertFalse(ok)
        self.assertEqual(reason,"MISSING_PRE_CANDIDATE_BASELINE")
        ok,reason=backfill._calibration_evidence_status(True,contract.MODEL_GENERATION_FINGERPRINT,0)
        self.assertFalse(ok)
        self.assertEqual(reason,"NO_SETTLED_BASELINE_OPTIONS")

    def test_evidence_gate_accepts_exact_current_generation(self):
        ok,reason=backfill._calibration_evidence_status(True,contract.MODEL_GENERATION_FINGERPRINT,3)
        self.assertTrue(ok)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
