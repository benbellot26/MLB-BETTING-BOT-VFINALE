from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import probability_contract_v13 as contract
from v11 import v13_run_mean_prior as prior
from v11 import v13_run_mean_runtime as runtime


def _history(seasons=range(2021, 2027), games_per_season=30):
    rows = []
    for season in seasons:
        for i in range(games_per_season):
            # Stable, deliberately small historical correction: the baseline is
            # low by 0.10 home and 0.05 away. No market field is present.
            rows.append({
                "game_pk": f"h-{season}-{i}",
                "game_date": f"{season}-06-{(i % 28) + 1:02d}T18:00:00Z",
                "season": season,
                "home_mu": 4.40,
                "away_mu": 4.30,
                "home_score": 4.50,
                "away_score": 4.35,
            })
    return rows


def _exact(n=12):
    return [{
        "game_pk": f"x-{i}",
        "game_date": f"2026-08-{(i % 18) + 1:02d}T18:00:00Z",
        "season": 2026,
        "phase": "FINAL",
        "home_mu": 4.40,
        "away_mu": 4.30,
        "dispersion": prior.DISPERSION,
        "home_score": 4.50,
        "away_score": 4.35,
    } for i in range(n)]


class V1311HistoricalTransferTests(unittest.TestCase):
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
            "home_score": 20.0,
            "away_score": 20.0,
        })
        with patch.object(prior, "MIN_WF_TEST_GAMES", 10), patch.object(prior, "MIN_WF_FOLDS", 3), \
             patch.object(prior, "MIN_EXACT_FINAL", 10), patch.object(prior, "EXACT_BOOTSTRAP_DRAWS", 200):
            report = prior.build(historical_rows=hist, exact_rows=exact)
        self.assertNotIn(exact[0]["game_pk"], {r for r in report["excluded_exact_transfer_game_ids"] if not r.startswith("x-")})
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


if __name__ == "__main__":
    unittest.main()
