from datetime import datetime, timezone
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.certification import evaluate

MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")
NOW=datetime(2026,8,26,14,0,tzinfo=timezone.utc)
FRESH="2026-08-26T13:00:00+00:00"
OBSERVED="2026-08-26T12:00:00+00:00"


def probability_ready():
    markets={}; calibrators={}
    for market in MARKETS:
        markets[market]={"n":500,"ece":.02,"sharp_benchmark":{"paired_n":500,"brier_gain_ci95_lower":.002,"logloss_gain_ci95_lower":0.0,"brier_gain_vs_sharp":.01,"logloss_gain_vs_sharp":.01}}
        calibrators[f"MARKET:{market}"]={"accepted":True,"active":False,"status":"VALIDATED_IDENTITY"}
    performance={"schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,"generated_at":FRESH,"games_settled":700,"markets":markets,"segments":{"rolling":{"60d":{"through":OBSERVED,"markets":{}}}}}
    calibration={"schema":"pulsar-v14-calibration-v3","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"latest_observation_at":OBSERVED,"calibrators":calibrators}
    return performance,calibration


def clv(n=120,mean=.40,positive=.56,ci=.08):
    return {"n":n,"mean_clv":mean,"positive_rate":positive,"mean_clv_ci95_lower":ci,"mean_clv_ci95_upper":.70}


def paper(primary=None,execution=None,close_at=FRESH):
    scoped={}
    if primary is not None: scoped["certification_clv"]=primary
    if execution is not None: scoped["execution_clv"]=execution
    if primary is not None or execution is not None: scoped["latest_certified_close_at"]=close_at
    return {"schema":"pulsar-v14-paper-bet-performance-v6","model_generation":MODEL_GENERATION,"generated_at":FRESH,"by_market":({"ML":scoped} if scoped else {})}


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

    def test_probability_policy_is_part_of_certification_contract(self):
        performance,calibration=probability_ready(); calibration["probability_policy_id"]="old-policy"; out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("probability_policy_mismatch",out["markets"]["ML"]["failures"])

    def test_wrong_generation_paper_evidence_cannot_certify(self):
        performance,calibration=probability_ready(); p=paper(clv(n=200),clv(n=80)); p["model_generation"]="old-generation"; out=evaluate(performance,calibration,p,now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("strict_current_generation_market_specific_paper_schema_required",out["markets"]["ML"]["betting_failures"])

    def test_stale_probability_report_expires_fail_closed(self):
        performance,calibration=probability_ready(); performance["generated_at"]="2026-08-23T00:00:00+00:00"; out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("performance_evidence_stale>48h",out["markets"]["ML"]["failures"])

    def test_fresh_report_over_stale_underlying_observations_fails_closed(self):
        performance,calibration=probability_ready(); stale="2026-08-20T00:00:00+00:00"; performance["segments"]["rolling"]["60d"]["through"]=stale; calibration["latest_observation_at"]=stale; out=evaluate(performance,calibration,paper(clv(),clv(n=80)),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertTrue(any("latest_performance_observation_stale" in reason for reason in out["markets"]["ML"]["failures"]))

    def test_stale_paper_close_blocks_betting_even_if_report_is_fresh(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper(clv(),clv(n=80),close_at="2026-08-20T00:00:00+00:00"),now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"]); self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertTrue(any("latest_certified_close_stale" in reason for reason in out["markets"]["ML"]["betting_failures"]))


if __name__=="__main__": unittest.main()
