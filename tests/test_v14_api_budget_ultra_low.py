from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from v14.api_budget import (
    all_paid_monthly_usage,
    automated_monthly_usage,
    build_report,
    record_close_snapshot,
    record_manual_snapshot,
    record_prediction_snapshot,
)


ENV={
    "V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_SLATE":"1",
    "V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_SLATE":"1",
    "V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT":"3",
    "V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH":"180",
    "V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH":"450",
}


class V14UltraLowApiBudgetTests(unittest.TestCase):
    def test_only_one_prediction_and_one_close_are_allowed_per_mlb_slate(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ,ENV,clear=False):
            ledger=Path(tmp)/"usage.jsonl";now=datetime(2026,9,1,23,50,tzinfo=timezone.utc);slate="2026-09-01"
            p=record_prediction_snapshot(ledger,now=now,slate_date=slate,due_games=["1","2"])
            c=record_close_snapshot(ledger,now=now,slate_date=slate,due_rows=2)
            self.assertEqual(p["provider_credit_cost"],3);self.assertEqual(c["provider_credit_cost"],3)
            # UTC midnight must not replenish the same MLB slate.
            after_midnight=now+timedelta(minutes=20)
            with self.assertRaisesRegex(RuntimeError,"slate budget exhausted"):
                record_prediction_snapshot(ledger,now=after_midnight,slate_date=slate,due_games=["3"])
            with self.assertRaisesRegex(RuntimeError,"slate budget exhausted"):
                record_close_snapshot(ledger,now=after_midnight,slate_date=slate,due_rows=1)
            month=automated_monthly_usage(ledger,now=now)
            self.assertEqual(month["snapshots"],2);self.assertEqual(month["provider_credits_used"],6)

    def test_new_mlb_slate_replenishes_slate_limit(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ,ENV,clear=False):
            ledger=Path(tmp)/"usage.jsonl";now=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
            record_prediction_snapshot(ledger,now=now,slate_date="2026-09-01",due_games=["1"])
            second=record_prediction_snapshot(ledger,now=now+timedelta(hours=1),slate_date="2026-09-02",due_games=["2"])
            self.assertEqual(second["slate_date"],"2026-09-02")

    def test_monthly_combined_automatic_credit_cap_fails_closed(self) -> None:
        env={**ENV,"V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH":"6"}
        with TemporaryDirectory() as tmp, patch.dict(os.environ,env,clear=False):
            ledger=Path(tmp)/"usage.jsonl";day1=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
            record_prediction_snapshot(ledger,now=day1,slate_date="2026-09-01",due_games=["1"])
            record_close_snapshot(ledger,now=day1,slate_date="2026-09-01",due_rows=1)
            with self.assertRaisesRegex(RuntimeError,"automated monthly provider-credit budget exhausted"):
                record_prediction_snapshot(ledger,now=day1+timedelta(days=1),slate_date="2026-09-02",due_games=["2"])

    def test_manual_runs_are_counted_in_global_hard_cap(self) -> None:
        env={**ENV,"V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH":"9"}
        with TemporaryDirectory() as tmp, patch.dict(os.environ,env,clear=False):
            ledger=Path(tmp)/"usage.jsonl";now=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
            record_prediction_snapshot(ledger,now=now,slate_date="2026-09-01",due_games=["1"])
            record_manual_snapshot(ledger,now=now+timedelta(minutes=1),slate_date="2026-09-01")
            record_manual_snapshot(ledger,now=now+timedelta(minutes=2),slate_date="2026-09-01")
            total=all_paid_monthly_usage(ledger,now=now)
            self.assertEqual(total["provider_credits_used"],9);self.assertFalse(total["allowed"])
            with self.assertRaisesRegex(RuntimeError,"all-paid monthly hard cap exhausted"):
                record_manual_snapshot(ledger,now=now+timedelta(minutes=3),slate_date="2026-09-01")

    def test_default_report_preserves_hard_50_credit_emergency_reserve(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ,ENV,clear=False):
            report=build_report(Path(tmp)/"usage.jsonl",now=datetime(2026,9,1,tzinfo=timezone.utc),slate_date="2026-09-01")
            policy=report["policy"]
            self.assertEqual(policy["target_plan_provider_credits_per_month"],500)
            self.assertEqual(policy["default_max_automated_provider_credits_per_utc_month"],180)
            self.assertEqual(policy["default_max_all_provider_credits_per_utc_month"],450)
            self.assertEqual(policy["hard_reserved_emergency_credits_at_default_policy"],50)
            self.assertTrue(policy["manual_prediction_runs_budgeted"])
            self.assertTrue(policy["mlb_slate_keyed_limits"])


if __name__=="__main__":unittest.main()
