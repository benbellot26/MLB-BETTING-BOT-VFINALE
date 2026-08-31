from __future__ import annotations

"""Cost-aware gate in front of all paid Odds close-capture consumers.

The workflow may wake frequently, but this module makes ZERO network calls until
at least one tracked/paper/official row is inside the certified-close window and
still lacks a certified close. When a call is due, one request-equivalent budget
reservation is persisted BEFORE the paid Odds request, then ONE returned snapshot
is reused by the market archive, paper ledger and official bet ledger.

Each consumer receives only the exact event IDs for due rows that have a verified
Odds identity. This makes the first certified close immutable in the production
collection path: a later paid snapshot triggered by another game or another
ledger cannot silently rewrite an already-certified market, paper or official
close. Legacy rows without an event ID may still preserve the historical paid-
gate/budget contract, but they receive no snapshot events and therefore cannot
cross-match another game through this shared orchestration path.

Paper hydration is also local and immutable: only an unclosed current-policy paper
row may be hydrated, and it uses the earliest prospectively archived <=15 minute
close that contains the exact Pinnacle no-vig probability for that selection.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .acquisition import odds_snapshot, parse_time
from .api_budget import LEDGER as API_USAGE_LEDGER, allowance as api_allowance, record_close_snapshot
from .bet_ledger import LEDGER as BET_LEDGER
from .market_close_ledger import (
    CERTIFIED_CLOSE_MAX_MINUTES,
    LEDGER as MARKET_LEDGER,
    PRIMARY_SHARP_BENCHMARK,
    _execution_from_close,
    _read as read_market,
    _selection_from_close,
    capture as capture_market,
)
from .official_close import capture as capture_official
from .paper_ledger import LEDGER as PAPER_LEDGER, capture_close as capture_paper

CERTIFIED_DUE_WINDOW_MINUTES = 15.0


def _num(value:Any)->float|None:
    try:out=float(value)
    except Exception:return None
    return out if math.isfinite(out) else None


def _generic_read(path: Path | str) -> list[dict[str, Any]]:
    target=Path(path)
    if not target.exists():return []
    out=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:row=json.loads(line)
        except Exception:continue
        if isinstance(row,dict):out.append(row)
    return out


def _generic_write(path:Path|str,rows:list[dict[str,Any]])->None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text("".join(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n" for row in rows),encoding="utf-8")


def _has_certified_close(row:dict[str,Any])->bool:
    best=row.get("best_close") or {}
    if str(best.get("quality") or "")=="CERTIFIED_CLOSE" or str(row.get("close_quality") or "")=="CERTIFIED_CLOSE":return True
    return any(isinstance(close,dict) and str(close.get("quality") or "")=="CERTIFIED_CLOSE" for close in row.get("close_history") or [])


def _due(rows:list[dict[str,Any]],current:datetime,source:str)->list[dict[str,Any]]:
    due=[]
    for row in rows:
        if _has_certified_close(row):continue
        try:minutes=(parse_time(row.get("game_date"))-current).total_seconds()/60.0
        except Exception:continue
        if 0<minutes<=CERTIFIED_DUE_WINDOW_MINUTES:
            due.append({"source":source,"game_pk":row.get("game_pk"),"odds_event_id":str(row.get("odds_event_id") or ""),"minutes_to_game":minutes})
    return due


def due_games(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER,bet_path:Path|str=BET_LEDGER,*,now:datetime|None=None)->list[dict[str,Any]]:
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc);market_rows=[r for r in read_market(market_path) if r.get("odds_event_time_verified") is True]
    return _due(market_rows,current,"MARKET")+_due(_generic_read(paper_path),current,"PAPER")+_due(_generic_read(bet_path),current,"OFFICIAL")


def _events_for_source(events:list[dict[str,Any]],due:list[dict[str,Any]],source:str)->list[dict[str,Any]]:
    """Return only exact snapshot events explicitly due for one ledger consumer."""
    event_ids={str(row.get("odds_event_id") or "") for row in due if str(row.get("source") or "").upper()==source and row.get("odds_event_id")}
    if not event_ids:return []
    return [event for event in events if str(event.get("id") or "") in event_ids]


def _first_primary_archive_close(archive:dict[str,Any],paper:dict[str,Any])->tuple[dict[str,Any],dict[str,Any],float,float]|None:
    try:analyzed=parse_time(paper.get("analyzed_at"));game=parse_time(paper.get("game_date"))
    except Exception:return None
    candidates=[]
    for close in archive.get("close_history") or []:
        if not isinstance(close,dict) or str(close.get("quality") or "")!="CERTIFIED_CLOSE":continue
        if str(close.get("odds_event_id") or "")!=str(paper.get("odds_event_id") or ""):continue
        try:captured=parse_time(close.get("captured_at"))
        except Exception:continue
        mins=_num(close.get("minutes_to_game"))
        if not (analyzed<=captured<game) or mins is None or not (0<mins<=CERTIFIED_CLOSE_MAX_MINUTES):continue
        selection=_selection_from_close(close,paper) or {};consensus=_num(selection.get("fair_probability"));pinnacle=_num(selection.get("pinnacle_no_vig_probability"))
        if consensus is None or pinnacle is None or not (0<consensus<1 and 0<pinnacle<1):continue
        candidates.append((captured,close,selection,consensus,pinnacle))
    if not candidates:return None
    candidates.sort(key=lambda item:item[0]);_,close,selection,consensus,pinnacle=candidates[0]
    return close,selection,consensus,pinnacle


def hydrate_first_paper(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER)->int:
    """Hydrate only the first usable primary close; never rewrite a certified paper row."""
    archives={str(row.get("game_pk") or ""):row for row in read_market(market_path) if row.get("model_generation")==MODEL_GENERATION and row.get("probability_policy_id")==PROBABILITY_POLICY_ID and row.get("certification_eligible") is False};papers=_generic_read(paper_path);changed=0
    for paper in papers:
        if paper.get("model_generation")!=MODEL_GENERATION or paper.get("probability_policy_id")!=PROBABILITY_POLICY_ID:continue
        if str(paper.get("close_quality") or "")=="CERTIFIED_CLOSE":continue
        archive=archives.get(str(paper.get("game_pk") or ""));event_id=str(paper.get("odds_event_id") or "")
        if archive is None or not event_id or str(archive.get("odds_event_id") or "")!=event_id:continue
        chosen=_first_primary_archive_close(archive,paper)
        if chosen is None:continue
        close,selection,consensus,pinnacle=chosen;archive_mins=_num(close.get("minutes_to_game"));entry_sharp=_num(paper.get("entry_sharp_probability"));entry_exec=_num(paper.get("entry_execution_implied_probability"))
        if entry_exec is None:
            odds=_num(paper.get("execution_odds"));entry_exec=1/odds if odds is not None and odds>1 else None
        if entry_exec is None:continue
        execution_close=_execution_from_close(close,paper)
        marker={"captured_at":close.get("captured_at"),"minutes_to_game":archive_mins,"quality":"CERTIFIED_CLOSE","sharp_fair_probability":consensus,"pinnacle_no_vig_probability":pinnacle,"primary_benchmark":PRIMARY_SHARP_BENCHMARK,"sharp_dispersion_pp":_num(selection.get("dispersion_pp")),"execution_close_odds":execution_close,"odds_event_id":close.get("odds_event_id"),"event_time_delta_minutes":archive.get("odds_event_time_delta_minutes"),"source":"RESEARCH_MARKET_CLOSE_ARCHIVE_FIRST_PRIMARY"}
        history=paper.get("close_history") if isinstance(paper.get("close_history"),list) else []
        if not any(isinstance(item,dict) and item.get("captured_at")==marker["captured_at"] and item.get("odds_event_id")==marker["odds_event_id"] and item.get("source")==marker["source"] for item in history):history.append(marker)
        paper["close_history"]=history;paper["close_captured_at"]=close.get("captured_at");paper["close_minutes_to_game"]=archive_mins;paper["close_quality"]="CERTIFIED_CLOSE";paper["closing_sharp_probability"]=consensus;paper["closing_pinnacle_probability"]=pinnacle;paper["sharp_fair_close_odds"]=1/consensus;paper["pinnacle_fair_close_odds"]=1/pinnacle;paper["sharp_clv_pp"]=(consensus-entry_sharp)*100 if entry_sharp is not None else None;paper["certification_clv_pp"]=(pinnacle-entry_exec)*100;paper["certification_clv_benchmark"]=PRIMARY_SHARP_BENCHMARK;paper["execution_close_odds"]=execution_close;paper["execution_price_clv_pp"]=(1/execution_close-entry_exec)*100 if execution_close is not None and execution_close>1 else None;changed+=1
    if changed:_generic_write(paper_path,papers)
    return changed


def run(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER,bet_path:Path|str=BET_LEDGER,*,api_usage_path:Path|str=API_USAGE_LEDGER,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->dict[str,Any]:
    hydrated=hydrate_first_paper(market_path,paper_path);due=due_games(market_path,paper_path,bet_path,now=now);budget=api_allowance(api_usage_path,now=now)
    if not due:
        return {"api_call_performed":False,"paid_api_snapshots":0,"budget_reserved":False,"captured":{"market":0,"paper":0,"official":0},"hydrated_paper":hydrated,"due_rows":0,"budget":budget,"reason":"no row needs a first certified close","cost_policy":"local first-primary hydration runs before due-check; paid Odds call only when a first certified close is still due"}
    if not budget["allowed"]:
        return {"api_call_performed":False,"paid_api_snapshots":0,"budget_reserved":False,"captured":{"market":0,"paper":0,"official":0},"hydrated_paper":hydrated,"due_rows":len(due),"due":due,"budget":budget,"budget_exhausted":True,"reason":"automated close API daily budget exhausted; fail closed without network call","cost_policy":"persistent daily cap protects against runaway paid requests"}
    reservation=record_close_snapshot(api_usage_path,now=now,due_rows=len(due))
    events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))()
    market_events=_events_for_source(events,due,"MARKET");paper_events=_events_for_source(events,due,"PAPER");official_events=_events_for_source(events,due,"OFFICIAL")
    market_changed=capture_market(market_path,api_key=api_key,events_loader=lambda:market_events,now=now);paper_changed=capture_paper(paper_path,api_key=api_key,events_loader=lambda:paper_events,now=now);official_changed=capture_official(path=bet_path,api_key=api_key,events_loader=lambda:official_events,now=now)
    hydrated+=hydrate_first_paper(market_path,paper_path);legacy_due=sum(1 for row in due if not row.get("odds_event_id"))
    return {"api_call_performed":True,"paid_api_snapshots":1,"budget_reserved":True,"reservation":reservation,"captured":{"market":market_changed,"paper":paper_changed,"official":official_changed},"hydrated_paper":hydrated,"due_rows":len(due),"due":due,"legacy_due_without_event_id":legacy_due,"consumer_event_counts":{"market":len(market_events),"paper":len(paper_events),"official":len(official_events)},"budget_before":budget,"budget_after":api_allowance(api_usage_path,now=now),"cost_policy":"one paid snapshot shared across consumers; each sees only due exact event IDs; legacy no-ID rows see no events; local hydration uses earliest archived Pinnacle-primary close only; certified paper rows are immutable"}


def main()->None:
    parser=argparse.ArgumentParser(description="Cost-aware unified V14 certified close capture");parser.add_argument("--market-ledger",default=str(MARKET_LEDGER));parser.add_argument("--paper-ledger",default=str(PAPER_LEDGER));parser.add_argument("--bet-ledger",default=str(BET_LEDGER));parser.add_argument("--api-usage-ledger",default=str(API_USAGE_LEDGER));parser.add_argument("--api-key");args=parser.parse_args();print(json.dumps(run(args.market_ledger,args.paper_ledger,args.bet_ledger,api_usage_path=args.api_usage_ledger,api_key=args.api_key),ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
