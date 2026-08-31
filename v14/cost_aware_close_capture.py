from __future__ import annotations

"""Ultra-low cost-aware gate for component-wise V14 close evidence.

The workflow wakes frequently but makes no paid Odds call until certified close
evidence is due. Under the 500-credit/month plan only one automated close
snapshot may be bought per UTC day, so the orchestrator waits when a larger
pending close cluster can be covered later with that same single request.

PRIMARY (Pinnacle no-vig) and EXECUTION (fresh same-book close) remain
independent and immutable. One paid snapshot is shared across exact due event
IDs and every consumer; legacy rows without event IDs can preserve the old gate
contract but never receive another event by accident.
"""

import argparse
from datetime import datetime, timedelta, timezone
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
CLUSTER_LOOKAHEAD_HOURS=12.0
ARCHIVE="ARCHIVE"

capture_paper=capture_paper_components
capture_official=capture_official_components
hydrate_first_paper=hydrate_paper_components


def _current(now:datetime|None=None)->datetime:
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


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


def _qualified_rows(rows:list[dict[str,Any]],current:datetime,source:str,*,due_only:bool)->list[dict[str,Any]]:
    out=[]
    for row in rows:
        needs=_needs(row,source)
        if not needs:continue
        try:game_time=parse_time(row.get("game_date"));minutes=(game_time-current).total_seconds()/60.0
        except Exception:continue
        if due_only:
            if not 0<minutes<=CERTIFIED_DUE_WINDOW_MINUTES:continue
        elif not 0<minutes<=CLUSTER_LOOKAHEAD_HOURS*60.0:
            continue
        out.append({"source":source,"game_pk":str(row.get("game_pk") or ""),"odds_event_id":str(row.get("odds_event_id") or ""),"game_time":game_time,"minutes_to_game":minutes,"needs":needs})
    return out


def _source_rows(market_path:Path|str,paper_path:Path|str,bet_path:Path|str)->dict[str,list[dict[str,Any]]]:
    return {
        "MARKET":[row for row in read_market(market_path) if row.get("odds_event_time_verified") is True],
        "PAPER":_generic_read(paper_path),
        "OFFICIAL":_generic_read(bet_path),
    }


def due_games(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER,bet_path:Path|str=BET_LEDGER,*,now:datetime|None=None)->list[dict[str,Any]]:
    current=_current(now);sources=_source_rows(market_path,paper_path,bet_path);due=[]
    for source,rows in sources.items():due.extend(_qualified_rows(rows,current,source,due_only=True))
    for row in due:row.pop("game_time",None)
    return due


def _cluster_key(row:dict[str,Any])->str:
    event=str(row.get("odds_event_id") or "")
    if event:return f"event:{event}"
    return f"legacy:{row.get('game_pk') or ''}"


def best_close_cluster(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER,bet_path:Path|str=BET_LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    current=_current(now);sources=_source_rows(market_path,paper_path,bet_path);pending=[]
    for source,rows in sources.items():pending.extend(_qualified_rows(rows,current,source,due_only=False))
    if not pending:return {"target_at":None,"games":0,"evidence_components":0,"game_keys":[]}
    candidates={current}
    for row in pending:
        opening=row["game_time"]-timedelta(minutes=CERTIFIED_DUE_WINDOW_MINUTES)
        if opening>=current:candidates.add(opening)
    scored=[]
    for candidate in candidates:
        visible=[row for row in pending if 0<(row["game_time"]-candidate).total_seconds()/60.0<=CERTIFIED_DUE_WINDOW_MINUTES]
        if not visible:continue
        keys={_cluster_key(row) for row in visible}
        evidence=sum(1 for row in visible if row["source"] in {"PAPER","OFFICIAL"} for need in row.get("needs") or [] if need in {PRIMARY,EXECUTION})
        scored.append((len(keys),evidence,candidate,visible,keys))
    if not scored:return {"target_at":None,"games":0,"evidence_components":0,"game_keys":[]}
    max_games=max(row[0] for row in scored);best=[row for row in scored if row[0]==max_games];max_evidence=max(row[1] for row in best);best=[row for row in best if row[1]==max_evidence];games,evidence,target,visible,keys=min(best,key=lambda row:row[2])
    return {"target_at":target.isoformat(),"games":games,"evidence_components":evidence,"game_keys":sorted(keys),"sources":sorted({row["source"] for row in visible}),"policy":"MAX_UNIQUE_GAMES_THEN_PRIMARY_EXECUTION_COMPONENTS_THEN_EARLIEST"}


def _events_for_source(events:list[dict[str,Any]],due:list[dict[str,Any]],source:str)->list[dict[str,Any]]:
    event_ids={str(row.get("odds_event_id") or "") for row in due if str(row.get("source") or "").upper()==source and row.get("odds_event_id")}
    if not event_ids:return []
    return [event for event in events if str(event.get("id") or "") in event_ids]


def _component_due_counts(due:list[dict[str,Any]])->dict[str,int]:
    return {"primary":sum(PRIMARY in (row.get("needs") or []) for row in due),"execution":sum(EXECUTION in (row.get("needs") or []) for row in due),"archive":sum(ARCHIVE in (row.get("needs") or []) for row in due)}


def run(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER,bet_path:Path|str=BET_LEDGER,*,api_usage_path:Path|str=API_USAGE_LEDGER,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->dict[str,Any]:
    current=_current(now);hydrated=hydrate_first_paper(market_path,paper_path);due=due_games(market_path,paper_path,bet_path,now=current);plan=best_close_cluster(market_path,paper_path,bet_path,now=current);budget=api_allowance(api_usage_path,now=current);component_counts=_component_due_counts(due)
    if not due:
        return {"api_call_performed":False,"paid_api_snapshots":0,"budget_reserved":False,"captured":{"market":0,"paper":0,"official":0},"hydrated_paper":hydrated,"due_rows":0,"component_due_counts":component_counts,"budget":budget,"best_close_cluster":plan,"reason":"no row has a missing certified close component","cost_policy":"one automated close snapshot/day; local component hydration before any paid call"}
    if not budget["allowed"]:
        return {"api_call_performed":False,"paid_api_snapshots":0,"budget_reserved":False,"captured":{"market":0,"paper":0,"official":0},"hydrated_paper":hydrated,"due_rows":len(due),"component_due_counts":component_counts,"due":due,"budget":budget,"best_close_cluster":plan,"budget_exhausted":True,"reason":"automated close API budget exhausted; fail closed without network call","cost_policy":"daily and monthly caps protect the 500-credit plan"}
    target=parse_time(plan["target_at"]) if plan.get("target_at") else current
    if target>current+timedelta(seconds=30):
        return {"api_call_performed":False,"paid_api_snapshots":0,"budget_reserved":False,"captured":{"market":0,"paper":0,"official":0},"hydrated_paper":hydrated,"due_rows":len(due),"component_due_counts":component_counts,"due":due,"budget":budget,"best_close_cluster":plan,"reason":"waiting for larger close cluster before spending today's only close snapshot","cost_policy":"single daily close snapshot is delayed only when a better pending cluster exists"}
    reservation=record_close_snapshot(api_usage_path,now=current,due_rows=len(due));events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))()
    market_events=_events_for_source(events,due,"MARKET");paper_events=_events_for_source(events,due,"PAPER");official_events=_events_for_source(events,due,"OFFICIAL")
    market_changed=capture_market(market_path,api_key=api_key,events_loader=lambda:market_events,now=current);paper_changed=capture_paper(paper_path,api_key=api_key,events_loader=lambda:paper_events,now=current);official_changed=capture_official(path=bet_path,api_key=api_key,events_loader=lambda:official_events,now=current)
    hydrated+=hydrate_first_paper(market_path,paper_path);legacy_due=sum(1 for row in due if not row.get("odds_event_id"))
    return {"api_call_performed":True,"paid_api_snapshots":1,"budget_reserved":True,"reservation":reservation,"captured":{"market":market_changed,"paper":paper_changed,"official":official_changed},"hydrated_paper":hydrated,"due_rows":len(due),"component_due_counts":component_counts,"due":due,"best_close_cluster":plan,"legacy_due_without_event_id":legacy_due,"consumer_event_counts":{"market":len(market_events),"paper":len(paper_events),"official":len(official_events)},"budget_before":budget,"budget_after":api_allowance(api_usage_path,now=current),"cost_policy":"one paid close snapshot/day shared across exact due events; PRIMARY and EXECUTION freeze independently"}


def main()->None:
    parser=argparse.ArgumentParser(description="Ultra-low component-wise V14 certified close capture");parser.add_argument("--market-ledger",default=str(MARKET_LEDGER));parser.add_argument("--paper-ledger",default=str(PAPER_LEDGER));parser.add_argument("--bet-ledger",default=str(BET_LEDGER));parser.add_argument("--api-usage-ledger",default=str(API_USAGE_LEDGER));parser.add_argument("--api-key");args=parser.parse_args();print(json.dumps(run(args.market_ledger,args.paper_ledger,args.bet_ledger,api_usage_path=args.api_usage_ledger,api_key=args.api_key),ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
