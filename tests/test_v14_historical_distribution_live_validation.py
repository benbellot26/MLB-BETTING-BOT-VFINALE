from __future__ import annotations

import copy
import unittest

from v14 import MODEL_GENERATION
from v14.historical_distribution_live_validation import build
from v14.historical_distribution_shadow import load as load_candidate


def artifact():
    out = load_candidate()
    if not out:
        raise AssertionError("repository distribution candidate must load")
    return copy.deepcopy(out)


def row(
    gid: int,
    analyzed: str,
    *,
    persisted: bool = True,
    source_run_id: int | None = None,
    candidate_id: str | None = None,
    candidate_fingerprint: str | None = None,
):
    evidence = artifact()
    shadow = {
        "status": "READY_SHADOW",
        "candidate_id": candidate_id or evidence["candidate_id"],
        "candidate_fingerprint": candidate_fingerprint or evidence["candidate_fingerprint"],
        "evidence_run_id": evidence["source_run_id"] if source_run_id is None else source_run_id,
        "candidate_parameters": {"dispersion": 5.5, "environment_sigma": 0.16},
        "candidate_probabilities": {"home_ml": 0.56, "away_ml": 0.44, "home_minus_1_5": 0.41, "away_plus_1_5": 0.59, "away_minus_1_5": 0.24, "home_plus_1_5": 0.76, "over": 0.53, "under": 0.47},
    }
    training = {"research_challengers": {"historical_distribution_shadow": shadow}} if persisted else {}
    return {
        "game_pk": str(gid),
        "game_date": "2026-09-30T20:00:00+00:00",
        "analyzed_at": analyzed,
        "model_generation": MODEL_GENERATION,
        "settled": True,
        "home_score": 5,
        "away_score": 3,
        "home_mu": 4.5,
        "away_mu": 4.0,
        "total_line": 8.5,
        "probabilities": {"home_ml": 0.55, "away_ml": 0.45, "home_minus_1_5": 0.40, "away_plus_1_5": 0.60, "away_minus_1_5": 0.25, "home_plus_1_5": 0.75, "over": 0.52, "under": 0.48},
        "training_features": training,
    }


class HistoricalDistributionLiveValidationTests(unittest.TestCase):
    def test_pre_freeze_rows_never_count(self):
        out = build([row(1, "2026-08-28T10:00:00+00:00")], artifact=artifact())
        self.assertEqual(out["games"], 0)
        self.assertEqual(out["status"], "COLLECTING")
        self.assertFalse(out["auto_activation"])

    def test_post_freeze_persisted_rows_count_but_cannot_promote_below_floor(self):
        out = build([row(1, "2026-08-29T16:00:00+00:00"), row(2, "2026-08-29T16:01:00+00:00")], artifact=artifact())
        self.assertEqual(out["games"], 2)
        self.assertEqual(out["status"], "COLLECTING")
        self.assertEqual(out["minimum_prospective_games"], 200)
        self.assertIn("persisted READY_SHADOW", out["evidence_contract"])

    def test_old_champion_only_rows_cannot_be_recomputed_into_prospective_evidence(self):
        out = build([row(1, "2026-08-29T16:00:00+00:00", persisted=False)], artifact=artifact())
        self.assertEqual(out["games"], 0)
        self.assertEqual(out["status"], "COLLECTING")

    def test_wrong_source_or_candidate_identity_fails_closed(self):
        rows = [
            row(1, "2026-08-29T16:00:00+00:00", source_run_id=1),
            row(2, "2026-08-29T16:01:00+00:00", candidate_id="other"),
            row(3, "2026-08-29T16:02:00+00:00", candidate_fingerprint="0" * 64),
        ]
        out = build(rows, artifact=artifact())
        self.assertEqual(out["games"], 0)

    def test_later_duplicate_does_not_inflate_one_game(self):
        rows = [row(1, "2026-08-29T16:00:00+00:00"), row(1, "2026-08-29T17:00:00+00:00")]
        out = build(rows, artifact=artifact())
        self.assertEqual(out["games"], 1)

    def test_tampered_injected_candidate_fails_closed(self):
        bad = artifact()
        bad["candidate_parameters"]["dispersion"] = 99.0
        out = build([row(1, "2026-08-29T16:00:00+00:00")], artifact=bad)
        self.assertEqual(out["games"], 0)
        self.assertEqual(out["status"], "COLLECTING")


if __name__ == "__main__":
    unittest.main()
