import unittest

from v14 import MODEL_GENERATION
from v14.native_payload import authorize_payload, build_native_discord_payload


def _candidate():
    return {
        "role": "CANDIDATE_NON_PUBLISHING",
        "native_acquisition": True,
        "legacy_acquisition_adapter": False,
        "market_probability_used_as_feature": False,
        "target_date": "2026-08-25",
        "analyzed_at": "2026-08-25T18:00:00Z",
        "coverage": {"priced_games": 1},
        "results": [{
            "game_pk": "123",
            "game_date": "2026-08-25T23:00:00Z",
            "analyzed_at": "2026-08-25T18:00:00Z",
            "phase": "FINAL",
            "home": "Home",
            "away": "Away",
            "ctx": {"home": "Home", "away": "Away"},
            "canonical_lines": {"TOTAL": 8.5},
            "line_selection": {"line": 8.5, "market_price_used_as_feature": False},
            "v14_prediction": {
                "role": "PRODUCTION",
                "model_generation": MODEL_GENERATION,
                "game_pk": "123",
                "game_date": "2026-08-25T23:00:00Z",
                "analyzed_at": "2026-08-25T18:00:00Z",
                "home": "Home",
                "away": "Away",
                "total_line": 8.5,
                "market_probability_used_as_feature": False,
                "probabilities": {
                    "away_ml": .45, "home_ml": .55,
                    "away_plus_1_5": .62, "home_minus_1_5": .38,
                    "home_plus_1_5": .69, "away_minus_1_5": .31,
                    "over": .52, "under": .48,
                },
            },
        }],
    }


class V14NativePayloadTests(unittest.TestCase):
    def test_builder_stays_unauthorized_by_default(self):
        payload = build_native_discord_payload(_candidate())
        self.assertEqual(payload["role"], "PRODUCTION_PAYLOAD_UNAUTHORIZED")
        self.assertFalse(payload["publication_authorized"])
        self.assertTrue(payload["native_acquisition"])
        self.assertFalse(payload["legacy_acquisition_adapter"])
        self.assertFalse(payload["legacy_probability_used_for_publication"])
        self.assertEqual(payload["chosen"], [])
        self.assertEqual(payload["combo"], {})
        self.assertEqual(len(payload["results"]), 1)

    def test_authorization_requires_explicit_external_parity_gate(self):
        payload = build_native_discord_payload(_candidate())
        with self.assertRaisesRegex(ValueError, "parity"):
            authorize_payload(payload, parity_authorized=False)
        authorized = authorize_payload(payload, parity_authorized=True)
        self.assertEqual(authorized["role"], "PRODUCTION")
        self.assertTrue(authorized["publication_authorized"])
        self.assertEqual(authorized["authorization_basis"], "external-native-parity-gate")

    def test_builder_rejects_legacy_candidate(self):
        candidate = _candidate()
        candidate["legacy_acquisition_adapter"] = True
        with self.assertRaisesRegex(ValueError, "legacy"):
            build_native_discord_payload(candidate)


if __name__ == "__main__":
    unittest.main()
