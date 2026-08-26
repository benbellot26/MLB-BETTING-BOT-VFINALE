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
        "coverage": {"priced_games": 1, "matched_odds_games": 1},
        "results": [
            {
                "game_pk": "123",
                "game_date": "2026-08-25T23:00:00Z",
                "analyzed_at": "2026-08-25T18:00:00Z",
                "phase": "FINAL",
                "home": "Home",
                "away": "Away",
                "ctx": {"home": "Home", "away": "Away"},
                "canonical_lines": {"TOTAL": 8.5},
                "line_selection": {"line": 8.5, "market_price_used_as_feature": False},
                "market_snapshot": {
                    "schema": "pulsar-v14-market-snapshot-v2",
                    "markets": {
                        "ML": {
                            "selections": {
                                "home": {"price": 1.90},
                                "away": {"price": 2.00},
                            }
                        }
                    },
                },
                "market_diagnostics": {
                    "schema": "pulsar-v14-market-diagnostics-v1",
                    "markets": {"ML": {"selections": {"home": {"edge_pp": 3.0}}}},
                },
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
                        "away_ml": 0.45,
                        "home_ml": 0.55,
                        "away_plus_1_5": 0.62,
                        "home_minus_1_5": 0.38,
                        "home_plus_1_5": 0.69,
                        "away_minus_1_5": 0.31,
                        "over": 0.52,
                        "under": 0.48,
                    },
                },
            }
        ],
    }


class V14NativePayloadTests(unittest.TestCase):
    def test_builder_stays_unauthorized_and_preserves_market_audit(self):
        payload = build_native_discord_payload(_candidate())
        self.assertEqual(payload["role"], "PRODUCTION_PAYLOAD_UNAUTHORIZED")
        self.assertFalse(payload["publication_authorized"])
        self.assertEqual(payload["chosen"], [])
        self.assertEqual(payload["combo"], {})
        result = payload["results"][0]
        self.assertEqual(result["market_snapshot"]["markets"]["ML"]["selections"]["home"]["price"], 1.90)
        self.assertEqual(result["market_diagnostics"]["markets"]["ML"]["selections"]["home"]["edge_pp"], 3.0)

    def test_authorization_requires_explicit_production_switch(self):
        payload = build_native_discord_payload(_candidate())
        with self.assertRaisesRegex(ValueError, "production"):
            authorize_payload(payload, production_authorized=False)

        authorized = authorize_payload(payload, production_authorized=True)
        self.assertEqual(authorized["role"], "PRODUCTION")
        self.assertTrue(authorized["publication_authorized"])
        basis = authorized["authorization_basis"]
        self.assertEqual(basis["type"], "software-production-contract")
        self.assertEqual(basis["model_generation"], MODEL_GENERATION)
        self.assertFalse(basis["betting_certified"])
        self.assertIn("distinct", basis["note"].lower())

    def test_builder_rejects_legacy_candidate(self):
        candidate = _candidate()
        candidate["legacy_acquisition_adapter"] = True
        with self.assertRaisesRegex(ValueError, "legacy"):
            build_native_discord_payload(candidate)


if __name__ == "__main__":
    unittest.main()
