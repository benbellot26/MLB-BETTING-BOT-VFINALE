import json
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION
from v14.production_runtime import choose_total_line, promote_payload


def _option(market, name, point=None, p=.5):
    return {
        "market": market,
        "name": name,
        "point": point,
        "p_baseball_calibrated": p,
        "p_predictive_final": p,
        "p_effective": p,
    }


def _result():
    return {
        "game_pk": "123",
        "game_date": "2026-08-25T23:00:00+00:00",
        "analyzed_at": "2026-08-25T18:00:00+00:00",
        "as_of": "2026-08-25T18:00:00+00:00",
        "phase": "FINAL",
        "ctx": {"home": "Home", "away": "Away"},
        "model_generation": "legacy",
        "game": {"gamePk": 123, "gameDate": "2026-08-25T23:00:00+00:00", "venue": {"name": "Unknown Test Park"}},
        "features": {
            "structural_home_mu": 4.5,
            "structural_away_mu": 4.2,
            "park_factor_runtime": {"static_factor": 1.0, "venue": "Unknown Test Park", "active": False},
            "historical_bootstrap": {"run_prior": {"active": False}, "v13_run_mean_prior": {"active": False}},
            "learned_run_adjustment": {"active": False},
            "run_dispersion": 7.5,
            "run_environment_sigma": 0.08,
            "extra_innings_home_probability": 0.5,
        },
        "canonical_lines": {"TOTAL": 8.0},
        "options": [
            _option("ML", "Away"), _option("ML", "Home"),
            _option("RUNLINE", "Away", +1.5), _option("RUNLINE", "Away", -1.5),
            _option("RUNLINE", "Home", +1.5), _option("RUNLINE", "Home", -1.5),
            _option("TOTAL", "over", 8.0), _option("TOTAL", "under", 8.0),
            _option("TOTAL", "over", 8.5), _option("TOTAL", "under", 8.5),
        ],
    }


class V14ProductionRuntimeTests(unittest.TestCase):
    def test_half_run_total_is_selected_when_canonical_is_integer(self):
        self.assertEqual(choose_total_line(_result()), 8.5)

    def test_payload_promotes_user_facing_surface_to_v14(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "features.jsonl"
            store.write_text("", encoding="utf-8")
            payload = promote_payload({"results": [_result()], "report": {}, "health": {}}, feature_store=store)
        self.assertEqual(payload["model_generation"], MODEL_GENERATION)
        self.assertFalse(payload["legacy_probability_used_for_publication"])
        result = payload["results"][0]
        self.assertEqual(result["model_generation"], MODEL_GENERATION)
        self.assertEqual(result["canonical_lines"]["TOTAL"], 8.5)
        self.assertIn("v14_prediction", result)
        probabilities = result["v14_prediction"]["probabilities"]
        self.assertAlmostEqual(probabilities["home_ml"] + probabilities["away_ml"], 1.0, places=12)
        displayed = [o for o in result["options"] if o.get("model_generation") == MODEL_GENERATION]
        self.assertEqual(len(displayed), 8)
        self.assertTrue(all(o.get("market_probability_used_as_feature") is False for o in displayed))

    def test_fails_closed_without_complete_half_run_total(self):
        result = _result()
        result["options"] = [o for o in result["options"] if o.get("point") != 8.5]
        with self.assertRaisesRegex(ValueError, "half-run"):
            choose_total_line(result)


if __name__ == "__main__":
    unittest.main()
