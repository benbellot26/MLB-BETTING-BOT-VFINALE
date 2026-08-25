import unittest

from v14 import MODEL_GENERATION
from v14.discord import build_game_embed


class V14DiscordTests(unittest.TestCase):
    def test_embed_reads_native_prediction_surface(self):
        result = {
            "game_pk": "123",
            "phase": "FINAL",
            "ctx": {"away": "Away", "home": "Home", "away_lineup": {"count": 9}, "home_lineup": {"count": 9}},
            "v14_prediction": {
                "role": "PRODUCTION",
                "model_generation": MODEL_GENERATION,
                "total_line": 8.5,
                "run_projection": {"away_mu": 4.1, "home_mu": 4.6},
                "context_adjustment": {"eligible": True, "feature_as_of": "2026-08-25T18:00:00+00:00"},
                "probabilities": {
                    "away_ml": .44, "home_ml": .56,
                    "away_plus_1_5": .61, "home_minus_1_5": .39,
                    "home_plus_1_5": .70, "away_minus_1_5": .30,
                    "over": .53, "under": .47,
                },
            },
        }
        embed = build_game_embed(result)
        text = "\n".join(field["value"] for field in embed["fields"])
        self.assertIn("56.0%", text)
        self.assertIn("53.0%", text)
        self.assertIn("Pulsar V14", embed["footer"]["text"])

    def test_embed_rejects_non_v14_prediction(self):
        with self.assertRaisesRegex(ValueError, "V14"):
            build_game_embed({"v14_prediction": {"role": "PRODUCTION", "model_generation": "legacy"}})


if __name__ == "__main__":
    unittest.main()
