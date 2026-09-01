from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from v14.api_budget import record_prediction_snapshot
from v14.scheduled_prediction_gate import build as prediction_gate, due_games


MULTI_ENV = {
    "V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_SLATE": "2",
    "V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_SLATE": "1",
    "V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT": "3",
    "V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH": "420",
    "V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH": "450",
    "V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS": "50",
}


def game(game_pk: str, at: datetime) -> dict:
    return {
        "gamePk": int(game_pk),
        "gameDate": at.isoformat(),
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "teams": {
            "home": {"team": {"name": f"Home {game_pk}"}},
            "away": {"team": {"name": f"Away {game_pk}"}},
        },
    }


class V14MultiSnapshotCoverageTests(unittest.TestCase):
    def test_two_snapshot_budget_keeps_early_due_game_and_later_large_cluster(self) -> None:
        now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
        games = [
            game("1", now + timedelta(minutes=30)),
            game("2", now + timedelta(hours=2)),
            game("3", now + timedelta(hours=2)),
            game("4", now + timedelta(hours=2)),
        ]
        with TemporaryDirectory() as tmp, patch.dict(os.environ, MULTI_ENV, clear=False):
            root = Path(tmp)
            out = prediction_gate(
                predictions_path=root / "predictions.jsonl",
                api_usage_path=root / "usage.jsonl",
                target_date="2026-09-01",
                now=now,
                games_loader=lambda _day: games,
            )
        self.assertTrue(out["run_required"])
        self.assertEqual(out["reason"], "FINAL_SNAPSHOT_DUE")
        self.assertEqual(out["effective_snapshot_capacity_remaining"], 2)
        plan = out["optimal_slate_plan"]
        self.assertEqual(plan["games"], 4)
        self.assertEqual(plan["snapshots_planned"], 2)
        self.assertEqual(plan["snapshots"][0]["target_at"], now.isoformat())
        self.assertEqual(plan["snapshots"][0]["game_ids"], ["1"])
        self.assertEqual(set(plan["snapshots"][1]["game_ids"]), {"2", "3", "4"})
        self.assertEqual(plan["snapshots"][1]["target_at"], (now + timedelta(hours=1, minutes=30)).isoformat())

    def test_remaining_slate_budget_changes_plan_after_one_snapshot_is_spent(self) -> None:
        now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
        games = [
            game("1", now + timedelta(minutes=30)),
            game("2", now + timedelta(hours=2)),
            game("3", now + timedelta(hours=2)),
            game("4", now + timedelta(hours=2)),
        ]
        with TemporaryDirectory() as tmp, patch.dict(os.environ, MULTI_ENV, clear=False):
            root = Path(tmp)
            usage = root / "usage.jsonl"
            record_prediction_snapshot(
                usage,
                now=now - timedelta(hours=2),
                slate_date="2026-09-01",
                due_games=["prior"],
            )
            out = prediction_gate(
                predictions_path=root / "predictions.jsonl",
                api_usage_path=usage,
                target_date="2026-09-01",
                now=now,
                games_loader=lambda _day: games,
            )
        self.assertFalse(out["run_required"])
        self.assertEqual(out["reason"], "WAITING_FOR_BEST_SLATE_CLUSTER")
        self.assertEqual(out["effective_snapshot_capacity_remaining"], 1)
        plan = out["optimal_slate_plan"]
        self.assertEqual(plan["games"], 3)
        self.assertEqual(plan["snapshots_planned"], 1)
        self.assertEqual(set(plan["game_ids"]), {"2", "3", "4"})

    def test_multi_snapshot_mode_does_not_relax_certification_window(self) -> None:
        now = datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
        games = [
            game("9", now + timedelta(minutes=9, seconds=59)),
            game("10", now + timedelta(minutes=10)),
            game("60", now + timedelta(minutes=60)),
            game("61", now + timedelta(minutes=60, seconds=1)),
        ]
        due = due_games(games, [], now=now)
        self.assertEqual({row["game_pk"] for row in due}, {"10", "60"})

    def test_workflows_opt_in_to_coverage_budget_but_preserve_hard_cap_and_reserve(self) -> None:
        production = Path(".github/workflows/mlb-bot.yml").read_text(encoding="utf-8")
        close = Path(".github/workflows/v14-close-capture.yml").read_text(encoding="utf-8")
        self.assertIn("V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_SLATE: '4'", production)
        self.assertIn("V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH: '420'", production)
        self.assertIn("V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_SLATE: '1'", close)
        self.assertIn("V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH: '420'", close)
        for text in (production, close):
            self.assertIn("V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH: '450'", text)
            self.assertIn("V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS: '50'", text)


if __name__ == "__main__":
    unittest.main()
