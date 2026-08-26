from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION
from v14.bet_ledger import _read as read_official
from v14.bet_ledger import record_payload as record_official
from v14.official_close import capture as capture_official_close
from v14.paper_ledger import _read as read_paper
from v14.paper_ledger import capture_close as capture_paper_close
from v14.paper_ledger import record_payload as record_paper
from v14.paper_ledger import report as report_paper

GAME_DATE="2026-08-25T23:00:00Z"; ANALYZED_AT="2026-08-25T20:00:00Z"; CLOSE_AT=datetime(2026,8,25,22,0,tzinfo=timezone.utc)


def _event(event_id="odds-123"):
    return {"id":event_id,"home_team":"Home","away_team":"Away","commence_time":GAME_DATE,"bookmakers":[{"key":"pinnacle","last_update":"2026-08-25T21:59:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":1.80},{"name":"Away","price":2.10}]},{"key":"totals","outcomes":[{"name":"Over","point":8.5,"price":1.91},{"name":"Under","point":8.5,"price":1.91}]}]},{"key":"winamax_fr","last_update":"2026-08-25T20:00:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":1.95},{"name":"Away","price":1.95}]}]}]}


def _paper_payload(analyzed_at=ANALYZED_AT):
    return {"model_generation":MODEL_GENERATION,"target_date":"2026-08-25","analyzed_at":analyzed_at,"results":[{"game_pk":"123","odds_event_id":"odds-123","game_date":GAME_DATE,"analyzed_at":analyzed_at,"home":"Home","away":"Away","canonical_lines":{"TOTAL":8.5},"starter_fallback":{"degraded":False},"sharp_market":{"selections":{"home_ml":{"fair_probability":.54}}},"v14_prediction":{"probabilities":{"home_ml":.60},"raw_probabilities":{"home_ml":.61}},"decision":{"candidates":[{"selection":"home_ml","canonical_market":"ML","market":"ML","price":2.00,"execution_book":"pinnacle","execution_source":"LINE_SHOPPED","probability":.60,"lower_probability":.56,"model_edge_pp":10.0,"robust_edge_pp":6.0,"sharp_edge_pp":6.0,"robust_sharp_edge_pp":2.0,"edge_qualified":True,"research_ready":True,"status":"RESEARCH_ONLY"}]}}]}


def _official_payload(certified:bool,analyzed_at=ANALYZED_AT):
    payload=_paper_payload(analyzed_at); payload["betting_certification"]={"certified":certified,"betting_status":"BETTING_CERTIFIED" if certified else "RESEARCH_ONLY"}; candidate=payload["results"][0]["decision"]["candidates"][0]; candidate["status"]="BET"; candidate["lower_probability"]=.60; candidate["execution_book"]="pinnacle"; payload["results"][0]["market_snapshot"]={"markets":{"ML":{"bookmaker":"winamax_fr"}}}; return payload


class V14LedgerTests(unittest.TestCase):
    def test_paper_candidate_is_recorded_and_gets_prospective_sharp_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload(),ledger),1); rows=read_paper(ledger); self.assertEqual(len(rows),1); self.assertEqual(rows[0]["selection"],"home_ml"); self.assertEqual(rows[0]["odds_event_id"],"odds-123"); self.assertIsNone(rows[0]["closing_sharp_probability"]); self.assertEqual(capture_paper_close(ledger,events_loader=lambda:[_event()],now=CLOSE_AT),1); closed=read_paper(ledger)[0]; self.assertIsNotNone(closed["closing_sharp_probability"]); self.assertIsNotNone(closed["sharp_clv_pp"]); self.assertEqual(closed["close_captured_at"],CLOSE_AT.isoformat())

    def test_paper_entry_is_immutable_per_game_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload("2026-08-25T19:00:00Z"),ledger),1); self.assertEqual(record_paper(_paper_payload("2026-08-25T20:00:00Z"),ledger),0); out=report_paper(read_paper(ledger)); self.assertEqual(out["raw_observations"],1); self.assertEqual(out["observations"],1); self.assertEqual(out["by_market"]["ML"]["independent_games"],1); self.assertIn("first",out["entry_policy"])

    def test_persisted_event_id_never_falls_back_to_similar_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"paper.jsonl"; self.assertEqual(record_paper(_paper_payload(),ledger),1); self.assertEqual(capture_paper_close(ledger,events_loader=lambda:[_event("different-id")],now=CLOSE_AT),0); self.assertIsNone(read_paper(ledger)[0]["closing_sharp_probability"])

    def test_official_ledger_refuses_uncertified_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"official.jsonl"; self.assertEqual(record_official(_official_payload(False),ledger),0); self.assertEqual(read_official(ledger),[])

    def test_official_ledger_uses_line_shopped_book_and_dedupes_later_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"official.jsonl"; self.assertEqual(record_official(_official_payload(True,"2026-08-25T19:00:00Z"),ledger),1); row=read_official(ledger)[0]; self.assertEqual(row["bookmaker"],"pinnacle"); self.assertEqual(row["bet_id"],"123:ML"); self.assertEqual(record_official(_official_payload(True,"2026-08-25T20:00:00Z"),ledger),0); self.assertEqual(len(read_official(ledger)),1)

    def test_certified_bet_is_recorded_with_conservative_stake_and_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"official.jsonl"; self.assertEqual(record_official(_official_payload(True),ledger),1); row=read_official(ledger)[0]; self.assertGreater(row["stake_fraction"],0.0); self.assertLessEqual(row["stake_fraction"],.01); self.assertIn(row["unit_tier"],{1,2,3}); self.assertEqual(capture_official_close(path=ledger,events_loader=lambda:[_event()],now=CLOSE_AT),1); closed=read_official(ledger)[0]; self.assertIsNotNone(closed["closing_odds"]); self.assertIsNotNone(closed["clv_implied_probability_pp"]); self.assertIn("verified sharp",closed["closing_source"]); self.assertIsNotNone(closed["execution_close_odds"])

    def test_stale_same_book_quote_is_not_used_as_tradable_close(self):
        payload=_official_payload(True); payload["results"][0]["decision"]["candidates"][0]["execution_book"]="winamax_fr"
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/"official.jsonl"; self.assertEqual(record_official(payload,ledger),1); self.assertEqual(capture_official_close(path=ledger,events_loader=lambda:[_event()],now=CLOSE_AT),1); row=read_official(ledger)[0]; self.assertIsNotNone(row["sharp_information_clv_pp"]); self.assertIsNone(row["execution_close_odds"]); self.assertIsNone(row["execution_price_clv_pp"])

if __name__=="__main__": unittest.main()
