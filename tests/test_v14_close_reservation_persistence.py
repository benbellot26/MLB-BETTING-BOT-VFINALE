from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from v14.cost_aware_close_capture import run as close_run


WORKFLOW=Path('.github/workflows/v14-close-capture.yml')


class V14CloseReservationPersistenceTests(unittest.TestCase):
    def _market_row(self,now:datetime,*,target_date:str='2026-09-01')->dict:
        return {
            'schema':'pulsar-v14-market-close-v1',
            'game_pk':'1',
            'target_date':target_date,
            'game_date':(now+timedelta(minutes=10)).isoformat(),
            'odds_event_id':'event-1',
            'odds_event_time_verified':True,
            'close_history':[],
            'best_close':None,
        }

    def test_reservation_hook_runs_before_events_loader_and_uses_target_slate(self)->None:
        now=datetime(2026,9,2,0,5,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);market=root/'market.jsonl';paper=root/'paper.jsonl';bet=root/'bet.jsonl';usage=root/'usage.jsonl'
            market.write_text(json.dumps(self._market_row(now,target_date='2026-09-01'))+'\n',encoding='utf-8')
            order=[];seen={}
            def hook(row):
                order.append('persist')
                seen.update(row)
            def loader():
                order.append('network')
                return []
            out=close_run(market,paper,bet,api_usage_path=usage,events_loader=loader,now=now,reservation_hook=hook)
            self.assertEqual(order[:2],['persist','network'])
            self.assertEqual(seen['slate_date'],'2026-09-01')
            self.assertEqual(out['slate_date'],'2026-09-01')
            self.assertTrue(out['reservation_persisted_before_network'])

    def test_persistence_failure_prevents_paid_loader(self)->None:
        now=datetime(2026,9,1,18,0,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);market=root/'market.jsonl';paper=root/'paper.jsonl';bet=root/'bet.jsonl';usage=root/'usage.jsonl'
            market.write_text(json.dumps(self._market_row(now))+'\n',encoding='utf-8')
            called={'network':0}
            def hook(_row):raise RuntimeError('state push failed')
            def loader():
                called['network']+=1
                return []
            with self.assertRaisesRegex(RuntimeError,'state push failed'):
                close_run(market,paper,bet,api_usage_path=usage,events_loader=loader,now=now,reservation_hook=hook)
            self.assertEqual(called['network'],0)
            self.assertTrue(usage.exists())

    def test_workflow_enforces_durable_reservation_and_provider_reconciliation(self)->None:
        text=WORKFLOW.read_text(encoding='utf-8')
        capture=text.index('- name: Capture closes with durable pre-network reservation when due')
        reconcile=text.index('- name: Reconcile provider quota and API ledger')
        persist=text.index('- name: Persist only substantive close evidence changes on runtime-data')
        self.assertLess(capture,reconcile);self.assertLess(reconcile,persist)
        block=text[capture:reconcile]
        self.assertIn('--persist-reservation-before-network',block)
        self.assertIn('V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS',block)
        reconcile_block=text[reconcile:persist]
        self.assertIn('if: always()',reconcile_block)
        self.assertIn('record-provider-state',reconcile_block)
        self.assertIn('v14.state_branch persist',reconcile_block)
        self.assertIn('provider-guard',reconcile_block)


if __name__=='__main__':unittest.main()
