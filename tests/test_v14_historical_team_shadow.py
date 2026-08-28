from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from v14.historical_team_shadow import evaluate, load


def _artifact():
    artifact = load()
    if not artifact:
        raise AssertionError("repository team-run candidate must be valid for tests")
    return copy.deepcopy(artifact)


def _team(rf, ra):
    return {
        "season_to_date": {"games": 50, "runs_for_pg": rf, "runs_against_pg": ra},
        "last_14_games": {"games": 14, "runs_for_pg": rf + 0.1, "runs_against_pg": ra - 0.1},
        "last_7_games": {"games": 7, "runs_for_pg": rf, "runs_against_pg": ra},
        "last_30_games": {"games": 30, "runs_for_pg": rf, "runs_against_pg": ra},
    }


def _history():
    return {"status": "READY_SHADOW", "point_in_time": True, "home": _team(4.8, 4.1), "away": _team(4.2, 4.7)}


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
        "run_projection": {"home_mu": 4.55, "away_mu": 4.15, "dispersion": 7.5, "environment_sigma": 0.08, "extra_innings_home_probability": 0.496},
        "probabilities": {"home_ml": 0.55, "away_ml": 0.45, "home_minus_1_5": 0.40, "away_plus_1_5": 0.60, "home_plus_1_5": 0.69, "away_minus_1_5": 0.31, "over": 0.52, "under": 0.48},
    }


class HistoricalTeamShadowTests(unittest.TestCase):
    def test_repository_artifact_is_immutable_validated_shadow(self):
        out = load()
        self.assertEqual(out.get("schema"), "pulsar-v14-historical-team-run-candidate-v2")
        self.assertEqual(out.get("status"), "HISTORICAL_VALIDATED_SHADOW")
        self.assertFalse(out.get("champion_impact"))
        self.assertTrue(out.get("candidate_fingerprint"))

    def test_rolling_dataset_hash_change_does_not_disable_frozen_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = _artifact()
            ap = Path(td) / "a.json"
            mp = Path(td) / "m.json"
            ap.write_text(json.dumps(artifact), encoding="utf-8")
            mp.write_text(json.dumps({"dataset_content_sha256": "future-refresh", "feature_contract_sha256": artifact["feature_contract_sha256"]}), encoding="utf-8")
            self.assertEqual(load(ap, mp).get("candidate_id"), artifact["candidate_id"])

    def test_feature_contract_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = _artifact()
            ap = Path(td) / "a.json"
            mp = Path(td) / "m.json"
            ap.write_text(json.dumps(artifact), encoding="utf-8")
            mp.write_text(json.dumps({"feature_contract_sha256": "0" * 64}), encoding="utf-8")
            self.assertEqual(load(ap, mp), {})

    def test_tampered_injected_parameters_fail_closed(self):
        artifact = _artifact()
        artifact["parameters"]["offense_weight"] = 0.99
        out = evaluate(_prediction(), _history(), artifact=artifact)
        self.assertEqual(out["status"], "COLLECTING")

    def test_shadow_changes_runs_and_probabilities_without_champion_impact(self):
        artifact = _artifact()
        out = evaluate(_prediction(), _history(), artifact=artifact)
        self.assertEqual(out["status"], "READY_SHADOW")
        self.assertEqual(out["candidate_id"], artifact["candidate_id"])
        self.assertEqual(out["candidate_fingerprint"], artifact["candidate_fingerprint"])
        self.assertFalse(out["champion_impact"])
        self.assertFalse(out["auto_activation"])
        self.assertNotEqual(out["candidate_run_projection"]["home_mu"], out["champion_run_projection"]["home_mu"])
        self.assertAlmostEqual(out["candidate_probabilities"]["home_ml"] + out["candidate_probabilities"]["away_ml"], 1.0)
        self.assertIn("home_ml", out["probability_delta"])

    def test_missing_pit_history_collects_instead_of_guessing(self):
        out = evaluate(_prediction(), {"status": "COLLECTING", "point_in_time": True}, artifact=_artifact())
        self.assertEqual(out["status"], "COLLECTING")


if __name__ == "__main__":
    unittest.main()
