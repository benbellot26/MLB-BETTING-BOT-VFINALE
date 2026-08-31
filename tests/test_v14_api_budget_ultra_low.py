from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from v14.api_budget import (
    automated_monthly_usage,
    build_report,
    record_close_snapshot,
    record_prediction_snapshot,
)


class V14UltraLowApiBudgetTests(unittest.TestCase):
    def test_only_one_prediction_and_one_close_are_allowed_per_day(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY": "1",
            "V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY": "1",
            "V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT": "3",
            "V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH": "180",
        }, clear=False):
            ledger=Path(tmp)/"usage.jsonl";now=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
            p=record_prediction_snapshot(ledger,now=now,due_games=["1","2"])
            c=record_close_snapshot(ledger,now=now,due_rows=2)
            self.assertEqual(p["provider_credit_cost"],3)
            self.assertEqual(c["provider_credit_cost"],3)
            with self.assertRaisesRegex(RuntimeError,"daily budget exhausted"):
                record_prediction_snapshot(ledger,now=now+timedelta(hours=1),due_games=["3"])
            with self.assertRaisesRegex(RuntimeError,"daily budget exhausted"):
                record_close_snapshot(ledger,now=now+timedelta(hours=1),due_rows=1)
            month=automated_monthly_usage(ledger,now=now)
            self.assertEqual(month["snapshots"],2)
            self.assertEqual(month["provider_credits_used"],6)

    def test_monthly_combined_credit_cap_fails_closed_before_next_snapshot(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY": "1",
            "V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY": "1",
            "V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT": "3",
            "V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH": "6",
        }, clear=False):
            ledger=Path(tmp)/"usage.jsonl";day1=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
            record_prediction_snapshot(ledger,now=day1,due_games=["1"])
            record_close_snapshot(ledger,now=day1,due_rows=1)
            day2=day1+timedelta(days=1)
            with self.assertRaisesRegex(RuntimeError,"monthly provider-credit budget exhausted"):
                record_prediction_snapshot(ledger,now=day2,due_games=["2"])
            month=automated_monthly_usage(ledger,now=day2)
            self.assertEqual(month["provider_credits_used"],6)
            self.assertEqual(month["provider_credits_remaining"],0)
            self.assertFalse(month["allowed"])

    def test_default_report_reserves_most_of_500_credit_plan_for_manual_use(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY": "1",
            "V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY": "1",
            "V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT": "3",
            "V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH": "180",
        }, clear=False):
            report=build_report(Path(tmp)/"usage.jsonl",now=datetime(2026,9,1,tzinfo=timezone.utc))
            policy=report["policy"]
            self.assertEqual(policy["target_plan_provider_credits_per_month"],500)
            self.assertEqual(policy["default_max_automated_provider_credits_per_utc_month"],180)
            self.assertEqual(policy["reserved_nonautomatic_credits_at_default_policy"],320)
            self.assertEqual(policy["policy_mode"],"ULTRA_LOW_MINIMUM_VIABLE_PROSPECTIVE_COLLECTION")


if __name__=="__main__":unittest.main()
