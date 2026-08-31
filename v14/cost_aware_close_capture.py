from __future__ import annotations

"""Cost-aware gate for component-wise V14 certified close evidence.

The workflow wakes frequently but makes no paid Odds call until at least one row
inside the <=15 minute certification window still needs evidence. PRIMARY
(Pinnacle no-vig) and EXECUTION (fresh same-book close) are independent needs:
a timing-qualified consensus snapshot no longer terminates either requirement.

One paid Odds snapshot is still shared per run. Each consumer receives only the
exact event IDs for its due rows. Legacy rows without event IDs may preserve the
historical paid-gate/budget contract but receive no events, so they cannot
cross-match another game.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .acquisition import odds_snapshot, parse_time
from .api_budget import LEDGER as API_USAGE_LEDGER, allowance as api_allowance, record_close_snapshot
from .bet_ledger import LEDGER as BET_LEDGER
from .component_close_capture import (
    EXECUTION,
    PRIMARY,
    capture_official_components,
    capture_paper_components,
    hydrate_paper_components,
    official_component_needs,
    paper_component_needs,
)
from .market_close_ledger import LEDGER as MARKET_LEDGER, _read as read_market, capture as capture_market
from .paper_ledger import LEDGER as PAPER_LEDGER

CERTIFIED_DUE_WINDOW_MINUTES=15.0
ARCHIVE="ARCHIVE"

# Compatibility aliases used by existing tests/tools. Production behavior is
# component-wise even though the public orchestration names remain stable.
capture_paper=capture_paper_components
capture_official=capture_official_components
hydrate_first_paper=hydrate_paper_components


def _generic_read(path:Path|str)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists():return []
    out=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:row=json.loads(line)
        except Exception:continue
        if isinstance(row,dict):out.append(row)
    return out


def _has_certified_archive_close(row:dict[str,Any])->bool:
    best=row.get("best_close") or {}
    if str(best.get("quality") or "")=="CERTIFIED_CLOSE":return True
    return any(isinstance(close,dict) and str(close.get("quality") or "")=="CERTIFIED_CLOSE" for close in row.get("close_history") or [])


def _needs(row:dict[str,Any],source:str)->list[str]:
    source=str(source or "").upper()
    if source=="PAPER":return paper_component_needs(row)
    if source=="OFFICIAL":return official_component_needs(row)
    if source=="MARKET":return [] if _has_certified_archive_close(row) else [ARCHIVE]
    return []


def _due(rows:list[dict[str,Any]],current:datetime,source:str)->list[dict[str,Any]]:
    due=[]
    for row in rows:
        needs=_needs(row,source)
        if not needs:continue
        try:minutes=(parse_time(row.get("game_date"))-current).total_seconds()/60.0
        except Exception:continue
        if 0<minutes<=CERTIFIED_DUE_WINDOW_MINUTES:
            due.append({"source":source,"game_pk":row.get("game_pk"),"odds_event_id":str(row.get("odds_event_id") or ""),"minutes_to_game":minutes,"needs":needs})
    return due


def due_games(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER,bet_path:Path|str=BET_LEDGER,*,now:datetime|None=None)->list[dict[str,Any]]:
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc);market_rows=[row for row in read_market(market_path) if row.get("odds_event_time_verified") is True]
    return _due(market_rows,current,"MARKET")+_due(_generic_read(paper_path),current,"PAPER")+_due(_generic_read(bet_path),current,"OFFICIAL")


def _events_for_source(events:list[dict[str,Any]],due:list[dict[str,Any]],source:str)->list[dict[str,Any]]:
    event_ids={str(row.get("odds_event_id") or "") for row in due if str(row.get("source") or "").upper()==source and row.get("odds_event_id")}
    if not event_ids:return []
    return [event for event in events if str(event.get("id") or "") in event_ids]


def _component_due_counts(due:list[dict[str,Any]])->dict[str,int]:
    return {
        "primary":sum(PRIMARY in (row.get("needs") or []) for row in due),
        "execution":sum(EXECUTION in (row.get("needs") or []) for row in due),
        "archive":sum(ARCHIVE in (row.get("needs") or []) for row in due),
    }


def run(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER,bet_path:Path|str=BET_LEDGER,*,api_usage_path:Path|str=API_USAGE_LEDGER,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->dict[str,Any]:
    hydrated=hydrate_first_paper(market_path,paper_path);due=due_games(market_path,paper_path,bet_path,now=now);budget=api_allowance(api_usage_path,now=now);component_counts=_component_due_counts(due)
    if not due:
        return {"api_call_performed":False,"paid_api_snapshots":0,"budget_reserved":False,"captured":{"market":0,"paper":0,"official":0},"hydrated_paper":hydrated,"due_rows":0,"component_due_counts":component_counts,"budget":budget,"reason":"no row has a missing certified close component","cost_policy":"local component hydration runs before due-check; paid Odds call only for missing <=15m PRIMARY/EXECUTION/archive evidence"}
    if not budget["allowed"]:
        return {"api_call_performed":False,"paid_api_snapshots":0,"budget_reserved":False,"captured":{"market":0,"paper":0,"official":0},"hydrated_paper":hydrated,"due_rows":len(due),"component_due_counts":component_counts,"due":due,"budget":budget,"budget_exhausted":True,"reason":"automated close API daily budget exhausted; fail closed without network call","cost_policy":"persistent daily cap protects against runaway paid requests"}
    reservation=record_close_snapshot(api_usage_path,now=now,due_rows=len(due));events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))()
    market_events=_events_for_source(events,due,"MARKET");paper_events=_events_for_source(events,due,"PAPER");official_events=_events_for_source(events,due,"OFFICIAL")
    market_changed=capture_market(market_path,api_key=api_key,events_loader=lambda:market_events,now=now);paper_changed=capture_paper(paper_path,api_key=api_key,events_loader=lambda:paper_events,now=now);official_changed=capture_official(path=bet_path,api_key=api_key,events_loader=lambda:official_events,now=now)
    hydrated+=hydrate_first_paper(market_path,paper_path);legacy_due=sum(1 for row in due if not row.get("odds_event_id"))
    return {"api_call_performed":True,"paid_api_snapshots":1,"budget_reserved":True,"reservation":reservation,"captured":{"market":market_changed,"paper":paper_changed,"official":official_changed},"hydrated_paper":hydrated,"due_rows":len(due),"component_due_counts":component_counts,"due":due,"legacy_due_without_event_id":legacy_due,"consumer_event_counts":{"market":len(market_events),"paper":len(paper_events),"official":len(official_events)},"budget_before":budget,"budget_after":api_allowance(api_usage_path,now=now),"cost_policy":"one paid snapshot shared across exact due events; PRIMARY and EXECUTION freeze independently; missing components remain retryable without overwriting completed evidence"}


def main()->None:
    parser=argparse.ArgumentParser(description="Cost-aware component-wise V14 certified close capture");parser.add_argument("--market-ledger",default=str(MARKET_LEDGER));parser.add_argument("--paper-ledger",default=str(PAPER_LEDGER));parser.add_argument("--bet-ledger",default=str(BET_LEDGER));parser.add_argument("--api-usage-ledger",default=str(API_USAGE_LEDGER));parser.add_argument("--api-key");args=parser.parse_args();print(json.dumps(run(args.market_ledger,args.paper_ledger,args.bet_ledger,api_usage_path=args.api_usage_ledger,api_key=args.api_key),ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
