from __future__ import annotations

"""Verified best-price execution layer, separate from sharp fair consensus."""

from typing import Any, Iterable
from .market_lines import DEFAULT_MAX_MARKET_AGE_MINUTES, _book_freshness, _market_outcomes, _num

DEFAULT_EXECUTION_BOOKS=("winamax_fr","betclic_fr","unibet_fr","pmu_fr","netbet_fr","pinnacle")


def _best(rows:list[dict[str,Any]],selection:str,point:float|None=None)->dict[str,Any]|None:
    candidates=[]
    for row in rows:
        if str(row.get("name") or "")!=selection: continue
        rp=_num(row.get("point"))
        if point is not None and rp!=point: continue
        price=_num(row.get("price"))
        if price is not None and price>1: candidates.append((price,row))
    if not candidates: return None
    price,row=max(candidates,key=lambda x:x[0]); return {"price":price,"point":_num(row.get("point")),"name":selection}


def best_execution(event:dict[str,Any],*,total_line:float,as_of:Any,allowed_books:Iterable[str]=DEFAULT_EXECUTION_BOOKS,max_age_minutes:float=DEFAULT_MAX_MARKET_AGE_MINUTES)->dict[str,Any]:
    allowed=set(allowed_books); home=str(event.get("home_team") or ""); away=str(event.get("away_team") or ""); selections={}
    for book in event.get("bookmakers") or []:
        key=str(book.get("key") or "")
        if key not in allowed or _book_freshness(book,as_of,max_age_minutes)!="VERIFIED_FRESH": continue
        specs=[("home_ml","h2h",home,None),("away_ml","h2h",away,None),("home_minus_1_5","spreads",home,-1.5),("away_plus_1_5","spreads",away,+1.5),("away_minus_1_5","spreads",away,-1.5),("home_plus_1_5","spreads",home,+1.5),("over","totals","Over",float(total_line)),("under","totals","Under",float(total_line))]
        for canonical,market,name,point in specs:
            candidate=_best(_market_outcomes(book,market),name,point)
            if candidate is None: continue
            current=selections.get(canonical)
            if current is None or float(candidate["price"])>float(current["price"]): selections[canonical]={**candidate,"bookmaker":key,"freshness":"VERIFIED_FRESH","last_update":book.get("last_update")}
    return {"schema":"pulsar-v14-execution-market-v1","captured_at":str(as_of),"total_line":float(total_line),"freshness_verified":bool(selections),"allowed_books":list(allowed),"selections":selections,"market_probability_used_as_feature":False,"note":"Best executable verified price; never used as a baseball-model feature."}
