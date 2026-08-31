from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from v14.cost_aware_close_capture import best_close_cluster, run as close_run
from v14.scheduled_prediction_gate import build as prediction_gate


def game(game_pk:str,at:datetime)->dict:
    return {
        "gamePk":int(game_pk),
        "gameDate":at.isoformat(),
        "status":{"abstractGameState":"Preview","detailedState":"Scheduled"},
        "teams":{"home":{"team":{"name":f"Home {game_pk}"}},"away":{"team":{"name":f"Away {game_pk}"}}},
    }


class V14UltraLowClusterPolicyTests(unittest.TestCase):
    def test_prediction_waits_for_larger_cluster_and_targets_30_minutes(self) -> None:
        now=datetime(2026,9,1,18,0,tzinfo=timezone.utc)
        games=[
            game("1",now+timedelta(minutes=30)),
            game("2",now+timedelta(hours=2)),
            game("3",now+timedelta(hours=2)),
            game("4",now+timedelta(hours=2)),
        ]
        with TemporaryDirectory() as tmp:
            root=Path(tmp);predictions=root/"predictions.jsonl";usage=root/"usage.jsonl"
            out=prediction_gate(predictions_path=predictions,api_usage_path=usage,target_date="2026-09-01",now=now,games_loader=lambda _day:games)
            self.assertFalse(out["run_required"])
            self.assertEqual(out["reason"],"WAITING_FOR_BEST_DAILY_CLUSTER")
            plan=out["best_daily_cluster"]
            self.assertEqual(plan["games"],3)
            self.assertEqual(set(plan["game_ids"]),{"2","3","4"})
            self.assertEqual(plan["target_at"],(now+timedelta(hours=1,minutes=30)).isoformat())
            self.assertAlmostEqual(plan["mean_target_error_minutes"],0.0)

    def test_prediction_runs_when_best_cluster_reaches_target(self) -> None:
        target=datetime(2026,9,1,19,30,tzinfo=timezone.utc)
        games=[game("2",target+timedelta(minutes=30)),game("3",target+timedelta(minutes=30)),game("4",target+timedelta(minutes=30))]
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            out=prediction_gate(predictions_path=root/"predictions.jsonl",api_usage_path=root/"usage.jsonl",target_date="2026-09-01",now=target,games_loader=lambda _day:games)
            self.assertTrue(out["run_required"])
            self.assertEqual(out["reason"],"FINAL_SNAPSHOT_DUE_AT_BEST_CLUSTER")
            self.assertEqual(set(out["due_game_ids"]),{"2","3","4"})

    def test_close_waits_for_larger_pending_cluster_without_network_call(self) -> None:
        now=datetime(2026,9,1,18,0,tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root=Path(tmp);market=root/"market.jsonl";paper=root/"paper.jsonl";bet=root/"bet.jsonl";usage=root/"usage.jsonl"
            rows=[]
            for game_pk,minutes in (("1",10),("2",60),("3",60),("4",60)):
                rows.append({"schema":"pulsar-v14-market-close-v1","game_pk":game_pk,"game_date":(now+timedelta(minutes=minutes)).isoformat(),"odds_event_id":f"event-{game_pk}","odds_event_time_verified":True,"close_history":[],"best_close":None})
            market.write_text("".join(json.dumps(row)+"\n" for row in rows),encoding="utf-8")
            plan=best_close_cluster(market,paper,bet,now=now)
            self.assertEqual(plan["games"],3)
            self.assertEqual(set(plan["game_keys"]),{"event:event-2","event:event-3","event:event-4"})
            self.assertEqual(plan["target_at"],(now+timedelta(minutes=45)).isoformat())
            called={"n":0}
            def loader():
                called["n"]+=1
                return []
            out=close_run(market,paper,bet,api_usage_path=usage,events_loader=loader,now=now)
            self.assertFalse(out["api_call_performed"])
            self.assertEqual(called["n"],0)
            self.assertIn("waiting for larger close cluster",out["reason"])


if __name__=="__main__":unittest.main()
