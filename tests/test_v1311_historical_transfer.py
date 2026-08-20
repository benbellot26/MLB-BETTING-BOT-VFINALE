from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import probability_contract_v13 as contract
from v11 import v13_distribution_prior as distribution
from v11 import v13_exact_transfer_evidence as exact_evidence
from v11 import v13_run_mean_prior as prior
from v11 import v13_run_mean_runtime as runtime


def _history(seasons=range(2021, 2027), games_per_season=30):
    rows = []
    for season in seasons:
        for i in range(games_per_season):
            rows.append({
                "game_pk": f"h-{season}-{i}",
                "game_date": f"{season}-06-{(i % 28) + 1:02d}T18:00:00Z",
                "season": season,
                "home_mu": 4.80,
                "away_mu": 3.80,
                "home_score": 5,
                "away_score": 4,
            })
    return rows


def _exact(n=12):
    return [{
        "game_pk": f"x-{i}",
        "game_date": f"2026-08-{(i % 18) + 1:02d}T18:00:00Z",
        "season": 2026,
        "phase": "FINAL",
        "home_mu": 4.80,
        "away_mu": 3.80,
        "dispersion": prior.DISPERSION,
        "home_score": 5,
        "away_score": 4,
    } for i in range(n)]


def _distribution_history(seasons=range(2021, 2027), games_per_season=520):
    home_scores = (0, 1, 2, 3, 5, 7, 8, 10)
    away_scores = (0, 1, 2, 3, 4, 6, 8, 9)
    rows = []
    for season in seasons:
        for i in range(games_per_season):
            rows.append({
                "game_pk": f"d-{season}-{i}",
                "game_date": f"{season}-07-{(i % 28) + 1:02d}T18:00:00Z",
                "season": season,
                "home_mu": 4.5,
                "away_mu": 4.1,
                "home_score": home_scores[i % len(home_scores)],
                "away_score": away_scores[i % len(away_scores)],
            })
    return rows


def _distribution_exact(n=40):
    h = (0, 1, 2, 3, 5, 7, 8, 10)
    a = (0, 1, 2, 3, 4, 6, 8, 9)
    return [{
        "game_pk": f"dx-{i}",
        "game_date": f"2026-08-{(i % 18) + 1:02d}T18:00:00Z",
        "season": 2026,
        "phase": "FINAL",
        "validation_baseline_home_runs": 4.5,
        "validation_baseline_away_runs": 4.1,
        "validation_baseline_dispersion": distribution.BASELINE_DISPERSION,
        "home_score": h[i % len(h)],
        "away_score": a[i % len(a)],
    } for i in range(n)]


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _promotion_provenance(as_of: str):
    return {
        "team_stats": {
            "source": "test-durable-snapshot",
            "as_of": as_of,
            "observed_at": as_of,
            "timestamp_basis": "durable_snapshot_capture",
            "source_timestamp_attested": True,
            "point_in_time": True,
            "snapshot": True,
            "cutoff_capable": False,
            "season_aggregate": False,
            "postgame_identity": False,
        }
    }


def _native_feature(game_pk="native-1", phase="FINAL", generation=None, as_of="2026-08-19T18:00:00Z", source=None):
    generation = generation or contract.MODEL_GENERATION_FINGERPRINT
    return {
        "schema": "v13-pit-feature-store-v1",
        "game_pk": game_pk,
        "game_date": "2026-08-19T19:00:00Z",
        "as_of": as_of,
        "phase": phase,
        "model_generation": generation,
        "point_in_time": True,
        "point_in_time_validation_reasons": [],
        "feature_provenance": _promotion_provenance(as_of),
        "features": {
            "historical_bootstrap": {
                "run_prior": {
                    "v13_validation_baseline_home_mu": 4.7,
                    "v13_validation_baseline_away_mu": 4.2,
                    "v13_validation_baseline_dispersion": 7.5,
                    "v13_validation_baseline_environment_sigma": 0.08,
                    "v13_validation_baseline_source": source or exact_evidence.PRE_CANDIDATE_BASELINE_SOURCE,
                    "v13_validation_model_generation": generation,
                }
            }
        },
    }


def _label(game_pk: str, home_score=6, away_score=3):
    return {
        "schema": exact_evidence.LABEL_SCHEMA,
        "game_pk": game_pk,
        "game_date": "2026-08-19T19:00:00Z",
        "home_score": home_score,
        "away_score": away_score,
        "settled_at": "2026-08-20T05:00:00Z",
        "label_source": exact_evidence.LABEL_SOURCE,
    }


class V1311HistoricalTransferTests(unittest.TestCase):
    def test_native_final_feature_plus_postgame_label_is_exact_transfer_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay = root / "replay.jsonl"
            feature = root / "features.jsonl"
            label = root / "labels.jsonl"
            _write_jsonl(replay, [])
            _write_jsonl(feature, [_native_feature()])
            _write_jsonl(label, [_label("native-1")])
            rows = exact_evidence.load_exact_final_rows(replay, feature, label)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["exact_evidence_source"], "NATIVE_CURRENT_GENERATION_FINAL")
        self.assertEqual(row["validation_baseline_model_generation"], contract.MODEL_GENERATION_FINGERPRINT)
        self.assertEqual((row["home_score"], row["away_score"]), (6, 3))
        self.assertEqual(row["validation_baseline_dispersion"], 7.5)

    def test_native_transfer_rejects_weak_pit_or_unattested_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay = root / "replay.jsonl"
            feature = root / "features.jsonl"
            label = root / "labels.jsonl"
            weak = _native_feature("weak")
            weak["feature_provenance"]["team_stats"]["source_timestamp_attested"] = False
            _write_jsonl(replay, [])
            _write_jsonl(feature, [weak, _native_feature("bad-label")])
            bad_label = _label("bad-label")
            bad_label["schema"] = "untrusted-label"
            _write_jsonl(label, [_label("weak"), bad_label])
            rows = exact_evidence.load_exact_final_rows(replay, feature, label)
        self.assertEqual(rows, [])

    def test_native_transfer_rejects_nonfinal_wrong_generation_and_poststart_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay = root / "replay.jsonl"
            feature = root / "features.jsonl"
            label = root / "labels.jsonl"
            _write_jsonl(replay, [])
            _write_jsonl(feature, [
                _native_feature("late", phase="LATE"),
                _native_feature("old", generation="old-generation"),
                _native_feature("poststart", as_of="2026-08-19T19:00:01Z"),
                _native_feature("wrong-source", source="not-pre-candidate"),
            ])
            _write_jsonl(label, [_label(gid) for gid in ("late", "old", "poststart", "wrong-source")])
            rows = exact_evidence.load_exact_final_rows(replay, feature, label)
        self.assertEqual(rows, [])

    def test_native_exact_evidence_deduplicates_to_latest_final_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay = root / "replay.jsonl"
            feature = root / "features.jsonl"
            label = root / "labels.jsonl"
            first = _native_feature(as_of="2026-08-19T17:30:00Z")
            second = _native_feature(as_of="2026-08-19T18:30:00Z")
            second["features"]["historical_bootstrap"]["run_prior"]["v13_validation_baseline_home_mu"] = 5.1
            _write_jsonl(replay, [])
            _write_jsonl(feature, [first, second])
            _write_jsonl(label, [_label("native-1")])
            rows = exact_evidence.load_exact_final_rows(replay, feature, label)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["validation_baseline_home_runs"], 5.1)

    def test_nested_walk_forward_uses_only_prior_seasons(self):
        with patch.object(prior, "MIN_WF_TEST_GAMES", 10), patch.object(prior, "MIN_WF_FOLDS", 3):
            report = prior._walk_forward(_history())
        self.assertTrue(report["stable"])
        self.assertGreaterEqual(report["folds_total"], 3)
        for fold in report["folds"]:
            self.assertTrue(all(s < fold["validation_season"] for s in fold["train_seasons"]))
            self.assertLess(fold["validation_season"], fold["test_season"])
            self.assertTrue(fold["passes"])

    def test_exact_transfer_games_are_excluded_from_historical_fit(self):
        hist = _history()
        exact = _exact()
        hist.append({
            "game_pk": exact[0]["game_pk"],
            "game_date": "2026-08-01T18:00:00Z",
            "season": 2026,
            "home_mu": 1.0,
            "away_mu": 1.0,
            "home_score": 20,
            "away_score": 20,
        })
        with patch.object(prior, "MIN_WF_TEST_GAMES", 10), patch.object(prior, "MIN_WF_FOLDS", 3), \
             patch.object(prior, "MIN_EXACT_FINAL", 10), patch.object(prior, "EXACT_BOOTSTRAP_DRAWS", 200):
            report = prior.build(historical_rows=hist, exact_rows=exact)
        self.assertIn(exact[0]["game_pk"], report["excluded_exact_transfer_game_ids"])
        self.assertEqual(report["historical_games"], len(hist) - 1)
        self.assertTrue(report["safety"]["exact_transfer_games_excluded_from_historical_fit"])

    def test_reconstructed_history_cannot_bypass_exact_v13_gate(self):
        artifact = {
            "schema": runtime.SCHEMA,
            "active": True,
            "historical_candidate_active": True,
            "walk_forward": {"stable": True, "folds_total": 4, "folds_passed": 4},
            "model_generation": contract.MODEL_GENERATION_FINGERPRINT,
            "phase_scope": "FINAL",
            "exact_final_games": 59,
            "exact_transfer_required_games": 60,
            "exact_transfer_status": "COLLECTING_FINAL_ONLY",
            "exact_transfer_bootstrap": {"passes": True},
            "safety": {"exact_transfer_games_excluded_from_historical_fit": True},
            "model": {"home_bias": 1.0, "away_bias": -1.0, "slope_delta": 0.0, "max_adjustment": 1.0},
        }
        h, a, meta = runtime.apply_pair(4.4, 4.3, "FINAL", artifact)
        self.assertEqual((h, a), (4.4, 4.3))
        self.assertFalse(meta["active"])
        self.assertIn("59_OF_60", meta["reason"])

    def test_active_transfer_is_capped_to_fifteen_hundredths_run(self):
        artifact = {
            "schema": runtime.SCHEMA,
            "active": True,
            "historical_candidate_active": True,
            "walk_forward": {"stable": True, "folds_total": 4, "folds_passed": 4},
            "model_generation": contract.MODEL_GENERATION_FINGERPRINT,
            "phase_scope": "FINAL",
            "exact_final_games": 60,
            "exact_transfer_required_games": 60,
            "exact_transfer_status": "PASS_FINAL_ONLY",
            "exact_transfer_bootstrap": {"passes": True, "nll_gain_positive_probability": 0.95},
            "safety": {"exact_transfer_games_excluded_from_historical_fit": True},
            "model": {"home_bias": 2.0, "away_bias": -2.0, "slope_delta": 0.0, "max_adjustment": 1.0},
        }
        h, a, meta = runtime.apply_pair(4.4, 4.3, "FINAL", artifact)
        self.assertTrue(meta["active"])
        self.assertAlmostEqual(h, 4.55, places=9)
        self.assertAlmostEqual(a, 4.15, places=9)
        self.assertLessEqual(abs(meta["home_delta"]), 0.15 + 1e-12)
        self.assertLessEqual(abs(meta["away_delta"]), 0.15 + 1e-12)

    def test_transfer_is_final_phase_only(self):
        artifact = {"phase_scope": "FINAL"}
        h, a, meta = runtime.apply_pair(4.4, 4.3, "LATE", artifact)
        self.assertEqual((h, a), (4.4, 4.3))
        self.assertFalse(meta["active"])
        self.assertEqual(meta["reason"], "phase_out_of_scope")

    def test_wrong_model_generation_fails_neutral(self):
        artifact = {
            "active": True,
            "historical_candidate_active": True,
            "walk_forward": {"stable": True},
            "model_generation": "old-generation",
            "phase_scope": "FINAL",
            "exact_final_games": 100,
            "exact_transfer_required_games": 60,
            "exact_transfer_status": "PASS_FINAL_ONLY",
            "exact_transfer_bootstrap": {"passes": True},
            "safety": {"exact_transfer_games_excluded_from_historical_fit": True},
        }
        h, a, meta = runtime.apply_pair(4.4, 4.3, "FINAL", artifact)
        self.assertEqual((h, a), (4.4, 4.3))
        self.assertFalse(meta["active"])
        self.assertEqual(meta["reason"], "FINAL_TRANSFER_MODEL_GENERATION_MISMATCH")

    def test_distribution_walk_forward_never_trains_on_future_season(self):
        with patch.object(distribution, "MIN_WALK_FORWARD_FOLDS", 3), \
             patch.object(distribution, "MIN_WALK_FORWARD_NLL_GAIN", 0.0):
            report = distribution._walk_forward(_distribution_history())
        self.assertTrue(report["stable"])
        self.assertGreaterEqual(report["folds_total"], 3)
        for fold in report["folds"]:
            self.assertTrue(all(s < fold["test_season"] for s in fold["train_seasons"]))
            self.assertTrue(fold["passes"])
            self.assertLess(fold["candidate_nb_nll"], fold["baseline_nb_nll"])

    def test_distribution_history_is_candidate_only_until_exact_transfer(self):
        hist = _distribution_history()
        with patch.object(distribution, "MIN_HISTORICAL_GAMES", 100), \
             patch.object(distribution, "MIN_WALK_FORWARD_FOLDS", 3), \
             patch.object(distribution, "MIN_WALK_FORWARD_NLL_GAIN", 0.0), \
             patch.object(distribution, "MIN_EXACT_FINAL", 20), \
             patch.object(distribution, "EXACT_BOOTSTRAP_DRAWS", 200):
            collecting = distribution.build(historical_rows=hist, exact_rows=[])
            promoted = distribution.build(historical_rows=hist, exact_rows=_distribution_exact(40))
        self.assertTrue(collecting["historical_candidate_active"])
        self.assertFalse(collecting["active"])
        self.assertEqual(collecting["exact_transfer_status"], "COLLECTING_FINAL_ONLY")
        self.assertTrue(promoted["historical_candidate_active"])
        self.assertTrue(promoted["active"])
        self.assertEqual(promoted["exact_transfer_status"], "PASS_FINAL_ONLY")
        self.assertTrue(promoted["exact_transfer_bootstrap"]["passes"])
        self.assertTrue(promoted["safety"]["exact_transfer_games_excluded_from_historical_fit"])


if __name__ == "__main__":
    unittest.main()
