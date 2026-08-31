import unittest

from v14 import MODEL_GENERATION
from v14.production_runtime import MIN_MATCHED_SCHEDULED_COVERAGE, MIN_PRICED_MATCHED_COVERAGE, validate_candidate_coverage, validate_production_payload

GAME_DATE="2026-08-31T20:00:00Z"
ANALYZED_AT="2026-08-31T19:30:00Z"


def _prediction():
    return {"role":"PRODUCTION","model_generation":MODEL_GENERATION,"market_probability_used_as_feature":False,"game_date":GAME_DATE,"analyzed_at":ANALYZED_AT,"phase":"FINAL","probabilities":{"away_ml":.45,"home_ml":.55,"away_plus_1_5":.62,"home_minus_1_5":.38,"home_plus_1_5":.70,"away_minus_1_5":.30,"over":.52,"under":.48}}


def _payload():
    return {"role":"PRODUCTION","publication_authorized":True,"model_generation":MODEL_GENERATION,"native_acquisition":True,"legacy_acquisition_adapter":False,"legacy_probability_used_for_publication":False,"market_probability_used_as_feature":False,"chosen":[],"combo":{},"results":[{"game_pk":"123","game_date":GAME_DATE,"analyzed_at":ANALYZED_AT,"phase":"FINAL","model_generation":MODEL_GENERATION,"native_acquisition":True,"market_snapshot":{},"execution_market":{},"market_diagnostics":{},"v14_prediction":_prediction()}]}

class V14ProductionRuntimeTests(unittest.TestCase):
    def test_native_production_payload_contract(self): validate_production_payload(_payload())
    def test_legacy_acquisition_is_rejected(self):
        payload=_payload(); payload["legacy_acquisition_adapter"]=True
        with self.assertRaisesRegex(ValueError,"legacy acquisition"): validate_production_payload(payload)
    def test_market_probability_feature_leak_is_rejected(self):
        payload=_payload(); payload["results"][0]["v14_prediction"]["market_probability_used_as_feature"]=True
        with self.assertRaisesRegex(ValueError,"market probability"): validate_production_payload(payload)
    def test_invalid_probability_complement_is_rejected(self):
        payload=_payload(); payload["results"][0]["v14_prediction"]["probabilities"]["home_ml"]=.60
        with self.assertRaisesRegex(ValueError,"probability surface"): validate_production_payload(payload)
    def test_market_audit_state_is_required(self):
        payload=_payload(); del payload["results"][0]["market_snapshot"]
        with self.assertRaisesRegex(ValueError,"market audit"): validate_production_payload(payload)
    def test_execution_market_state_is_required(self):
        payload=_payload(); del payload["results"][0]["execution_market"]
        with self.assertRaisesRegex(ValueError,"execution state"): validate_production_payload(payload)
    def test_candidate_coverage_gates_both_schedule_matching_and_pricing(self):
        validate_candidate_coverage({"coverage":{"scheduled_future_games":10,"matched_odds_games":8,"priced_games":8}})
        self.assertEqual(MIN_PRICED_MATCHED_COVERAGE,.80); self.assertEqual(MIN_MATCHED_SCHEDULED_COVERAGE,.80)
        with self.assertRaisesRegex(RuntimeError,"odds/schedule coverage too low"): validate_candidate_coverage({"coverage":{"scheduled_future_games":10,"matched_odds_games":7,"priced_games":7}})
        with self.assertRaisesRegex(RuntimeError,"priced/matched coverage too low"): validate_candidate_coverage({"coverage":{"scheduled_future_games":10,"matched_odds_games":10,"priced_games":7}})
        with self.assertRaisesRegex(RuntimeError,"no priced games"): validate_candidate_coverage({"coverage":{"scheduled_future_games":10,"matched_odds_games":10,"priced_games":0}})
    def test_bet_requires_validated_sharp_sportsbook_source(self):
        payload=_payload(); cert={"model_generation":MODEL_GENERATION,"certified":True,"markets":{"ML":{"betting_certified":True}}}; payload["betting_certification"]=cert; result=payload["results"][0]; result["betting_certification"]=cert; result["decision"]={"candidates":[{"status":"BET","canonical_market":"ML","edge_qualified":True,"research_ready":True,"execution_book":"pinnacle","price":1.9,"sharp_sportsbook_source_count":0}]}
        with self.assertRaisesRegex(ValueError,"sharp sportsbook"): validate_production_payload(payload)
        result["decision"]["candidates"][0]["sharp_sportsbook_source_count"]=1; validate_production_payload(payload)
    def test_bet_outside_certified_10_60m_window_is_rejected(self):
        payload=_payload(); cert={"model_generation":MODEL_GENERATION,"certified":True,"markets":{"ML":{"betting_certified":True}}}; payload["betting_certification"]=cert; result=payload["results"][0]; result["betting_certification"]=cert; result["analyzed_at"]="2026-08-31T18:30:00Z"; result["v14_prediction"]["analyzed_at"]="2026-08-31T18:30:00Z"; result["decision"]={"candidates":[{"status":"BET","canonical_market":"ML","edge_qualified":True,"research_ready":True,"execution_book":"pinnacle","price":1.9,"sharp_sportsbook_source_count":1}]}
        with self.assertRaisesRegex(ValueError,"outside certified FINAL 10-60m"): validate_production_payload(payload)

if __name__=="__main__": unittest.main()
