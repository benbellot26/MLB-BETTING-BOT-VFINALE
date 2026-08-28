from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from v14.historical_distribution_shadow import evaluate, load


def _artifact():
    artifact = load()
    if not artifact:
        raise AssertionError("repository distribution candidate must be valid for tests")
    return copy.deepcopy(artifact)


def _prediction():
    return {
        "game_pk": "1",
        "game_date": "2026-08-29T20:00:00Z",
        "analyzed_at": "2026-08-29T18:00:00Z",
        "phase": "FINAL",
        "home": "Home",
        "away": "Away",
        "model_generation": "g",
        "total_line": 8.5,
        "run_projection": {"home_mu": 4.6, "away_mu": 4.1, "extra_innings_home_probability": 0.496},
        "probabilities": {"home_ml": 0.55, "away_ml": 0.45, "home_minus_1_5": 0.40, "away_plus_1_5": 0.60, "home_plus_1_5": 0.69, "away_minus_1_5": 0.31, "over": 0.52, "under": 0.48},
    }


class HistoricalDistributionShadowTests(unittest.TestCase):
    def test_repository_artifact_is_enabled_only_as_validated_shadow(self):
        out = load()
        self.assertEqual(out.get("schema"), "pulsar-v14-historical-distribution-candidate-v2")
        self.assertEqual(out.get("status"), "HISTORICAL_VALIDATED_SHADOW")
        self.assertFalse(out.get("auto_activation"))
        self.assertFalse(out.get("champion_impact"))
        self.assertTrue(out.get("native_live_confirmation_required"))
        self.assertTrue(out.get("candidate_fingerprint"))

    def test_rolling_dataset_hash_change_does_not_disable_frozen_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = _artifact()
            ap = Path(td) / "a.json"
            mp = Path(td) / "m.json"
            ap.write_text(json.dumps(artifact), encoding="utf-8")
            mp.write_text(json.dumps({"dataset_content_sha256": "future-refresh", "feature_contract_sha256": artifact["feature_contract_sha256"]}), encoding="utf-8")
            self.assertEqual(load(ap, mp).get("candidate_id"), artifact["candidate_id"])

    def test_feature_contract_change_rejects_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = _artifact()
            ap = Path(td) / "a.json"
            mp = Path(td) / "m.json"
            ap.write_text(json.dumps(artifact), encoding="utf-8")
            mp.write_text(json.dumps({"feature_contract_sha256": "0" * 64}), encoding="utf-8")
            self.assertEqual(load(ap, mp), {})

    def test_tampered_injected_parameters_fail_closed(self):
        artifact = _artifact()
        artifact["candidate_parameters"]["dispersion"] = 99.0
        out = evaluate(_prediction(), artifact=artifact)
        self.assertEqual(out["status"], "COLLECTING")

    def test_evaluate_produces_alternate_probabilities_without_champion_impact(self):
        artifact = _artifact()
        out = evaluate(_prediction(), artifact=artifact)
        self.assertEqual(out["status"], "READY_SHADOW")
        self.assertEqual(out["candidate_id"], artifact["candidate_id"])
        self.assertEqual(out["candidate_fingerprint"], artifact["candidate_fingerprint"])
        self.assertFalse(out["champion_impact"])
        self.assertAlmostEqual(out["candidate_probabilities"]["home_ml"] + out["candidate_probabilities"]["away_ml"], 1.0)
        self.assertIn("home_ml", out["probability_delta"])


if __name__ == "__main__":
    unittest.main()
