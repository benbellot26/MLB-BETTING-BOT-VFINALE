import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.discord import build_game_embed
from v14.uncertainty import intervals
from v14.uncertainty_fit import build as build_uncertainty_artifact


PROBABILITIES = {
    "home_ml": .64,
    "away_ml": .36,
    "home_minus_1_5": .40,
    "away_plus_1_5": .60,
    "away_minus_1_5": .25,
    "home_plus_1_5": .75,
    "over": .55,
    "under": .45,
}


class V14UncertaintyTransparencyTests(unittest.TestCase):
    def test_fallback_is_explicit_and_keeps_existing_widths(self):
        quality = {"eligible": True, "home_lineup_count": 9, "away_lineup_count": 9}
        out = intervals(
            PROBABILITIES,
            {"phase": "FINAL", "markets": {}},
            data_quality=quality,
            starter_degraded=False,
            market_fresh=True,
            artifact={},
        )

        self.assertTrue(out["uses_fallback"])
        self.assertFalse(out["all_empirical_95"])
        self.assertEqual(out["quality_penalty_pp"], 0.0)
        self.assertEqual(out["quality_penalty_reasons"], [])
        self.assertEqual(out["source_by_market"]["ML"], "fallback")
        self.assertEqual(out["selections"]["home_ml"]["band_basis"], "CONSERVATIVE_FALLBACK")
        self.assertFalse(out["selections"]["home_ml"]["empirical_evidence_ready"])
        self.assertAlmostEqual(out["selections"]["home_ml"]["base_half_width_pp"], 6.0)
        self.assertAlmostEqual(out["selections"]["home_ml"]["half_width_pp"], 6.0)
        self.assertAlmostEqual(out["selections"]["home_minus_1_5"]["half_width_pp"], 7.5)
        self.assertAlmostEqual(out["selections"]["over"]["half_width_pp"], 8.5)
        self.assertIn("otherwise fixed conservative market fallback", out["method"])
        self.assertIn("fallback is not an empirical 95% interval", out["note"])

    def test_quality_penalty_components_explain_same_2_2pp_widening(self):
        quality = {"eligible": True, "home_lineup_count": 0, "away_lineup_count": 9}
        out = intervals(
            PROBABILITIES,
            {"phase": "FINAL", "markets": {}},
            data_quality=quality,
            starter_degraded=False,
            market_fresh=True,
            artifact={},
        )

        self.assertAlmostEqual(out["quality_penalty_pp"], 2.2)
        self.assertAlmostEqual(out["selections"]["home_ml"]["half_width_pp"], 8.2)
        self.assertAlmostEqual(out["selections"]["home_minus_1_5"]["half_width_pp"], 9.7)
        self.assertAlmostEqual(out["selections"]["over"]["half_width_pp"], 10.7)
        self.assertEqual(
            [row["code"] for row in out["quality_penalty_reasons"]],
            ["lineup_incomplete", "lineup_severely_incomplete"],
        )

    def test_exact_generation_and_policy_empirical_cell_is_labeled_empirical(self):
        artifact = {
            "schema": "pulsar-v14-uncertainty-fit-v3",
            "model_generation": MODEL_GENERATION,
            "probability_policy_id": PROBABILITY_POLICY_ID,
            "cells": {
                "ML:FINAL:0.6-0.7": {
                    "ready": True,
                    "n": 420,
                    "empirical_half_width": .041,
                }
            },
        }
        quality = {"eligible": True, "home_lineup_count": 9, "away_lineup_count": 9}
        out = intervals(
            PROBABILITIES,
            {"phase": "FINAL", "markets": {}},
            data_quality=quality,
            starter_degraded=False,
            market_fresh=True,
            artifact=artifact,
        )

        row = out["selections"]["home_ml"]
        self.assertEqual(row["uncertainty_source"], "empirical_95")
        self.assertEqual(row["band_basis"], "EMPIRICAL_95")
        self.assertTrue(row["empirical_evidence_ready"])
        self.assertEqual(row["evidence_n"], 420)
        self.assertAlmostEqual(row["base_half_width_pp"], 4.1)
        self.assertAlmostEqual(row["half_width_pp"], 4.1)

    def test_empirical_artifact_without_policy_fails_closed_to_fallback(self):
        artifact = {
            "schema": "pulsar-v14-uncertainty-fit-v2",
            "model_generation": MODEL_GENERATION,
            "cells": {
                "ML:FINAL:0.6-0.7": {
                    "ready": True,
                    "n": 420,
                    "empirical_half_width": .025,
                }
            },
        }
        quality = {"eligible": True, "home_lineup_count": 9, "away_lineup_count": 9}
        out = intervals(
            PROBABILITIES,
            {"phase": "FINAL", "markets": {}},
            data_quality=quality,
            starter_degraded=False,
            market_fresh=True,
            artifact=artifact,
        )
        row = out["selections"]["home_ml"]
        self.assertEqual(row["uncertainty_source"], "fallback")
        self.assertEqual(row["band_basis"], "CONSERVATIVE_FALLBACK")
        self.assertAlmostEqual(row["base_half_width_pp"], 6.0)

    def test_empirical_artifact_from_other_policy_fails_closed_to_fallback(self):
        artifact = {
            "schema": "pulsar-v14-uncertainty-fit-v3",
            "model_generation": MODEL_GENERATION,
            "probability_policy_id": "pulsar-v14-probability-policy-old",
            "cells": {
                "ML:FINAL:0.6-0.7": {
                    "ready": True,
                    "n": 420,
                    "empirical_half_width": .025,
                }
            },
        }
        quality = {"eligible": True, "home_lineup_count": 9, "away_lineup_count": 9}
        out = intervals(
            PROBABILITIES,
            {"phase": "FINAL", "markets": {}},
            data_quality=quality,
            starter_degraded=False,
            market_fresh=True,
            artifact=artifact,
        )
        row = out["selections"]["home_ml"]
        self.assertEqual(row["uncertainty_source"], "fallback")
        self.assertEqual(row["band_basis"], "CONSERVATIVE_FALLBACK")
        self.assertAlmostEqual(row["base_half_width_pp"], 6.0)

    def test_uncertainty_fit_stamps_exact_probability_identity(self):
        artifact = build_uncertainty_artifact([])
        self.assertEqual(artifact["schema"], "pulsar-v14-uncertainty-fit-v3")
        self.assertEqual(artifact["model_generation"], MODEL_GENERATION)
        self.assertEqual(artifact["probability_policy_id"], PROBABILITY_POLICY_ID)

    def test_discord_explains_fallback_and_shows_runline_intervals(self):
        quality = {"eligible": True, "home_lineup_count": 9, "away_lineup_count": 9}
        bands = intervals(
            PROBABILITIES,
            {"phase": "FINAL", "markets": {}},
            data_quality=quality,
            starter_degraded=False,
            market_fresh=True,
            artifact={},
        )
        result = {
            "game_pk": "123",
            "phase": "FINAL",
            "ctx": {
                "away": "Away",
                "home": "Home",
                "away_lineup": {"count": 9},
                "home_lineup": {"count": 9},
            },
            "v14_prediction": {
                "role": "PRODUCTION",
                "model_generation": MODEL_GENERATION,
                "total_line": 8.5,
                "run_projection": {"away_mu": 4.1, "home_mu": 4.6},
                "context_adjustment": {"eligible": True, "feature_as_of": "2026-08-27T08:00:00+00:00"},
                "probabilities": PROBABILITIES,
                "probability_intervals": bands,
            },
        }

        embed = build_game_embed(result)
        by_name = {field["name"]: field["value"] for field in embed["fields"]}
        runline = by_name["⚾ RUN LINE ±1.5"]
        quality_text = by_name["🧪 PROBABILITY QUALITY"]

        self.assertGreaterEqual(runline.count("["), 4)
        self.assertIn("ML **conservative fallback**", quality_text)
        self.assertIn("RL **conservative fallback**", quality_text)
        self.assertIn("Total **conservative fallback**", quality_text)
        self.assertIn("Quality penalty **+0.0 pp**", quality_text)
        self.assertIn("Fallback ≠ empirical 95% CI", quality_text)


if __name__ == "__main__":
    unittest.main()
