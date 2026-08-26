import unittest

from v14 import MODEL_GENERATION
from v14.certification import evaluate


MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")


def probability_ready():
    markets={}; calibrators={}
    for market in MARKETS:
        markets[market]={"n":500,"ece":0.02,"sharp_benchmark":{"paired_n":500,"brier_gain_ci95_lower":0.002,"logloss_gain_ci95_lower":0.0,"brier_gain_vs_sharp":0.01,"logloss_gain_vs_sharp":0.01}}
        calibrators[f"MARKET:{market}"]={"accepted":True,"active":False,"status":"VALIDATED_IDENTITY"}
    performance={"schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,"games_settled":700,"markets":markets}
    calibration={"schema":"pulsar-v14-calibration-v2","model_generation":MODEL_GENERATION,"calibrators":calibrators}
    return performance,calibration


class V14StrictCertificationTests(unittest.TestCase):
    def test_one_markets_clv_cannot_certify_another_market(self):
        performance,calibration=probability_ready(); paper={"schema":"pulsar-v14-paper-bet-performance-v3","by_market":{"ML":{"clv":{"n":120,"mean_clv":0.40,"positive_rate":0.56,"mean_clv_ci95_lower":0.08}}},"clv":{"n":120,"mean_clv":0.40,"positive_rate":0.56,"mean_clv_ci95_lower":0.08}}
        out=evaluate(performance,calibration,paper)
        self.assertTrue(out["markets"]["ML"]["betting_certified"]); self.assertFalse(out["markets"]["TOTAL_OVER"]["betting_certified"]); self.assertIn("paper_clv_n<100",out["markets"]["TOTAL_OVER"]["betting_failures"])

    def test_new_paper_report_requires_positive_clv_confidence_bound(self):
        performance,calibration=probability_ready(); paper={"schema":"pulsar-v14-paper-bet-performance-v3","by_market":{"ML":{"clv":{"n":120,"mean_clv":0.40,"positive_rate":0.56,"mean_clv_ci95_lower":None}}}}
        out=evaluate(performance,calibration,paper)
        self.assertTrue(out["markets"]["ML"]["probability_certified"]); self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_clv_ci95_missing",out["markets"]["ML"]["betting_failures"])

    def test_negative_clv_confidence_bound_blocks_betting(self):
        performance,calibration=probability_ready(); paper={"schema":"pulsar-v14-paper-bet-performance-v3","by_market":{"ML":{"clv":{"n":200,"mean_clv":0.10,"positive_rate":0.55,"mean_clv_ci95_lower":-0.03}}}}
        out=evaluate(performance,calibration,paper)
        self.assertFalse(out["markets"]["ML"]["betting_certified"]); self.assertIn("paper_clv_ci95_not_positive",out["markets"]["ML"]["betting_failures"])

    def test_legacy_performance_cannot_certify_even_with_good_nominal_metrics(self):
        performance,calibration=probability_ready(); performance.pop("schema")
        paper={"schema":"pulsar-v14-paper-bet-performance-v3","by_market":{"ML":{"clv":{"n":200,"mean_clv":0.40,"positive_rate":0.56,"mean_clv_ci95_lower":0.08}}}}
        out=evaluate(performance,calibration,paper)
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("strict_performance_schema_required",out["markets"]["ML"]["failures"])

    def test_calibration_schema_is_part_of_certification_contract(self):
        performance,calibration=probability_ready(); calibration.pop("schema")
        out=evaluate(performance,calibration,{})
        self.assertFalse(out["markets"]["ML"]["probability_certified"]); self.assertIn("strict_calibration_schema_required",out["markets"]["ML"]["failures"])


if __name__=="__main__": unittest.main()
