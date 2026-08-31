from datetime import datetime, timezone
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.certification import evaluate
from v14.certification_timing import CERTIFICATION_RUN_TRIGGER

MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")
NOW=datetime(2026,8,26,14,0,tzinfo=timezone.utc)
FRESH="2026-08-26T13:00:00+00:00"
OBSERVED="2026-08-26T12:00:00+00:00"


def probability_ready():
    markets={}; calibrators={}
    for market in MARKETS:
        markets[market]={"n":500,"ece":.02,"sharp_benchmark":{"paired_n":500,"brier_gain_ci95_lower":.002,"logloss_gain_ci95_lower":0.0,"brier_gain_vs_sharp":.01,"logloss_gain_vs_sharp":.01}}
        calibrators[f"MARKET:{market}"]={"accepted":True,"active":False,"status":"VALIDATED_IDENTITY"}
        calibrators[f"PHASE:FINAL:{market}"]={"accepted":True,"active":False,"status":"VALIDATED_IDENTITY"}
    performance={
        "schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,
        "generated_at":FRESH,"games_settled":700,"latest_observation_at":OBSERVED,"markets":markets,
        "segments":{"rolling":{"60d":{"through":OBSERVED,"markets":{}}}},
        "certification_cohort":{"phase":"FINAL","run_trigger":CERTIFICATION_RUN_TRIGGER,"games":700,"latest_observation_at":OBSERVED,"markets":markets,"rolling":{"60d":{"through":OBSERVED,"markets":{}}}},
    }
    calibration={"schema":"pulsar-v14-calibration-v3","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"latest_observation_at":OBSERVED,"calibrators":calibrators}
    return performance,calibration


def clv(n=120,mean=.40,positive=.56,ci=.08,*,benchmark=None,method="paired nonparametric bootstrap mean"):
    row={"n":n,"mean_clv":mean,"positive_rate":positive,"mean_clv_ci95_lower":ci,"mean_clv_ci95_upper":.70,"inference_method":method,"bootstrap_reps":5000}
    if benchmark is not None:row["benchmark"]=benchmark
    return row


def paper(primary=None,execution=None,close_at=FRESH,phase="FINAL",trigger=CERTIFICATION_RUN_TRIGGER):
    scoped={}
    if primary is not None:
        primary=dict(primary); primary.setdefault("benchmark","PINNACLE_NO_VIG"); scoped["certification_clv"]=primary
    if execution is not None: scoped["execution_clv"]=execution
    if primary is not None or execution is not None: scoped["latest_certified_close_at"]=close_at
    return {"schema":"pulsar-v14-paper-bet-performance-v8","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"certification_entry_phase":phase,"certification_run_trigger":trigger,"primary_clv_benchmark":"PINNACLE_NO_VIG","legacy_consensus_certification_clv_can_certify":False,"by_market":({"ML":scoped} if scoped else {})}


def primary_sharp(*,brier_lower=.002,logloss_lower=0.0,paired_n=500):
    markets={}
    for market in MARKETS:
        markets[market]={"model_vs_primary":{"paired_n":paired_n,"model_metrics":{"n":paired_n,"brier":.22,"logloss":.64,"ece":.02},"brier_gain":{"n":paired_n,"mean":.01,"ci95_lower":brier_lower,"ci95_upper":.02,"method":"paired nonparametric bootstrap mean","reps":5000},"logloss_gain":{"n":paired_n,"mean":.01,"ci95_lower":logloss_lower,"ci95_upper":.02,"method":"paired nonparametric bootstrap mean","reps":5000},"calendar_block_brier_gain":{"n":paired_n,"blocks":100,"mean":.01,"ci95_lower":.001,"ci95_upper":.02,"method":"calendar-block nonparametric bootstrap mean","reps":5000}}}
    return {"schema":"pulsar-v14-sharp-benchmark-report-v1","generated_at":FRESH,"model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"primary_benchmark":"PINNACLE_NO_VIG","certification_phase":"FINAL","certification_run_trigger":CERTIFICATION_RUN_TRIGGER,"certification":{"phase":"FINAL","run_trigger":CERTIFICATION_RUN_TRIGGER,"games":700,"markets":markets},"phases":{"FINAL":{"games":700,"markets":markets}}}


class V14StrictCertificationTests(unittest.TestCase):
    def test_one_markets_clv_cannot_certify_another_market(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertTrue(out["markets"]["ML"]["betting_certified"]); self.assertFalse(out["markets"]["TOTAL_OVER"]["betting_certified"]); self.assertIn("paper_certification_clv_n<100",out["markets"]["TOTAL_OVER"]["betting_failures"])

    def test_primary_executable_to_sharp_close_requires_positive_ci(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(ci=None),clv(n=80)),now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"]); self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_certification_clv_ci95_missing",out["markets"]["ML"]["betting_failures"])

    def test_negative_primary_clv_confidence_bound_blocks_betting(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(n=200,ci=-.03),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_certification_clv_ci95_not_positive",out["markets"]["ML"]["betting_failures"])

    def test_same_book_execution_evidence_is_also_required(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(),None),now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_execution_clv_n<50",out["markets"]["ML"]["betting_failures"])

    def test_legacy_performance_cannot_certify_even_with_good_nominal_metrics(self):
        performance,calibration=probability_ready(); performance.pop("schema"); out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("strict_performance_schema_required",out["markets"]["ML"]["failures"])

    def test_calibration_schema_is_part_of_certification_contract(self):
        performance,calibration=probability_ready(); calibration.pop("schema"); out=evaluate(performance,calibration,{},now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("strict_calibration_schema_required",out["markets"]["ML"]["failures"])

    def test_probability_policy_is_part_of_calibration_contract(self):
        performance,calibration=probability_ready(); calibration["probability_policy_id"]="old-policy"; out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("calibration_probability_policy_mismatch",out["markets"]["ML"]["failures"])

    def test_performance_probability_policy_is_required(self):
        performance,calibration=probability_ready(); performance["probability_policy_id"]="old-policy"; out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("performance_probability_policy_mismatch",out["markets"]["ML"]["failures"])

    def test_paper_probability_policy_is_required(self):
        performance,calibration=probability_ready(); p=paper(clv(),clv(n=80)); p["probability_policy_id"]="old-policy"; out=evaluate(performance,calibration,p,now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"]); self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("strict_pinnacle_primary_scheduled_final_paper_schema_required",out["markets"]["ML"]["betting_failures"])

    def test_wrong_generation_paper_evidence_cannot_certify(self):
        performance,calibration=probability_ready(); p=paper(clv(n=200),clv(n=80)); p["model_generation"]="old-generation"; out=evaluate(performance,calibration,p,now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("strict_pinnacle_primary_scheduled_final_paper_schema_required",out["markets"]["ML"]["betting_failures"])

    def test_non_final_paper_evidence_cannot_certify_final_strategy(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(n=200),clv(n=80),phase="EARLY"),now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"])
        self.assertFalse(out["markets"]["ML"]["betting_certified"])
        self.assertIn("strict_pinnacle_primary_scheduled_final_paper_schema_required",out["markets"]["ML"]["betting_failures"])

    def test_manual_final_paper_evidence_cannot_certify_scheduled_strategy(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(n=200),clv(n=80),trigger="MANUAL"),now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"])
        self.assertFalse(out["markets"]["ML"]["betting_certified"])
        self.assertIn("strict_pinnacle_primary_scheduled_final_paper_schema_required",out["markets"]["ML"]["betting_failures"])

    def test_legacy_v7_consensus_clv_cannot_certify(self):
        performance,calibration=probability_ready(); p=paper(clv(n=200),clv(n=80)); p["schema"]="pulsar-v14-paper-bet-performance-v7"; p.pop("primary_clv_benchmark"); p.pop("legacy_consensus_certification_clv_can_certify")
        out=evaluate(performance,calibration,p,now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("strict_pinnacle_primary_scheduled_final_paper_schema_required",out["markets"]["ML"]["betting_failures"])

    def test_wrong_primary_clv_benchmark_cannot_certify(self):
        performance,calibration=probability_ready(); p=paper(clv(n=200),clv(n=80)); p["by_market"]["ML"]["certification_clv"]["benchmark"]="WEIGHTED_SHARP_CONSENSUS"
        out=evaluate(performance,calibration,p,now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_certification_clv_benchmark_mismatch",out["markets"]["ML"]["betting_failures"])

    def test_nonbootstrap_paper_clv_cannot_certify(self):
        performance,calibration=probability_ready(); p=paper(clv(n=200,method="normal approximation"),clv(n=80))
        out=evaluate(performance,calibration,p,now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_certification_clv_paired_bootstrap_required",out["markets"]["ML"]["betting_failures"])

    def test_stale_probability_report_expires_fail_closed(self):
        performance,calibration=probability_ready(); performance["generated_at"]="2026-08-23T00:00:00+00:00"; out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("performance_evidence_stale>48h",out["markets"]["ML"]["failures"])

    def test_fresh_report_over_stale_underlying_observations_fails_closed(self):
        performance,calibration=probability_ready(); stale="2026-08-20T00:00:00+00:00"; performance["segments"]["rolling"]["60d"]["through"]=stale; calibration["latest_observation_at"]=stale; out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertTrue(any("latest_performance_observation_stale" in reason for reason in out["markets"]["ML"]["failures"]))

    def test_stale_paper_close_blocks_betting_even_if_report_is_fresh(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(),clv(n=80),close_at="2026-08-20T00:00:00+00:00"),now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"]); self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertTrue(any("latest_certified_close_stale" in reason for reason in out["markets"]["ML"]["betting_failures"]))

    def test_production_primary_benchmark_missing_fails_closed(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW,sharp_benchmark_report={},require_primary_benchmark=True)
        self.assertFalse(out["markets"]["ML"]["probability_certified"])
        self.assertIn("strict_primary_sharp_benchmark_schema_required",out["markets"]["ML"]["failures"])

    def test_canonical_final_pinnacle_bootstrap_can_satisfy_extra_gate(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW,sharp_benchmark_report=primary_sharp(),require_primary_benchmark=True)
        self.assertTrue(out["markets"]["ML"]["probability_certified"])
        self.assertEqual((out["policy"] or {}).get("primary_sharp_benchmark"),"PINNACLE_NO_VIG")
        self.assertEqual((out["policy"] or {}).get("primary_sharp_phase"),"FINAL")
        self.assertEqual((out["policy"] or {}).get("certification_run_trigger"),CERTIFICATION_RUN_TRIGGER)
        self.assertEqual((out["policy"] or {}).get("paper_entry_phase"),"FINAL")
        self.assertEqual((out["policy"] or {}).get("paper_primary_clv_benchmark"),"PINNACLE_NO_VIG")

    def test_primary_pinnacle_bootstrap_negative_ci_blocks(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW,sharp_benchmark_report=primary_sharp(brier_lower=-.001),require_primary_benchmark=True)
        self.assertFalse(out["markets"]["ML"]["probability_certified"])
        self.assertIn("pinnacle_final_brier_bootstrap_ci95_not_positive",out["markets"]["ML"]["failures"])


if __name__=="__main__": unittest.main()
