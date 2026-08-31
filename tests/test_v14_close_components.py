from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.certification_timing import CERTIFICATION_RUN_TRIGGER
from v14.component_close_capture import (
    EXECUTION,
    PRIMARY,
    capture_official_components,
    capture_paper_components,
    official_component_needs,
    paper_component_needs,
)
from v14.paper_ledger import _read as read_paper
from v14.bet_ledger import _read as read_bets


NOW=datetime(2026,8,31,18,0,tzinfo=timezone.utc)
GAME=(NOW+timedelta(minutes=10)).isoformat()
ANALYZED=(NOW-timedelta(minutes=20)).isoformat()


def _write(path:Path,rows:list[dict])->None:
    path.write_text("".join(json.dumps(row,separators=(",",":"))+"\n" for row in rows),encoding="utf-8")


def _book(key:str,home_price:float,away_price:float,*,as_of:datetime)->dict:
    return {"key":key,"last_update":as_of.isoformat(),"markets":[{"key":"h2h","outcomes":[{"name":"Home","price":home_price},{"name":"Away","price":away_price}]}]}


def _event(*books:dict)->dict:
    return {"id":"event-a","home_team":"Home","away_team":"Away","commence_time":GAME,"bookmakers":list(books)}


def _paper()->dict:
    return {
        "schema":"pulsar-v14-paper-bet-v8",
        "model_generation":MODEL_GENERATION,
        "probability_policy_id":PROBABILITY_POLICY_ID,
        "run_trigger":CERTIFICATION_RUN_TRIGGER,
        "phase":"FINAL",
        "game_pk":"A",
        "odds_event_id":"event-a",
        "odds_event_time_verified":True,
        "game_date":GAME,
        "analyzed_at":ANALYZED,
        "home":"Home",
        "away":"Away",
        "market":"ML",
        "canonical_market":"ML",
        "selection":"home_ml",
        "total_line":None,
        "execution_book":"winamax_fr",
        "execution_odds":2.0,
        "entry_execution_implied_probability":0.50,
        "entry_sharp_probability":0.52,
        "close_history":[],
        "close_quality":None,
        "certification_clv_pp":None,
        "certification_clv_benchmark":None,
        "closing_pinnacle_probability":None,
        "execution_close_odds":None,
        "execution_price_clv_pp":None,
    }


def _official()->dict:
    return {
        "schema":"pulsar-v14-authorized-bet-v5",
        "ledger_role":"SYSTEM_AUTHORIZED_BET",
        "execution_confirmed":False,
        "model_generation":MODEL_GENERATION,
        "bet_id":"A:ML",
        "game_pk":"A",
        "odds_event_id":"event-a",
        "target_date":"2026-08-31",
        "game_date":GAME,
        "analyzed_at":ANALYZED,
        "home":"Home",
        "away":"Away",
        "market":"ML",
        "canonical_market":"ML",
        "selection":"home_ml",
        "line":None,
        "bookmaker":"winamax_fr",
        "odds":2.0,
        "result":None,
        "close_history":[],
        "close_quality":None,
        "sharp_fair_close_probability":None,
        "sharp_information_clv_pp":None,
        "sharp_information_benchmark":None,
        "execution_close_odds":None,
        "execution_price_clv_pp":None,
    }


class V14CloseComponentTests(unittest.TestCase):
    def test_paper_execution_can_arrive_before_primary_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"paper.jsonl";_write(path,[_paper()])
            winamax=_event(_book("winamax_fr",1.90,2.05,as_of=NOW))
            self.assertEqual(capture_paper_components(path,events_loader=lambda:[winamax],now=NOW),1)
            first=read_paper(path)[0]
            self.assertEqual(paper_component_needs(first),[PRIMARY])
            self.assertEqual(first["execution_close_odds"],1.90)
            execution_at=first["execution_close_captured_at"]
            self.assertIsNone(first.get("certification_clv_pp"))

            later=NOW+timedelta(minutes=5)
            pinnacle=_event(_book("pinnacle",1.80,2.10,as_of=later))
            self.assertEqual(capture_paper_components(path,events_loader=lambda:[pinnacle],now=later),1)
            second=read_paper(path)[0]
            self.assertEqual(paper_component_needs(second),[])
            self.assertEqual(second["execution_close_odds"],1.90)
            self.assertEqual(second["execution_close_captured_at"],execution_at)
            self.assertEqual(second["certification_clv_benchmark"],"PINNACLE_NO_VIG")
            self.assertIsNotNone(second["certification_clv_pp"])
            self.assertEqual(second["primary_close_captured_at"],later.isoformat())

    def test_paper_primary_can_arrive_before_execution_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"paper.jsonl";_write(path,[_paper()])
            pinnacle=_event(_book("pinnacle",1.80,2.10,as_of=NOW))
            self.assertEqual(capture_paper_components(path,events_loader=lambda:[pinnacle],now=NOW),1)
            first=read_paper(path)[0]
            self.assertEqual(paper_component_needs(first),[EXECUTION])
            primary_at=first["primary_close_captured_at"];primary_probability=first["closing_pinnacle_probability"]

            later=NOW+timedelta(minutes=5)
            winamax=_event(_book("winamax_fr",1.88,2.08,as_of=later))
            self.assertEqual(capture_paper_components(path,events_loader=lambda:[winamax],now=later),1)
            second=read_paper(path)[0]
            self.assertEqual(paper_component_needs(second),[])
            self.assertEqual(second["primary_close_captured_at"],primary_at)
            self.assertAlmostEqual(second["closing_pinnacle_probability"],primary_probability)
            self.assertEqual(second["execution_close_odds"],1.88)
            self.assertEqual(second["execution_close_captured_at"],later.isoformat())

    def test_official_components_are_independent_and_terminal_only_when_both_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bets.jsonl";_write(path,[_official()])
            winamax=_event(_book("winamax_fr",1.91,2.04,as_of=NOW))
            self.assertEqual(capture_official_components(path=path,events_loader=lambda:[winamax],now=NOW),1)
            first=read_bets(path)[0]
            self.assertEqual(official_component_needs(first),[PRIMARY])
            execution_at=first["execution_close_captured_at"]

            later=NOW+timedelta(minutes=5)
            pinnacle=_event(_book("pinnacle",1.82,2.06,as_of=later))
            self.assertEqual(capture_official_components(path=path,events_loader=lambda:[pinnacle],now=later),1)
            second=read_bets(path)[0]
            self.assertEqual(official_component_needs(second),[])
            self.assertEqual(second["execution_close_captured_at"],execution_at)
            self.assertEqual(second["execution_close_odds"],1.91)
            self.assertEqual(second["sharp_information_benchmark"],"PINNACLE_NO_VIG")
            self.assertIsNotNone(second["sharp_information_clv_pp"])

    def test_generic_timing_close_does_not_satisfy_components(self):
        paper=_paper();paper.update({"close_quality":"CERTIFIED_CLOSE","close_captured_at":NOW.isoformat(),"close_minutes_to_game":10.0})
        official=_official();official.update({"close_quality":"CERTIFIED_CLOSE","close_captured_at":NOW.isoformat(),"close_minutes_to_game":10.0})
        self.assertEqual(paper_component_needs(paper),[PRIMARY,EXECUTION])
        self.assertEqual(official_component_needs(official),[PRIMARY,EXECUTION])


if __name__=="__main__":unittest.main()
