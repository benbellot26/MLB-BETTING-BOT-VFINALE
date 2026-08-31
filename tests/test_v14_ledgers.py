from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.bet_ledger import _read as read_authorized
from v14.bet_ledger import record_payload as record_authorized
from v14.executed_bet_ledger import _read as read_executed
from v14.executed_bet_ledger import record_execution, report as report_executed
from v14.official_close import capture as capture_authorized_close
from v14.paper_ledger import _read as read_paper
from v14.paper_ledger import capture_close as capture_paper_close
from v14.paper_ledger import record_payload as record_paper
from v14.paper_ledger import report as report_paper

GAME_DATE="2026-08-25T23:00:00Z"; ANALYZED_AT="2026-08-25T20:00:00Z"; CLOSE_AT=datetime(2026,8,25,22,0,tzinfo=timezone.utc)


def _event(event_id="odds-123",include_total=True,commence_time=GAME_DATE):
    pinnacle_markets=[{"key":"h2h","outcomes":[{"name":"Home","price":1.80},{"name":"Away","price":2.10}]}]
    if include_total: pinnacle_markets.append({"key":"totals","outcomes":[{"name":"Over","point":8.5,"price":1.91},{"name":"Under","point":8.5,"price":1.91}]})
    return {"id":event_id,"home_team":"Home","away_team":"Away","commence_time":commence_time,"bookmakers":[{"key":"pinnacle","last_update":"2026-08-25T21:59:00Z","markets":pinnacle_markets},{"key":"winamax_fr","last_update":"2026-08-25T20:00:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":1.95},{"name":"Away","price":1.95}]}]}]}


def _paper_payload(analyzed_at=ANALYZED_AT,event_time=GAME_DATE):
    return {"model_generation":MODEL_GENERATION,"target_date":"2026-08-25","analyzed_at":analyzed_at,"results":[{"game_pk":"123","model_generation":MODEL_GENERATION,"odds_event_id":"odds-123","game_date":GAME_DATE,"analyzed_at":analyzed_at,"home":"Home","away":"Away","canonical_lines":{"TOTAL":8.5},"starter_fallback":{"degraded":False},"market_snapshot":{"freshness_verified":True,"commence_time":event_time,"markets":{"ML":{"bookmaker":"pinnacle"}}},"execution_market":{"freshness_verified":True,"selections":{"home_ml":{"price":2.00,"bookmaker":"pinnacle"}}},"sharp_market":{"freshness_verified":True,"selections":{"home_ml":{"fair_probability":.54,"source_count":1,"sportsbook_source_count":1,"exchange_proxy_source_count":0}}},"v14_prediction":{"model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"calibration":{"probability_policy_id":PROBABILITY_POLICY_ID},"probabilities":{"home_ml":.60},"raw_probabilities":{"home_ml":.61}},"decision":{"candidates":[{"selection":"home_ml","canonical_market":"ML","market":"ML","price":2.00,"execution_book":"pinnacle","execution_source":"LINE_SHOPPED","probability":.60,"lower_probability":.56,"model_edge_pp":10.0,"robust_edge_pp":6.0,"sharp_edge_pp":6.0,"robust_sharp_edge_pp":2.0,"sharp_source_count":1,"sharp_sportsbook_source_count":1,"sharp_exchange_proxy_source_count":0,"edge_qualified":True,"research_ready":True,"market_betting_certified":False,"status":"RESEARCH_ONLY"}]}}]}


def _authorized_payload(certified:bool,analyzed_at=ANALYZED_AT):
    payload=_paper_payload(analyzed_at)
    payload["betting_certification"]={"model_generation":MODEL_GENERATION,"certified":certified,"betting_status":"BETTING_CERTIFIED" if certified else "RESEARCH_ONLY","markets":{"ML":{"betting_certified":certified}}}
    candidate=payload["results"][0]["decision"]["candidates"][0]
    candidate["status"]="BET"; candidate["lower_probability"]=.60; candidate["execution_book"]="pinnacle"; candidate["market_betting_certified"]=certified; candidate["sharp_sportsbook_source_count"]=1
    return payload


class V14LedgerTests(unittest.TestCase):
    def test_paper_candidate_is_recorded_and_gets_executable_to_sharp_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload(),ledger),1); rows=read_paper(ledger); self.assertEqual(len(rows),1); self.assertEqual(rows[0]["schema"],"pulsar-v14-paper-bet-v8"); self.assertEqual(rows[0]["probability_policy_id"],PROBABILITY_POLICY_ID); self.assertTrue(rows[0]["odds_event_time_verified"]); self.assertEqual(rows[0]["selection"],"home_ml"); self.assertEqual(rows[0]["odds_event_id"],"odds-123"); self.assertTrue(rows[0]["entry_market_freshness_verified"]); self.assertIsNone(rows[0]["closing_sharp_probability"]); self.assertEqual(capture_paper_close(ledger,events_loader=lambda:[_event()],now=CLOSE_AT),1); closed=read_paper(ledger)[0]; self.assertIsNotNone(closed["closing_sharp_probability"]); self.assertIsNotNone(closed["closing_pinnacle_probability"]); self.assertIsNotNone(closed["sharp_clv_pp"]); self.assertIsNotNone(closed["certification_clv_pp"]); self.assertEqual(closed["certification_clv_benchmark"],"PINNACLE_NO_VIG"); self.assertEqual(closed["close_captured_at"],CLOSE_AT.isoformat())

    def test_ml_close_does_not_require_total_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper=Path(tmp)/"paper.jsonl"; authorized=Path(tmp)/"authorized.jsonl"
            self.assertEqual(record_paper(_paper_payload(),paper),1); self.assertEqual(capture_paper_close(paper,events_loader=lambda:[_event(include_total=False)],now=CLOSE_AT),1); self.assertIsNotNone(read_paper(paper)[0]["closing_sharp_probability"])
            self.assertEqual(record_authorized(_authorized_payload(True),authorized),1); self.assertEqual(capture_authorized_close(path=authorized,events_loader=lambda:[_event(include_total=False)],now=CLOSE_AT),1); self.assertIsNotNone(read_authorized(authorized)[0]["closing_odds"])

    def test_paper_entry_is_immutable_per_game_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload("2026-08-25T19:00:00Z"),ledger),1); self.assertEqual(record_paper(_paper_payload("2026-08-25T20:00:00Z"),ledger),0); out=report_paper(read_paper(ledger)); self.assertEqual(out["schema"],"pulsar-v14-paper-bet-performance-v8"); self.assertEqual(out["probability_policy_id"],PROBABILITY_POLICY_ID); self.assertEqual(out["primary_clv_benchmark"],"PINNACLE_NO_VIG"); self.assertEqual(out["raw_observations"],1); self.assertEqual(out["observations"],1); self.assertEqual(out["by_market"]["ML"]["independent_games"],1); self.assertIn("first",out["entry_policy"])

    def test_persisted_event_id_never_falls_back_to_similar_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload(),ledger),1); self.assertEqual(capture_paper_close(ledger,events_loader=lambda:[_event("different-id")],now=CLOSE_AT),0); self.assertIsNone(read_paper(ledger)[0]["closing_sharp_probability"])

    def test_paper_rejects_postgame_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload("2026-08-25T23:01:00Z"),ledger),0); self.assertEqual(read_paper(ledger),[])

    def test_paper_rejects_unverified_entry_market_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; payload=_paper_payload(); payload["results"][0]["sharp_market"]["freshness_verified"]=False; self.assertEqual(record_paper(payload,ledger),0); self.assertEqual(read_paper(ledger),[])

    def test_paper_rejects_missing_or_wrong_probability_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; payload=_paper_payload(); payload["results"][0]["v14_prediction"]["probability_policy_id"]="old-policy"; payload["results"][0]["v14_prediction"]["calibration"]["probability_policy_id"]="old-policy"; self.assertEqual(record_paper(payload,ledger),0); self.assertEqual(read_paper(ledger),[])

    def test_paper_requires_timestamp_verified_odds_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload(event_time=None),ledger),0); self.assertEqual(record_paper(_paper_payload(event_time="2026-08-26T01:00:00Z"),ledger),0); self.assertEqual(read_paper(ledger),[])

    def test_paper_close_rejects_same_event_id_with_wrong_start_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload(),ledger),1); self.assertEqual(capture_paper_close(ledger,events_loader=lambda:[_event(commence_time="2026-08-26T01:00:00Z")],now=CLOSE_AT),0); self.assertIsNone(read_paper(ledger)[0]["closing_sharp_probability"])

    def test_authorized_ledger_refuses_uncertified_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"authorized.jsonl"; self.assertEqual(record_authorized(_authorized_payload(False),ledger),0); self.assertEqual(read_authorized(ledger),[])

    def test_authorized_ledger_refuses_market_not_certified_even_when_global_flag_is_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"authorized.jsonl"; payload=_authorized_payload(True); payload["betting_certification"]["markets"]["ML"]["betting_certified"]=False; payload["results"][0]["decision"]["candidates"][0]["market_betting_certified"]=False; self.assertEqual(record_authorized(payload,ledger),0); self.assertEqual(read_authorized(ledger),[])

    def test_authorized_ledger_requires_real_sharp_sportsbook_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"authorized.jsonl"; payload=_authorized_payload(True); payload["results"][0]["decision"]["candidates"][0]["sharp_sportsbook_source_count"]=0; self.assertEqual(record_authorized(payload,ledger),0); self.assertEqual(read_authorized(ledger),[])

    def test_authorized_ledger_uses_line_shopped_book_and_dedupes_later_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"authorized.jsonl"; self.assertEqual(record_authorized(_authorized_payload(True,"2026-08-25T19:00:00Z"),ledger),1); row=read_authorized(ledger)[0]; self.assertEqual(row["schema"],"pulsar-v14-authorized-bet-v5"); self.assertEqual(row["ledger_role"],"SYSTEM_AUTHORIZED_BET"); self.assertFalse(row["execution_confirmed"]); self.assertEqual(row["bookmaker"],"pinnacle"); self.assertEqual(row["bet_id"],"123:ML"); self.assertEqual(record_authorized(_authorized_payload(True,"2026-08-25T20:00:00Z"),ledger),0); self.assertEqual(len(read_authorized(ledger)),1)

    def test_certified_authorization_gets_conservative_stake_and_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"authorized.jsonl"; self.assertEqual(record_authorized(_authorized_payload(True),ledger),1); row=read_authorized(ledger)[0]; self.assertGreater(row["stake_fraction"],0.0); self.assertLessEqual(row["stake_fraction"],.01); self.assertIn(row["unit_tier"],{1,2,3}); self.assertEqual(capture_authorized_close(path=ledger,events_loader=lambda:[_event()],now=CLOSE_AT),1); closed=read_authorized(ledger)[0]; self.assertIsNotNone(closed["closing_odds"]); self.assertIsNotNone(closed["clv_implied_probability_pp"]); self.assertIn("Pinnacle no-vig",closed["closing_source"]); self.assertEqual(closed["sharp_information_benchmark"],"PINNACLE_NO_VIG"); self.assertIsNotNone(closed["execution_close_odds"])

    def test_stale_same_book_quote_is_not_used_as_tradable_close(self):
        payload=_authorized_payload(True); payload["results"][0]["decision"]["candidates"][0]["execution_book"]="winamax_fr"
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"authorized.jsonl"; self.assertEqual(record_authorized(payload,ledger),1); self.assertEqual(capture_authorized_close(path=ledger,events_loader=lambda:[_event()],now=CLOSE_AT),1); row=read_authorized(ledger)[0]; self.assertIsNotNone(row["sharp_information_clv_pp"]); self.assertIsNotNone(row["consensus_information_clv_pp"]); self.assertIsNone(row["execution_close_odds"]); self.assertIsNone(row["execution_price_clv_pp"])

    def test_real_execution_ledger_requires_explicit_execution_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"executed.jsonl"
            execution={"authorized_bet_id":"123:ML","game_pk":"123","canonical_market":"ML","selection":"home_ml","executed_at":"2026-08-25T20:05:00Z","bookmaker":"pinnacle","odds":1.97,"stake_units":2.0,"stake_cash":20.0,"unit_value":10.0,"source":"MANUAL_TRACKER","result":"WIN","return_cash":39.4,"profit_cash":19.4,"profit_units":1.94}
            self.assertTrue(record_execution(execution,ledger)); self.assertFalse(record_execution(execution,ledger)); rows=read_executed(ledger); self.assertEqual(len(rows),1); self.assertTrue(rows[0]["execution_confirmed"]); self.assertEqual(rows[0]["ledger_role"],"REAL_EXECUTION"); report=report_executed(rows); self.assertEqual(report["bets"],1); self.assertAlmostEqual(report["profit_cash"],19.4); self.assertAlmostEqual(report["profit_units"],1.94)
            with self.assertRaises(ValueError): record_execution({"authorized_bet_id":"bad"},ledger)

if __name__=="__main__": unittest.main()
