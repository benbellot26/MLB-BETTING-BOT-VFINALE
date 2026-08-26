import unittest

from v14 import MODEL_GENERATION
from v14.production_runtime import MIN_PRICED_MATCHED_COVERAGE, validate_candidate_coverage, validate_production_payload


def _prediction():
    return {"role":"PRODUCTION","model_generation":MODEL_GENERATION,"market_probability_used_as_feature":False,"probabilities":{"away_ml":.45,"home_ml":.55,"away_plus_1_5":.62,"home_minus_1_5":.38,"home_plus_1_5":.70,"away_minus_1_5":.30,"over":.52,"under":.48}}


def _payload():
    return {"role":"PRODUCTION","publication_authorized":True,"model_generation":MODEL_GENERATION,"native_acquisition":True,"legacy_acquisition_adapter":False,"legacy_probability_used_for_publication":False,"market_probability_used_as_feature":False,"chosen":[],"combo":{},"results":[{"game_pk":"123","model_generation":MODEL_GENERATION,"native_acquisition":True,"market_snapshot":{},"execution_market":{},"market_diagnostics":{},"v14_prediction":_prediction()}]}

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
    def test_candidate_coverage_gate(self):
        validate_candidate_coverage({"coverage":{"matched_odds_games":10,"priced_games":8}})
        self.assertEqual(MIN_PRICED_MATCHED_COVERAGE,.80)
        with self.assertRaisesRegex(RuntimeError,"coverage too low"): validate_candidate_coverage({"coverage":{"matched_odds_games":10,"priced_games":7}})
        with self.assertRaisesRegex(RuntimeError,"no priced games"): validate_candidate_coverage({"coverage":{"matched_odds_games":10,"priced_games":0}})

if __name__=="__main__": unittest.main()
