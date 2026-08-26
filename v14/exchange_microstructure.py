from __future__ import annotations

"""Exchange order-book normalization for V14 benchmark/execution research.

This module deliberately does not feed baseball probabilities. It converts
Betfair/Matchbook back-lay books into a common evidence schema with executable
prices, available depth, traded volume and explicit commission metadata.
Live acquisition remains disabled unless account/API credentials are supplied
through the runtime secret store.
"""

import math
import os
from typing import Any

ROLE = "BENCHMARK_ONLY"


def _num(value: Any) -> float | None:
    try:
        out=float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _level(price: Any, size: Any) -> dict[str,float] | None:
    p=_num(price);s=_num(size)
    if p is None or s is None or p<=1.0 or s<0:return None
    return {"price":p,"available":s}


def _runner(name: str|None, runner_id: Any, backs: list[dict[str,float]], lays: list[dict[str,float]], *, traded_volume: float|None=None, commission_rate: float|None=None) -> dict[str,Any]:
    backs=sorted(backs,key=lambda x:x["price"],reverse=True);lays=sorted(lays,key=lambda x:x["price"])
    best_back=backs[0] if backs else None;best_lay=lays[0] if lays else None
    spread=None;mid_probability=None
    if best_back and best_lay and best_lay["price"]>=best_back["price"]:
        mid=(best_back["price"]+best_lay["price"])/2
        spread=(best_lay["price"]-best_back["price"])/mid*10_000 if mid>0 else None
        mid_probability=(1/best_back["price"]+1/best_lay["price"])/2
    adjusted_back=None
    if best_back and commission_rate is not None and 0<=commission_rate<1:
        adjusted_back=1+(best_back["price"]-1)*(1-commission_rate)
    return {
        "runner_id":str(runner_id or ""),"name":name,"best_back":best_back,"best_lay":best_lay,
        "back_levels":backs,"lay_levels":lays,"back_depth":sum(x["available"] for x in backs),"lay_depth":sum(x["available"] for x in lays),
        "spread_bps":spread,"raw_mid_implied_probability":mid_probability,"traded_volume":traded_volume,
        "commission_rate":commission_rate,"commission_adjusted_back_price":adjusted_back,
    }


def normalize_matchbook_market(payload: dict[str,Any]|None, *, commission_rate: float|None=None) -> dict[str,Any]:
    data=payload if isinstance(payload,dict) else {};markets=data.get("markets") or []
    market=markets[0] if markets and isinstance(markets[0],dict) else data
    rows=[]
    for raw in market.get("runners") or []:
        backs=[];lays=[]
        for price in raw.get("prices") or []:
            side=str(price.get("side") or "").lower();level=_level(price.get("decimal-odds",price.get("odds")),price.get("available-amount"))
            if level is None:continue
            if side=="back":backs.append(level)
            elif side=="lay":lays.append(level)
        rows.append(_runner(raw.get("name"),raw.get("id"),backs,lays,traded_volume=_num(raw.get("volume")),commission_rate=commission_rate))
    complete=sum(bool(r["best_back"] and r["best_lay"]) for r in rows)
    return {"schema":"pulsar-v14-exchange-book-v1","role":ROLE,"provider":"MATCHBOOK","status":"READY_BENCHMARK" if complete>=2 else "COLLECTING","benchmark_only":True,"champion_impact":False,"market_probability_used_as_feature":False,"market_id":str(market.get("id") or market.get("market-id") or ""),"market_name":market.get("name"),"runners":rows,"complete_two_sided_runners":complete,"price_depth_observed":max([len(r["back_levels"])+len(r["lay_levels"]) for r in rows] or [0]),"commission_rate":commission_rate,"source_contract":"Matchbook back-lay prices with available-amount; expanded depth preferred"}


def normalize_betfair_market_book(payload: dict[str,Any]|None, *, selection_names: dict[str,str]|None=None, commission_rate: float|None=None) -> dict[str,Any]:
    data=payload if isinstance(payload,dict) else {};names=selection_names or {};rows=[]
    for raw in data.get("runners") or []:
        ex=raw.get("ex") or {};backs=[];lays=[]
        for price in ex.get("availableToBack") or []:
            level=_level(price.get("price"),price.get("size"));
            if level:backs.append(level)
        for price in ex.get("availableToLay") or []:
            level=_level(price.get("price"),price.get("size"));
            if level:lays.append(level)
        selection=str(raw.get("selectionId") or "")
        rows.append(_runner(names.get(selection),selection,backs,lays,traded_volume=_num(raw.get("totalMatched")),commission_rate=commission_rate))
    complete=sum(bool(r["best_back"] and r["best_lay"]) for r in rows)
    return {"schema":"pulsar-v14-exchange-book-v1","role":ROLE,"provider":"BETFAIR","status":"READY_BENCHMARK" if complete>=2 and data.get("isMarketDataDelayed") is not True else ("DELAYED_RESEARCH" if complete>=2 else "COLLECTING"),"benchmark_only":True,"champion_impact":False,"market_probability_used_as_feature":False,"market_id":str(data.get("marketId") or ""),"market_status":data.get("status"),"market_data_delayed":data.get("isMarketDataDelayed"),"total_matched":_num(data.get("totalMatched")),"runners":rows,"complete_two_sided_runners":complete,"commission_rate":commission_rate,"source_contract":"Betfair MarketBook EX_BEST_OFFERS/EX_ALL_OFFERS plus matched volume"}


def credential_status(environ: dict[str,str]|None=None) -> dict[str,Any]:
    env=os.environ if environ is None else environ
    matchbook=bool(env.get("MATCHBOOK_SESSION_TOKEN"))
    betfair=bool(env.get("BETFAIR_APP_KEY") and env.get("BETFAIR_SESSION_TOKEN"))
    return {"schema":"pulsar-v14-exchange-credentials-v1","matchbook_ready":matchbook,"betfair_ready":betfair,"live_acquisition_ready":matchbook or betfair,"required_secrets":{"matchbook":["MATCHBOOK_SESSION_TOKEN"],"betfair":["BETFAIR_APP_KEY","BETFAIR_SESSION_TOKEN"]},"credentials_must_not_be_committed":True}
