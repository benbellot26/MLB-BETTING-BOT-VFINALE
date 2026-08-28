from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import unittest

from v14 import MODEL_GENERATION
from v14.historical_team_live_validation import build
from v14.historical_team_shadow import load as load_candidate


def artifact():
    out = load_candidate()
    if not out:
        raise AssertionError("repository team candidate must load")
    return copy.deepcopy(out)


def row(i: int, good: bool = True, *, candidate_id: str | None = None, candidate_fingerprint: str | None = None):
    evidence = artifact()
    analyzed = datetime(2026, 8, 29, tzinfo=timezone.utc) + timedelta(hours=i)
    champion = {"home_ml": 0.52, "away_ml": 0.48, "home_minus_1_5": 0.42, "away_plus_1_5": 0.58, "away_minus_1_5": 0.25, "home_plus_1_5": 0.75, "over": 0.52, "under": 0.48}
    candidate = {"home_ml": 0.62 if good else 0.42, "away_ml": 0.38 if good else 0.58, "home_minus_1_5": 0.52 if good else 0.32, "away_plus_1_5": 0.48 if good else 0.68, "away_minus_1_5": 0.18 if good else 0.35, "home_plus_1_5": 0.82 if good else 0.65, "over": 0.62 if good else 0.42, "under": 0.38 if good else 0.58}
    shadow = {
        "status": "READY_SHADOW",
        "candidate_id": candidate_id or evidence["candidate_id"],
        "candidate_fingerprint": candidate_fingerprint or evidence["candidate_fingerprint"],
        "evidence_run_id": evidence["source_run_id"],
        "candidate_run_projection": {"home_mu": 5.0 if good else 3.0, "away_mu": 3.0 if good else 5.0},
        "candidate_probabilities": candidate,
    }
    return {
        "model_generation": MODEL_GENERATION,
        "game_pk": str(i),
        "game_date": "2026-09-30T23:00:00+00:00",
        "analyzed_at": analyzed.isoformat(),
        "settled": True,
        "home_score": 5,
        "away_score": 3,
        "home_mu": 4.2,
        "away_mu": 4.0,
        "total_line": 7.5,
        "probabilities": champion,
        "training_features": {"research_challengers": {"historical_team_run_shadow": shadow}},
    }


class HistoricalTeamLiveValidationTests(unittest.TestCase):
    def test_good_postfreeze_shadow_reaches_review_only(self):
        out = build([row(i) for i in range(200)], artifact())
        self.assertEqual(out["status"], "PROMOTION_REVIEW")
        self.assertTrue(out["gates"]["passes"])
        self.assertFalse(out["auto_activation"])
        self.assertFalse(out["champion_impact"])
        self.assertEqual(out["candidate_fingerprint"], artifact()["candidate_fingerprint"])

    def test_too_few_games_stays_collecting(self):
        out = build([row(i) for i in range(50)], artifact())
        self.assertEqual(out["status"], "COLLECTING")
        self.assertFalse(out["gates"]["enough_games"])

    def test_worse_shadow_is_rejected_after_minimum(self):
        out = build([row(i, False) for i in range(200)], artifact())
        self.assertEqual(out["status"], "REJECTED_NATIVE_LIVE")
        self.assertFalse(out["gates"]["passes"])

    def test_wrong_candidate_identity_never_counts(self):
        rows = [row(1, candidate_id="other"), row(2, candidate_fingerprint="0" * 64)]
        out = build(rows, artifact())
        self.assertEqual(out["n"], 0)

    def test_tampered_injected_candidate_fails_closed(self):
        bad = artifact()
        bad["parameters"]["offense_weight"] = 0.99
        out = build([row(1)], bad)
        self.assertEqual(out["n"], 0)
        self.assertEqual(out["status"], "COLLECTING")


if __name__ == "__main__":
    unittest.main()
