from datetime import datetime, timezone
import unittest

from v14 import MODEL_GENERATION
from v14.certification import evaluate

MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")
NOW=datetime(2026,8,26,14,0,tzinfo=timezone.utc)
FRESH="2026-08-26T13:00:00+00:00"


def probability_ready():
    markets={}; calibrators={}
    for market in MARKETS:
        markets[market]={"n":500,"ece":.02,"sharp_benchmark":{"paired_n":500,"brier_gain_ci95_lower":.002,"logloss_gain_ci95_lower":0.0,"brier_gain_vs_sharp":.01,"logloss_gain_vs_sharp":.01}}
        calibrators[f"MARKET:{market}"]={"accepted":True,"active":False,"status":"VALIDATED_IDENTITY"}
    performance={"schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,"generated_at":FRESH,"games_settled":700,"markets":markets}
    calibration={"schema":"pulsar-v14-calibration-v2","model_generation":MODEL_GENERATION,"generated_at":FRESH,"calibrators":calibrators}
    return performance,calibration


def paper(clv=None):
    return {"schema":"pulsar-v14-paper-bet-performance-v5","model_generation":MODEL_GENERATION,"generated_at":FRESH,"by_market":({"ML":{"clv":clv}} if clv is not None else {})}


class V14StrictCertificationTests(unittest.TestCase):
    def test_one_markets_clv_cannot_certify_another_market(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper({"n":120,"mean_clv":.40,"positive_rate":.56,"mean_clv_ci95_lower":.08}),now=NOW)
        self.assertTrue(out["markets"]["ML"]["betting_certified"]); self.assertFalse(out["markets"]["TOTAL_OVER"]["betting_certified"]); self.assertIn("paper_clv_n<100",out["markets"]["TOTAL_OVER"]["betting_failures"])

    def test_new_paper_report_requires_positive_clv_confidence_bound(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper({"n":120,"mean_clv":.40,"positive_rate":.56,"mean_clv_ci95_lower":None}),now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"]); self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_clv_ci95_missing",out["markets"]["ML"]["betting_failures"])

    def test_negative_clv_confidence_bound_blocks_betting(self):
        performance,calibration=probability_ready(); out=evaluate(performance,calibration,paper({"n":200,"mean_clv":.10,"positive_rate":.55,"mean_clv_ci95_lower":-.03}),now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_clv_ci95_not_positive",out["markets"]["ML"]["betting_failures"])

    def test_legacy_performance_cannot_certify_even_with_good_nominal_metrics(self):
        performance,calibration=probability_ready(); performance.pop("schema"); out=evaluate(performance,calibration,paper({"n":200,"mean_clv":.40,"positive_rate":.56,"mean_clv_ci95_lower":.08}),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("strict_performance_schema_required",out["markets"]["ML"]["failures"])

    def test_calibration_schema_is_part_of_certification_contract(self):
        performance,calibration=probability_ready(); calibration.pop("schema"); out=evaluate(performance,calibration,{},now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("strict_calibration_schema_required",out["markets"]["ML"]["failures"])

    def test_wrong_generation_paper_evidence_cannot_certify(self):
        performance,calibration=probability_ready(); p=paper({"n":200,"mean_clv":.40,"positive_rate":.56,"mean_clv_ci95_lower":.08}); p["model_generation"]="old-generation"; out=evaluate(performance,calibration,p,now=NOW)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("strict_current_generation_market_specific_paper_schema_required",out["markets"]["ML"]["betting_failures"])

    def test_stale_probability_evidence_expires_fail_closed(self):
        performance,calibration=probability_ready(); performance["generated_at"]="2026-08-23T00:00:00+00:00"; out=evaluate(performance,calibration,paper({"n":200,"mean_clv":.40,"positive_rate":.56,"mean_clv_ci95_lower":.08}),now=NOW)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("performance_evidence_stale>48h",out["markets"]["ML"]["failures"])

    def test_stale_paper_evidence_blocks_betting_only(self):
        performance,calibration=probability_ready(); p=paper({"n":200,"mean_clv":.40,"positive_rate":.56,"mean_clv_ci95_lower":.08}); p["generated_at"]="2026-08-23T00:00:00+00:00"; out=evaluate(performance,calibration,p,now=NOW)
        self.assertTrue(out["markets"]["ML"]["probability_certified"]); self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_evidence_stale>48h",out["markets"]["ML"]["betting_failures"])

if __name__=="__main__": unittest.main()
