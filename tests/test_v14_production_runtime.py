import unittest

from v14 import MODEL_GENERATION
from v14.production_runtime import NATIVE_CUTOVER_EVIDENCE, _validate_cutover_evidence, validate_production_payload


def _prediction():
    return {
        "role": "PRODUCTION",
        "model_generation": MODEL_GENERATION,
        "market_probability_used_as_feature": False,
        "probabilities": {
            "away_ml": .45, "home_ml": .55,
            "away_plus_1_5": .62, "home_minus_1_5": .38,
            "home_plus_1_5": .70, "away_minus_1_5": .30,
            "over": .52, "under": .48,
        },
    }


def _payload():
    return {
        "role": "PRODUCTION",
        "publication_authorized": True,
        "model_generation": MODEL_GENERATION,
        "native_acquisition": True,
        "legacy_acquisition_adapter": False,
        "legacy_probability_used_for_publication": False,
        "market_probability_used_as_feature": False,
        "chosen": [],
        "combo": {},
        "results": [{
            "game_pk": "123",
            "model_generation": MODEL_GENERATION,
            "native_acquisition": True,
            "v14_prediction": _prediction(),
        }],
    }


class V14ProductionRuntimeTests(unittest.TestCase):
    def test_cutover_evidence_is_the_passed_native_parity_run(self):
        _validate_cutover_evidence()
        self.assertEqual(NATIVE_CUTOVER_EVIDENCE["run_id"], 32828843533)
        self.assertEqual(NATIVE_CUTOVER_EVIDENCE["status"], "PASS")
        self.assertEqual(NATIVE_CUTOVER_EVIDENCE["comparable_games"], 15)
        self.assertEqual(NATIVE_CUTOVER_EVIDENCE["candidate_coverage"], 1.0)
        self.assertEqual(NATIVE_CUTOVER_EVIDENCE["mean_abs_structural_run_delta"], 0.0)
        self.assertEqual(NATIVE_CUTOVER_EVIDENCE["max_abs_structural_run_delta"], 0.0)

    def test_native_production_payload_contract(self):
        validate_production_payload(_payload())

    def test_legacy_acquisition_is_rejected(self):
        payload = _payload()
        payload["legacy_acquisition_adapter"] = True
        with self.assertRaisesRegex(ValueError, "legacy acquisition"):
            validate_production_payload(payload)

    def test_market_probability_feature_leak_is_rejected(self):
        payload = _payload()
        payload["results"][0]["v14_prediction"]["market_probability_used_as_feature"] = True
        with self.assertRaisesRegex(ValueError, "market probability"):
            validate_production_payload(payload)

    def test_invalid_probability_complement_is_rejected(self):
        payload = _payload()
        payload["results"][0]["v14_prediction"]["probabilities"]["home_ml"] = .60
        with self.assertRaisesRegex(ValueError, "probability surface"):
            validate_production_payload(payload)


if __name__ == "__main__":
    unittest.main()
