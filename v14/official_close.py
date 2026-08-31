from __future__ import annotations

"""Prospective verified close capture for certified system-authorized bets.

Pinnacle no-vig is the primary information benchmark. The multi-book consensus
is retained as a secondary diagnostic and the same-book close remains the
tradable execution-quality benchmark.
"""

import argparse
from datetime import datetime, timezone
from typing import Any, Callable

from .acquisition import canonical_team_name, odds_snapshot, parse_time
from .bet_ledger import LEDGER, _read, _write
from .market_lines import DEFAULT_MAX_MARKET_AGE_MINUTES, _book_freshness
from .sharp_market import sharp_consensus

CLOSE_WINDOW_MINUTES=120.0
CERTIFIED_CLOSE_MAX_MINUTES=15.0
EVENT_TOLERANCE_MINUTES=60.0
EVENT_AMBIGUITY_MARGIN_MINUTES=20.0
PRIMARY_SHARP_BENCHMARK="PINNACLE_NO_VIG"


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception:return None
    return out if out==out and abs(out)!=float("inf") else None


def _pinnacle_probability(sharp_row:dict[str,Any])->float|None:
    for contributor in sharp_row.get("contributors") or []:
        if str(contributor.get("bookmaker") or "").lower()!="pinnacle":continue
        if str(contributor.get("source_type") or "").upper()!="SPORTSBOOK":continue
        value=_num(contributor.get("fair_probability"))
        if value is not None and 0<value<1:return value
    return None


def _event_for_row(row:dict[str,Any],events:list[dict[str,Any]])->dict[str,Any]|None:
    event_id=str(row.get("odds_event_id") or "")
    if event_id:
        exact=[event for event in events if str(event.get("id") or "")==event_id]
        return exact[0] if len(exact)==1 else None
    home=canonical_team_name(row.get("home")); away=canonical_team_name(row.get("away"))
    try: game_time=parse_time(row.get("game_date"))
    except Exception: return None
    candidates=[]
    for event in events:
        if canonical_team_name(event.get("home_team"))!=home or canonical_team_name(event.get("away_team"))!=away: continue
        try: delta=abs((parse_time(event.get("commence_time"))-game_time).total_seconds())/60
        except Exception: continue
        if delta<=EVENT_TOLERANCE_MINUTES: candidates.append((delta,event))
    candidates.sort(key=lambda x:x[0])
    if not candidates: return None
    if len(candidates)>1 and candidates[1][0]-candidates[0][0]<EVENT_AMBIGUITY_MARGIN_MINUTES: return None
    return candidates[0][1]


def _same_book_close(event:dict[str,Any],row:dict[str,Any],*,as_of:str)->float|None:
    book=next((b for b in event.get("bookmakers") or [] if str(b.get("key") or "")==str(row.get("bookmaker") or "")),None)
    if not book or _book_freshness(book,as_of,DEFAULT_MAX_MARKET_AGE_MINUTES)!="VERIFIED_FRESH": return None
    selection=str(row.get("selection") or ""); home=str(event.get("home_team") or ""); away=str(event.get("away_team") or ""); line=row.get("line"); market_key="h2h" if selection.endswith("_ml") else "totals" if selection in {"over","under"} else "spreads"; outcomes=[]
    for market in book.get("markets") or []:
        if str(market.get("key") or "")==market_key: outcomes=market.get("outcomes") or []; break
    name=home if selection.startswith("home") else away if selection.startswith("away") else "Over" if selection=="over" else "Under"; point=None
    if "minus_1_5" in selection: point=-1.5
    elif "plus_1_5" in selection: point=1.5
    elif selection in {"over","under"}: point=float(line) if line is not None else None
    for out in outcomes:
        if str(out.get("name") or "")!=name: continue
        try: op=float(out.get("point")) if out.get("point") is not None else None
        except Exception: op=None
        if point is not None and op!=point: continue
        try: price=float(out.get("price"))
        except Exception: continue
        if price>1: return price
    return None


def capture(*,path:str|Any=LEDGER,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->int:
    rows=_read(path); current=now or datetime.now(timezone.utc)
    if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc); pending=[]
    for row in rows:
        if row.get("result"): continue
        try: mins=(parse_time(row.get("game_date"))-current).total_seconds()/60
        except Exception: continue
        if 0<mins<=CLOSE_WINDOW_MINUTES: pending.append((row,mins))
    if not pending: return 0
    events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))(); captured=current.isoformat(); changed=0
    for row,mins in pending:
        event=_event_for_row(row,events)
        if event is None: continue
        selection=str(row.get("selection") or ""); total_line=row.get("line") if selection in {"over","under"} else None
        if selection in {"over","under"} and total_line is None: continue
        sharp=sharp_consensus(event,total_line=float(total_line) if total_line is not None else None,as_of=captured); sharp_row=((sharp.get("selections") or {}).get(selection) or {}); consensus_p=_num(sharp_row.get("fair_probability")); pinnacle_p=_pinnacle_probability(sharp_row)
        if consensus_p is None or not 0<consensus_p<1 or sharp.get("freshness_verified") is not True: continue
        entry_odds=float(row.get("odds") or 0)
        if entry_odds<=1: continue
        tradable=_same_book_close(event,row,as_of=captured); quality="CERTIFIED_CLOSE" if mins<=CERTIFIED_CLOSE_MAX_MINUTES else "PROVISIONAL_CLOSE"; history=row.get("close_history") if isinstance(row.get("close_history"),list) else []
        history.append({"captured_at":captured,"minutes_to_game":mins,"quality":quality,"sharp_fair_probability":consensus_p,"pinnacle_no_vig_probability":pinnacle_p,"primary_benchmark":PRIMARY_SHARP_BENCHMARK if pinnacle_p is not None else None,"same_book_close_odds":tradable,"same_book_fresh":tradable is not None,"odds_event_id":event.get("id")}); row["close_history"]=history
        # Compatibility fields now point at the primary benchmark when it exists.
        primary=pinnacle_p
        row["closing_odds"]=(1/primary) if primary is not None else None; row["closing_source"]=(f"verified Pinnacle no-vig fair probability <={CLOSE_WINDOW_MINUTES:.0f}m pregame ({quality})" if primary is not None else f"verified sharp consensus only <={CLOSE_WINDOW_MINUTES:.0f}m pregame ({quality}); primary unavailable")
        row["clv_implied_probability_pp"]=(primary-1/entry_odds)*100 if primary is not None else None; row["sharp_fair_close_probability"]=primary; row["sharp_fair_close_odds"]=(1/primary) if primary is not None else None; row["sharp_information_clv_pp"]=(primary-1/entry_odds)*100 if primary is not None else None; row["sharp_information_benchmark"]=PRIMARY_SHARP_BENCHMARK if primary is not None else None
        row["consensus_fair_close_probability"]=consensus_p; row["consensus_information_clv_pp"]=(consensus_p-1/entry_odds)*100; row["execution_close_odds"]=tradable; row["execution_price_clv_pp"]=(1/tradable-1/entry_odds)*100 if tradable else None; row["close_quality"]=quality; row["close_minutes_to_game"]=mins; row["close_captured_at"]=captured; changed+=1
    if changed: _write(rows,path)
    return changed


def main()->None:
    parser=argparse.ArgumentParser(description="Capture prospective verified closes for V14 system-authorized bets"); parser.add_argument("--ledger",default=str(LEDGER)); args=parser.parse_args(); print(f"PULSAR_V14_OFFICIAL_CLOSE captured={capture(path=args.ledger)}")

if __name__=="__main__": main()
