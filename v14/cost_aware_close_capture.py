from __future__ import annotations

"""Cost-aware gate in front of all paid Odds close-capture consumers.

The workflow may wake frequently, but this module makes ZERO network calls until
at least one tracked/paper/official row is inside the certified-close window and
still lacks a certified close. When a call is due, ONE Odds snapshot is fetched
and reused by the market archive, paper ledger and official bet ledger. A
persistent daily budget also prevents runaway automated paid calls.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .acquisition import odds_snapshot, parse_time
from .api_budget import LEDGER as API_USAGE_LEDGER, allowance as api_allowance, record_close_snapshot
from .bet_ledger import LEDGER as BET_LEDGER
from .market_close_ledger import LEDGER as MARKET_LEDGER, _read as read_market, capture as capture_market
from .official_close import capture as capture_official
from .paper_ledger import LEDGER as PAPER_LEDGER, capture_close as capture_paper

CERTIFIED_DUE_WINDOW_MINUTES = 18.0


def _generic_read(path: Path | str) -> list[dict[str, Any]]:
    target=Path(path)
    if not target.exists(): return []
    out=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if isinstance(row,dict): out.append(row)
    return out


def _has_certified_close(row: dict[str, Any]) -> bool:
    best = row.get("best_close") or {}
    if str(best.get("quality") or "") == "CERTIFIED_CLOSE" or str(row.get("close_quality") or "") == "CERTIFIED_CLOSE":
        return True
    for close in row.get("close_history") or []:
        if isinstance(close, dict) and str(close.get("quality") or "") == "CERTIFIED_CLOSE":
            return True
    return False


def _due(rows:list[dict[str,Any]],current:datetime,source:str)->list[dict[str,Any]]:
    due=[]
    for row in rows:
        if _has_certified_close(row): continue
        try: minutes=(parse_time(row.get("game_date"))-current).total_seconds()/60.0
        except Exception: continue
        if 0<minutes<=CERTIFIED_DUE_WINDOW_MINUTES:
            due.append({"source":source,"game_pk":row.get("game_pk"),"minutes_to_game":minutes})
    return due


def due_games(
    market_path:Path|str=MARKET_LEDGER,
    paper_path:Path|str=PAPER_LEDGER,
    bet_path:Path|str=BET_LEDGER,
    *,
    now:datetime|None=None,
)->list[dict[str,Any]]:
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc)
    market_rows=[r for r in read_market(market_path) if r.get("odds_event_time_verified") is True]
    return _due(market_rows,current,"MARKET")+_due(_generic_read(paper_path),current,"PAPER")+_due(_generic_read(bet_path),current,"OFFICIAL")


def run(
    market_path:Path|str=MARKET_LEDGER,
    paper_path:Path|str=PAPER_LEDGER,
    bet_path:Path|str=BET_LEDGER,
    *,
    api_usage_path:Path|str=API_USAGE_LEDGER,
    api_key:str|None=None,
    events_loader:Callable[[],list[dict[str,Any]]]|None=None,
    now:datetime|None=None,
)->dict[str,Any]:
    due=due_games(market_path,paper_path,bet_path,now=now)
    budget=api_allowance(api_usage_path,now=now)
    if not due:
        return {"api_call_performed":False,"paid_api_snapshots":0,"captured":{"market":0,"paper":0,"official":0},"due_rows":0,"budget":budget,"reason":"no row needs a first certified close","cost_policy":"wake often; paid Odds call only when first certified close is due"}
    if not budget["allowed"]:
        return {"api_call_performed":False,"paid_api_snapshots":0,"captured":{"market":0,"paper":0,"official":0},"due_rows":len(due),"due":due,"budget":budget,"budget_exhausted":True,"reason":"automated close API daily budget exhausted; fail closed without network call","cost_policy":"persistent daily cap protects against runaway paid requests"}
    # Exactly one paid snapshot for this run. All consumers reuse the same in-memory events.
    events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))()
    record_close_snapshot(api_usage_path,now=now,due_rows=len(due))
    loader=lambda:events
    market_changed=capture_market(market_path,api_key=api_key,events_loader=loader,now=now)
    paper_changed=capture_paper(paper_path,api_key=api_key,events_loader=loader,now=now)
    official_changed=capture_official(path=bet_path,api_key=api_key,events_loader=loader,now=now)
    return {"api_call_performed":True,"paid_api_snapshots":1,"captured":{"market":market_changed,"paper":paper_changed,"official":official_changed},"due_rows":len(due),"due":due,"budget_before":budget,"budget_after":api_allowance(api_usage_path,now=now),"cost_policy":"one Odds snapshot shared across market/paper/official close capture; certified rows never trigger another paid call; daily budget enforced"}


def main()->None:
    parser=argparse.ArgumentParser(description="Cost-aware unified V14 certified close capture")
    parser.add_argument("--market-ledger",default=str(MARKET_LEDGER));parser.add_argument("--paper-ledger",default=str(PAPER_LEDGER));parser.add_argument("--bet-ledger",default=str(BET_LEDGER));parser.add_argument("--api-usage-ledger",default=str(API_USAGE_LEDGER));parser.add_argument("--api-key");args=parser.parse_args()
    print(json.dumps(run(args.market_ledger,args.paper_ledger,args.bet_ledger,api_usage_path=args.api_usage_ledger,api_key=args.api_key),ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
