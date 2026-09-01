from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from v14.acquisition import write_odds_quota_state
from v14.api_budget import (
    manual_allowance,
    provider_guard,
    record_manual_snapshot,
    record_provider_quota,
)
from v14.odds_quota_probe import probe


ENV={
    "V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT":"3",
    "V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH":"450",
    "V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS":"50",
    "V14_ODDS_PROVIDER_QUOTA_MAX_AGE_MINUTES":"360",
}


class FakeResponse:
    def __init__(self,headers:dict[str,str],body:bytes=b'[{"key":"baseball_mlb"}]')->None:
        self.headers=headers;self._body=body
    def __enter__(self):return self
    def __exit__(self,*_args):return False
    def read(self)->bytes:return self._body


class V14OddsProviderQuotaTests(unittest.TestCase):
    def _state(self,path:Path,*,remaining:int,used:int=0,last:int=3,captured_at:str="2026-09-01T10:00:00+00:00")->None:
        path.write_text(json.dumps({
            "schema":"pulsar-v14-odds-provider-quota-v1",
            "captured_at":captured_at,
            "provider":"THE_ODDS_API",
            "credits_remaining_until_provider_reset":remaining,
            "credits_used_since_provider_reset":used,
            "last_request_credit_cost":last,
            "credentials_persisted":False,
        }),encoding="utf-8")

    def test_response_headers_are_persisted_without_credentials(self)->None:
        with TemporaryDirectory() as tmp:
            state=Path(tmp)/"quota.json"
            payload=write_odds_quota_state({"X-Requests-Remaining":"497","x-requests-used":"3","X-REQUESTS-LAST":"3","apiKey":"secret"},path=state,captured_at="2026-09-01T10:00:00+00:00")
            self.assertEqual(payload["credits_remaining_until_provider_reset"],497)
            self.assertEqual(payload["credits_used_since_provider_reset"],3)
            self.assertEqual(payload["last_request_credit_cost"],3)
            self.assertFalse(payload["credentials_persisted"])
            text=state.read_text(encoding="utf-8")
            self.assertNotIn("secret",text);self.assertNotIn("apiKey",text)

    def test_zero_credit_sports_probe_refreshes_headers_without_persisting_key(self)->None:
        with TemporaryDirectory() as tmp, patch('v14.odds_quota_probe.urlopen',return_value=FakeResponse({"x-requests-remaining":"500","x-requests-used":"0","x-requests-last":"0"})):
            state=Path(tmp)/"quota.json";out=probe(api_key="top-secret",state_path=state)
            self.assertEqual(out["provider_credit_cost"],0);self.assertEqual(out["sports_returned"],1)
            self.assertEqual(out["quota"]["credits_remaining_until_provider_reset"],500)
            self.assertFalse(out["credentials_persisted"])
            self.assertNotIn("top-secret",state.read_text(encoding="utf-8"))

    def test_exact_50_credit_post_request_reserve_is_allowed_when_attestation_is_fresh(self)->None:
        now=datetime(2026,9,1,10,5,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp, patch.dict(os.environ,ENV,clear=False):
            root=Path(tmp);ledger=root/"usage.jsonl";state=root/"quota.json"
            self._state(state,remaining=53,used=447,last=3)
            record_provider_quota(ledger,state_path=state,now=now)
            guard=provider_guard(ledger,now=now)
            self.assertTrue(guard["fresh"]);self.assertTrue(guard["allowed"])
            self.assertEqual(guard["credits_after_next_snapshot"],50)
            record_manual_snapshot(ledger,now=now,slate_date="2026-09-01")

    def test_fresh_provider_guard_blocks_below_reserve(self)->None:
        now=datetime(2026,9,1,10,5,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp, patch.dict(os.environ,ENV,clear=False):
            root=Path(tmp);ledger=root/"usage.jsonl";state=root/"quota.json"
            self._state(state,remaining=52,used=448,last=3)
            record_provider_quota(ledger,state_path=state,now=now)
            guard=provider_guard(ledger,now=now)
            self.assertTrue(guard["fresh"]);self.assertFalse(guard["allowed"])
            self.assertEqual(guard["credits_after_next_snapshot"],49)
            with self.assertRaisesRegex(RuntimeError,"provider-reported emergency reserve reached"):
                record_manual_snapshot(ledger,now=now,slate_date="2026-09-01")

    def test_prior_month_attestation_becomes_refresh_required_not_permanent_deadlock(self)->None:
        october=datetime(2026,10,1,0,5,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp, patch.dict(os.environ,ENV,clear=False):
            root=Path(tmp);ledger=root/"usage.jsonl";state=root/"quota.json"
            self._state(state,remaining=52,used=448,last=3,captured_at="2026-09-30T23:59:00+00:00")
            record_provider_quota(ledger,state_path=state,now=datetime(2026,9,30,23,59,tzinfo=timezone.utc))
            guard=provider_guard(ledger,now=october)
            self.assertEqual(guard["status"],"STALE_REFRESH_REQUIRED")
            self.assertTrue(guard["allowed"]);self.assertTrue(guard["requires_zero_credit_refresh_before_paid_reservation"])
            local=manual_allowance(ledger,now=october,slate_date="2026-10-01")
            self.assertEqual(local["all_paid_month"]["provider_credits_used"],0)

    def test_last_provider_cost_is_used_conservatively_when_cost_drifts(self)->None:
        now=datetime(2026,9,1,10,5,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp, patch.dict(os.environ,ENV,clear=False):
            root=Path(tmp);ledger=root/"usage.jsonl";state=root/"quota.json"
            self._state(state,remaining=55,used=445,last=6)
            record_provider_quota(ledger,state_path=state,now=now)
            guard=provider_guard(ledger,now=now)
            self.assertEqual(guard["configured_next_credit_cost"],3);self.assertEqual(guard["conservative_next_credit_cost"],6)
            self.assertEqual(guard["credits_after_next_snapshot"],49);self.assertFalse(guard["allowed"])

    def test_duplicate_provider_attestation_does_not_grow_ledger(self)->None:
        now=datetime(2026,9,1,10,5,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=root/"usage.jsonl";state=root/"quota.json"
            self._state(state,remaining=497,used=3,last=3)
            first=record_provider_quota(ledger,state_path=state,now=now);second=record_provider_quota(ledger,state_path=state,now=now)
            self.assertTrue(first["recorded"]);self.assertFalse(second["recorded"])
            self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()),1)


if __name__=="__main__":unittest.main()
