from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from v14.coverage_ledger import rows_from_candidate
from v14.cost_aware_close_capture import CERTIFIED_DUE_WINDOW_MINUTES, due_games, run as cost_aware_run
from v14.paired_inference import bootstrap_mean_ci
from v14.research_registry import register, verify
from v14.sharp_benchmark import pinnacle_probability
from v14.snapshot_policy import canonical_bucket, select_canonical


class AuditHardeningTests(unittest.TestCase):
    def test_bootstrap_is_deterministic(self) -> None:
        a=bootstrap_mean_ci([.1,.2,-.1,.3],reps=600,label="same")
        b=bootstrap_mean_ci([.1,.2,-.1,.3],reps=600,label="same")
        self.assertEqual(a,b)
        self.assertEqual(a["n"],4)

    def test_snapshot_policy_uses_observed_windows_only(self) -> None:
        game=datetime(2026,9,1,0,0,tzinfo=timezone.utc)
        def row(minutes:int,stamp:str)->dict:
            return {"game_pk":"1","game_date":game.isoformat(),"analyzed_at":(game-timedelta(minutes=minutes)).isoformat(),"stamp":stamp}
        early=row(550,"early");late=row(175,"late");final=row(28,"final");outside=row(90,"outside")
        self.assertEqual(canonical_bucket(early),"EARLY")
        self.assertIsNone(canonical_bucket(outside))
        selected=select_canonical([outside,final,early,late])
        self.assertEqual(selected["1"]["FINAL"]["stamp"],"final")
        self.assertEqual(set(selected["1"]),{"EARLY","LATE","FINAL"})

    def test_registry_is_append_only_and_duplicate_id_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"registry.jsonl"
            spec={"experiment_id":"CH-001","hypothesis":"x","model":"m","features":["a"],"training_period":"2021-2024","validation_period":"prospective","primary_metric":"brier","success_rule":"ci lower > 0","code_commit_sha":"abc"}
            register(spec,path,registered_at="2026-09-01T00:00:00+00:00")
            with self.assertRaises(ValueError): register(spec,path)
            self.assertTrue(verify(path)["valid"])

    def test_coverage_records_skips_without_network(self) -> None:
        candidate={"target_date":"2026-09-01","analyzed_at":"2026-09-01T12:00:00Z","results":[{"game_pk":"1","home":"H","away":"A","phase":"LATE","market_snapshot":{"freshness_verified":True},"sharp_market":{"freshness_verified":True,"selections":{"home_ml":{}}},"execution_market":{"freshness_verified":True,"selections":{"home_ml":{}}}}],"skipped":[{"game_pk":"2","reason":"odds_event_unmatched"}]}
        rows=rows_from_candidate(candidate)
        self.assertEqual(len(rows),2)
        self.assertTrue(rows[0]["eligible"])
        self.assertFalse(rows[1]["eligible"])
        self.assertEqual(rows[1]["rejection_reason"],"odds_event_unmatched")
        self.assertTrue(all(r["network_calls_added"]==0 for r in rows))

    def test_pinnacle_is_primary_and_exchange_cannot_substitute(self) -> None:
        row={"sharp_market":{"selections":{"home_ml":{"contributors":[{"bookmaker":"betfair_ex_eu","source_type":"EXCHANGE_PROXY","fair_probability":.60},{"bookmaker":"pinnacle","source_type":"SPORTSBOOK","fair_probability":.55}]}}}}
        self.assertAlmostEqual(pinnacle_probability(row,"home_ml") or 0,.55)
        row2={"sharp_market":{"selections":{"home_ml":{"contributors":[{"bookmaker":"betfair_ex_eu","source_type":"EXCHANGE_PROXY","fair_probability":.60}]}}}}
        self.assertIsNone(pinnacle_probability(row2,"home_ml"))

    def test_cost_gate_does_not_call_loader_when_nothing_due(self) -> None:
        with TemporaryDirectory() as tmp:
            root=Path(tmp); market=root/"market.jsonl"; paper=root/"paper.jsonl"; bet=root/"bet.jsonl"
            called={"n":0}
            def loader():
                called["n"]+=1
                return []
            out=cost_aware_run(market,paper,bet,events_loader=loader,now=datetime(2026,9,1,tzinfo=timezone.utc))
            self.assertFalse(out["api_call_performed"])
            self.assertEqual(out["paid_api_snapshots"],0)
            self.assertEqual(called["n"],0)

    def test_paid_gate_starts_only_inside_certified_close_window(self) -> None:
        self.assertEqual(CERTIFIED_DUE_WINDOW_MINUTES,15.0)
        with TemporaryDirectory() as tmp:
            root=Path(tmp); market=root/"market.jsonl"; paper=root/"paper.jsonl"; bet=root/"bet.jsonl"
            now=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
            row={
                "schema":"pulsar-v14-market-close-v1",
                "game_pk":"1",
                "game_date":(now+timedelta(minutes=16)).isoformat(),
                "odds_event_time_verified":True,
                "close_history":[],
                "best_close":None,
            }
            market.write_text(json.dumps(row)+"\n",encoding="utf-8")
            self.assertEqual(due_games(market,paper,bet,now=now),[])
            row["game_date"]=(now+timedelta(minutes=15)).isoformat()
            market.write_text(json.dumps(row)+"\n",encoding="utf-8")
            due=due_games(market,paper,bet,now=now)
            self.assertEqual(len(due),1)
            self.assertEqual(due[0]["source"],"MARKET")


if __name__=="__main__": unittest.main()
