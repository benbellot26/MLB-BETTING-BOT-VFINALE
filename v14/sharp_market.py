from __future__ import annotations

"""Sharp-market consensus separated from execution/display prices.

Weights are market-specific and can be supplied by a validated research
artifact. Unadjusted exchange back-price proxies are intentionally discounted
until commission, liquidity and lay-side information are available. Consensus
uncertainty and per-book contributors are persisted so weights can be learned
with strict OOS evidence rather than hand-picked forever.
"""

import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from .market_lines import DEFAULT_MAX_MARKET_AGE_MINUTES, _book_freshness, _market_outcomes, _num

WEIGHTS_ARTIFACT=Path("data/v14_sharp_book_weights.json")
DEFAULT_SHARP_BOOK_WEIGHTS={"pinnacle":1.00,"betfair_ex_eu":0.55,"matchbook":0.55,"betonlineag":0.65}
EXCHANGE_BOOKS={"betfair_ex_eu","matchbook"}


def proportional_devig(a:float,b:float)->tuple[float,float]:
    ia,ib=1/float(a),1/float(b); s=ia+ib
    if not math.isfinite(s) or s<=0: raise ValueError("invalid two-way prices")
    return ia/s,ib/s


def power_devig(a:float,b:float)->tuple[float,float]:
    q1,q2=1/float(a),1/float(b)
    if min(q1,q2)<=0: raise ValueError("invalid prices")
    lo,hi=.05,10.0
    for _ in range(80):
        mid=(lo+hi)/2
        if q1**mid+q2**mid>1: lo=mid
        else: hi=mid
    k=(lo+hi)/2; p1,p2=q1**k,q2**k; s=p1+p2
    return p1/s,p2/s


def additive_devig(a:float,b:float)->tuple[float,float]:
    q1,q2=1/float(a),1/float(b); margin=q1+q2-1; p1=q1-margin/2; p2=q2-margin/2
    if min(p1,p2)<=0: return proportional_devig(a,b)
    s=p1+p2; return p1/s,p2/s


def devig_candidates(a:float,b:float)->dict[str,tuple[float,float]]:
    return {"proportional":proportional_devig(a,b),"power":power_devig(a,b),"additive":additive_devig(a,b)}


def _fair_pair(a:float,b:float)->tuple[float,float,dict[str,Any]]:
    methods=devig_candidates(a,b); left=[v[0] for v in methods.values()]; p1=median(left); p2=1-p1
    return p1,p2,{"methods":list(methods),"estimates":methods,"method_spread_pp":100*(max(left)-min(left))}


def _load_weights(path:Path|str=WEIGHTS_ARTIFACT)->dict[str,Any]:
    target=Path(path)
    if not target.exists(): return {"status":"DEFAULT","global":DEFAULT_SHARP_BOOK_WEIGHTS,"markets":{}}
    try: payload=json.loads(target.read_text(encoding="utf-8"))
    except Exception: return {"status":"DEFAULT","global":DEFAULT_SHARP_BOOK_WEIGHTS,"markets":{}}
    if not isinstance(payload,dict) or payload.get("schema") not in {"pulsar-v14-sharp-weights-v1","pulsar-v14-sharp-weights-v2"} or payload.get("validated") is not True:
        return {"status":"DEFAULT","global":DEFAULT_SHARP_BOOK_WEIGHTS,"markets":{}}
    return payload


def _weight(book:str,market:str,artifact:dict[str,Any])->float|None:
    scoped=(artifact.get("markets") or {}).get(market) or {}; raw=scoped.get(book)
    if raw is None: raw=(artifact.get("global") or DEFAULT_SHARP_BOOK_WEIGHTS).get(book)
    try: out=float(raw)
    except Exception: return None
    return out if math.isfinite(out) and out>0 else None


def _consensus(rows:list[tuple[float,float,str,str]])->dict[str,Any]|None:
    if not rows: return None
    probs=[p for p,_w,_b,_t in rows]; med=median(probs); bounded=[(max(med-.08,min(med+.08,p)),w,b,t,p) for p,w,b,t in rows]; total=sum(w for _p,w,_b,_t,_raw in bounded)
    mean=sum(p*w for p,w,_b,_t,_raw in bounded)/max(1e-12,total); variance=sum(w*(p-mean)**2 for p,w,_b,_t,_raw in bounded)/max(1e-12,total)
    contributors=[{"bookmaker":b,"source_type":t,"fair_probability":raw,"winsorized_probability":p,"weight":w,"proxy_discounted":t=="EXCHANGE_PROXY"} for p,w,b,t,raw in bounded]
    return {"fair_probability":mean,"source_count":len(rows),"sportsbook_source_count":sum(t=="SPORTSBOOK" for _p,_w,_b,t in rows),"exchange_proxy_source_count":sum(t=="EXCHANGE_PROXY" for _p,_w,_b,t in rows),"books":[b for _p,_w,b,_t in rows],"source_types":[t for _p,_w,_b,t in rows],"contributors":contributors,"dispersion_pp":100*math.sqrt(max(0,variance)),"range_pp":100*(max(probs)-min(probs)) if len(probs)>1 else 0.0,"consensus_method":"weighted winsorized cross-book fair probability"}


def _price_pair(outcomes:list[dict[str,Any]],name_a:str,name_b:str,*,point_a:float|None=None,point_b:float|None=None)->tuple[float,float]|None:
    a=b=None
    for row in outcomes:
        name=str(row.get("name") or ""); point=_num(row.get("point"))
        if name==name_a and (point_a is None or point==point_a): a=_num(row.get("price"))
        if name==name_b and (point_b is None or point==point_b): b=_num(row.get("price"))
    return (float(a),float(b)) if a is not None and b is not None and a>1 and b>1 else None


def sharp_consensus(event:dict[str,Any],*,total_line:float,as_of:Any,max_age_minutes:float=DEFAULT_MAX_MARKET_AGE_MINUTES,weights_artifact:dict[str,Any]|None=None)->dict[str,Any]:
    home,away=str(event.get("home_team") or ""),str(event.get("away_team") or ""); artifact=_load_weights() if weights_artifact is None else weights_artifact
    accum={"home_ml":[],"home_minus_1_5":[],"away_minus_1_5":[],"over":[]}; book_rows=[]; devig_meta=[]
    for book in event.get("bookmakers") or []:
        key=str(book.get("key") or ""); freshness=_book_freshness(book,as_of,max_age_minutes)
        if freshness!="VERIFIED_FRESH": continue
        source_type="EXCHANGE_PROXY" if key in EXCHANGE_BOOKS else "SPORTSBOOK"; used=[]
        specs=[("ML","home_ml","h2h",home,away,None,None),("RL_HOME_-1.5","home_minus_1_5","spreads",home,away,-1.5,+1.5),("RL_AWAY_-1.5","away_minus_1_5","spreads",away,home,-1.5,+1.5)]
        for market,out_key,market_key,a_name,b_name,pa,pb in specs:
            weight=_weight(key,market,artifact)
            if weight is None: continue
            pair=_price_pair(_market_outcomes(book,market_key),a_name,b_name,point_a=pa,point_b=pb)
            if pair:
                p,_q,meta=_fair_pair(*pair); accum[out_key].append((p,weight,key,source_type)); used.append(market); devig_meta.append({"bookmaker":key,"market":market,"method_spread_pp":meta["method_spread_pp"]})
        weight=_weight(key,"TOTAL_OVER",artifact); totals=[r for r in _market_outcomes(book,"totals") if _num(r.get("point"))==float(total_line)]; pair=_price_pair(totals,"Over","Under")
        if pair and weight is not None:
            p,_q,meta=_fair_pair(*pair); accum["over"].append((p,weight,key,source_type)); used.append("TOTAL_OVER"); devig_meta.append({"bookmaker":key,"market":"TOTAL_OVER","method_spread_pp":meta["method_spread_pp"]})
        if used: book_rows.append({"bookmaker":key,"source_type":source_type,"freshness":freshness,"markets":used,"exchange_commission_adjusted":False if source_type=="EXCHANGE_PROXY" else None,"default_proxy_weight":DEFAULT_SHARP_BOOK_WEIGHTS.get(key) if source_type=="EXCHANGE_PROXY" else None})
    selections={}
    for key,rows in accum.items():
        row=_consensus(rows)
        if row is not None: selections[key]=row
    for left,right in (("home_ml","away_ml"),("home_minus_1_5","away_plus_1_5"),("away_minus_1_5","home_plus_1_5"),("over","under")):
        if left in selections:
            base=selections[left]; contributors=[{**c,"fair_probability":1-float(c["fair_probability"]),"winsorized_probability":1-float(c["winsorized_probability"])} for c in base.get("contributors") or []]; selections[right]={**base,"fair_probability":1-float(base["fair_probability"]),"contributors":contributors}
    required={"home_ml","away_ml","over","under"}; actionable=required<=set(selections) and bool(book_rows)
    return {"schema":"pulsar-v14-sharp-consensus-v3","market_probability_used_as_feature":False,"benchmark_only":True,"actionable":actionable,"freshness_verified":bool(book_rows),"total_line":float(total_line),"selections":selections,"books":book_rows,"weights_status":artifact.get("status") or ("VALIDATED" if artifact.get("validated") else "DEFAULT"),"devig_methods":["proportional","power","additive"],"devig_method_diagnostics":devig_meta,"exchange_note":"Exchange sources are downweighted proxies unless commission/liquidity/lay fields become available and are validated OOS."}
