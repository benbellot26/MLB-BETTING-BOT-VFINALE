from datetime import datetime, timezone
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14 import certification
from v14.probability_calibration import calibrate_probability, calibrate_surface


NOW=datetime(2026,8,31,12,30,tzinfo=timezone.utc)
NOW_ISO=NOW.isoformat()


def active_artifact():
    return {
        "schema":"pulsar-v14-calibration-v3",
        "model_generation":MODEL_GENERATION,
        "probability_policy_id":PROBABILITY_POLICY_ID,
        "generated_at":NOW_ISO,
        "latest_observation_at":NOW_ISO,
        "calibrators":{
            "PHASE:FINAL:ML":{
                "active":True,"accepted":True,"method":"platt-logit","status":"ACTIVE_TRANSFORM",
                "n":500,"slope":0.55,"intercept":0.4,
            }
        },
    }


def strict_evidence(*,ece=.02,calibration_payload=None):
    market_metrics={
        "n":400,"ece":ece,
        "sharp_benchmark":{
            "paired_n":400,"brier_gain_ci95_lower":.001,"logloss_gain_ci95_lower":0.0,
        },
    }
    performance={
        "schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,
        "probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":NOW_ISO,
        "latest_observation_at":NOW_ISO,"games_settled":600,"markets":{},
        "segments":{"rolling":{}},
        "certification_cohort":{
            "phase":"FINAL","run_trigger":"SCHEDULED_FINAL","games":600,
            "latest_observation_at":NOW_ISO,"markets":{"ML":market_metrics},"rolling":{},
        },
    }
    primary={
        "paired_n":400,
        "model_metrics":{"n":400,"ece":ece},
        "brier_gain":{"method":"paired nonparametric bootstrap mean","n":400,"mean":.004,"ci95_lower":.001,"ci95_upper":.008},
        "logloss_gain":{"method":"paired nonparametric bootstrap mean","n":400,"mean":.003,"ci95_lower":0.0,"ci95_upper":.006},
    }
    sharp={
        "schema":"pulsar-v14-sharp-benchmark-report-v1","model_generation":MODEL_GENERATION,
        "probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":NOW_ISO,
        "primary_benchmark":"PINNACLE_NO_VIG","certification_phase":"FINAL",
        "certification_run_trigger":"SCHEDULED_FINAL",
        "certification":{"phase":"FINAL","run_trigger":"SCHEDULED_FINAL","markets":{"ML":{"model_vs_primary":primary}}},
    }
    cert_clv={
        "n":100,"mean_clv":1.1,"positive_rate":.60,"mean_clv_ci95_lower":.2,"mean_clv_ci95_upper":2.0,
        "inference_method":"paired nonparametric bootstrap mean","benchmark":"PINNACLE_NO_VIG",
    }
    execution_clv={
        "n":50,"mean_clv":.5,"positive_rate":.56,"mean_clv_ci95_lower":.1,"mean_clv_ci95_upper":1.0,
        "inference_method":"paired nonparametric bootstrap mean",
    }
    paper={
        "schema":"pulsar-v14-paper-bet-performance-v8","model_generation":MODEL_GENERATION,
        "probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":NOW_ISO,
        "certification_entry_phase":"FINAL","certification_run_trigger":"SCHEDULED_FINAL",
        "primary_clv_benchmark":"PINNACLE_NO_VIG","legacy_consensus_certification_clv_can_certify":False,
        "by_market":{"ML":{"latest_certified_close_at":NOW_ISO,"latest_primary_close_at":NOW_ISO,"latest_execution_close_at":NOW_ISO,"certification_clv":cert_clv,"execution_clv":execution_clv}},
    }
    calibration_payload=calibration_payload if calibration_payload is not None else {}
    return performance,calibration_payload,paper,sharp


class V14PolicyFreezeTests(unittest.TestCase):
    def test_active_research_calibrator_cannot_change_current_policy_probability(self):
        p=.61
        q,meta=calibrate_probability(p,"ML","FINAL",active_artifact())
        self.assertEqual(q,p)
        self.assertTrue(meta["research_candidate_active"])
        self.assertFalse(meta["production_transform_authorized"])
        self.assertFalse(meta["production_transform_applied"])
        self.assertFalse(meta["active"])
        self.assertEqual(meta["method"],"identity")

    def test_surface_remains_exactly_frozen_when_shadow_transform_is_active(self):
        raw={"home_ml":.61,"away_ml":.39}
        out,meta=calibrate_surface(raw,phase="FINAL",artifact=active_artifact())
        self.assertAlmostEqual(out["home_ml"],.61)
        self.assertAlmostEqual(out["away_ml"],.39)
        self.assertFalse(meta["production_transform_applied"])
        self.assertTrue(meta["any_research_candidate_active"])

    def test_strict_certification_uses_scheduled_final_published_ece_not_shadow_calibrator(self):
        perf,cal,paper,sharp=strict_evidence(calibration_payload={})
        out=certification.evaluate(perf,cal,paper,now=NOW,sharp_benchmark_report=sharp,require_primary_benchmark=True)
        self.assertTrue(out["markets"]["ML"]["probability_certified"])
        self.assertTrue(out["markets"]["ML"]["betting_certified"])
        self.assertEqual(out["markets"]["ML"]["calibration_evidence_source"],"SCHEDULED_FINAL_PUBLISHED_PROBABILITY")
        self.assertNotIn("calibration_not_oos_accepted",out["markets"]["ML"]["failures"])

    def test_shadow_calibrator_cannot_rescue_bad_scheduled_final_ece(self):
        cal=active_artifact()
        perf,cal,paper,sharp=strict_evidence(ece=.20,calibration_payload=cal)
        out=certification.evaluate(perf,cal,paper,now=NOW,sharp_benchmark_report=sharp,require_primary_benchmark=True)
        ml=out["markets"]["ML"]
        self.assertFalse(ml["probability_certified"])
        self.assertFalse(ml["betting_certified"])
        self.assertTrue(any(reason.startswith("ece>") for reason in ml["failures"]))
        self.assertTrue(any(reason.startswith("pinnacle_final_model_ece>") for reason in ml["failures"]))


if __name__=="__main__":
    unittest.main()