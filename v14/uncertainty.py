from __future__ import annotations

"""Conservative empirical decision bands for Pulsar V14.

When enough settled observations exist, market×phase×probability-bucket bands
are loaded from the exact current model generation. Otherwise wide conservative
fallbacks remain. These are decision-safety bands, not Bayesian credible
intervals.
"""

import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

ARTIFACT=Path("data/v14_uncertainty.json")
BASE_HALF_WIDTH={"ML":.060,"RL_HOME_-1.5":.075,"RL_AWAY_-1.5":.075,"TOTAL_OVER":.085}
PAIR_MAP={"ML":("home_ml","away_ml"),"RL_HOME_-1.5":("home_minus_1_5","away_plus_1_5"),"RL_AWAY_-1.5":("away_minus_1_5","home_plus_1_5"),"TOTAL_OVER":("over","under")}
Z95=1.96


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _load(path:Path|str=ARTIFACT)->dict[str,Any]:
    target=Path(path)
    if not target.exists(): return {}
    try: row=json.loads(target.read_text(encoding="utf-8"))
    except Exception: return {}
    if not isinstance(row,dict) or row.get("schema") not in {"pulsar-v14-uncertainty-fit-v1","pulsar-v14-uncertainty-fit-v2"}: return {}
    if row.get("model_generation")!=MODEL_GENERATION: return {}
    return row


def _bucket(p:float)->str:
    lo=min(.9,max(0.0,math.floor(float(p)/.10)*.10)); return f"{lo:.1f}-{lo+.1:.1f}"


def _quality_penalty(data_quality:dict[str,Any]|None,*,starter_degraded:bool,market_fresh:bool|None)->float:
    q=data_quality or {}; penalty=0.0
    if starter_degraded: penalty+=.035
    if q.get("eligible") is False: penalty+=.040
    home=int(_num(q.get("home_lineup_count")) or 0); away=int(_num(q.get("away_lineup_count")) or 0)
    if min(home,away)<9: penalty+=.012
    if min(home,away)<5: penalty+=.010
    if market_fresh is False: penalty+=.015
    return min(.08,penalty)


def _empirical_half(market:str,phase:str,p:float,artifact:dict[str,Any])->tuple[float|None,dict[str,Any]]:
    cells=artifact.get("cells") or {}; bucket=_bucket(p)
    for scope in (str(phase or "ALL").upper(),"ALL"):
        cell=cells.get(f"{market}:{scope}:{bucket}") or {}
        if cell.get("ready") is True and _num(cell.get("empirical_half_width")) is not None:
            return float(cell["empirical_half_width"]),{"cell":f"{market}:{scope}:{bucket}","n":int(cell.get("n") or 0),"source":"empirical_95"}
    return None,{"cell":None,"n":0,"source":"fallback"}


def _accepted_fallback_half(p:float,meta:dict[str,Any])->tuple[float,int]:
    holdout=meta.get("holdout") or {}; n=int(holdout.get("n") or 0)
    if n<=0: n=min(int(meta.get("n") or 0),80)
    n=max(25,n); ece=abs(_num(holdout.get("ece")) or 0.0); sampling=Z95*math.sqrt(max(1e-8,p*(1-p))/n)
    return max(.025,sampling+.5*ece),n


def intervals(probabilities:dict[str,Any],calibration:dict[str,Any]|None,*,data_quality:dict[str,Any]|None=None,starter_degraded:bool=False,market_fresh:bool|None=None,artifact:dict[str,Any]|None=None)->dict[str,Any]:
    cal=calibration or {}; cal_markets=cal.get("markets") or {}; phase=str(cal.get("phase") or "ALL").upper(); empirical=_load() if artifact is None else artifact
    if empirical and empirical.get("model_generation")!=MODEL_GENERATION: empirical={}
    penalty=_quality_penalty(data_quality,starter_degraded=starter_degraded,market_fresh=market_fresh); selections={}
    for market,(left,right) in PAIR_MAP.items():
        p=_num(probabilities.get(left))
        if p is None: continue
        meta=cal_markets.get(market) or {}; n=int(meta.get("n") or 0); active=meta.get("active") is True; accepted=meta.get("accepted") is True or active; empirical_half,evidence=_empirical_half(market,phase,p,empirical)
        evidence_n=int(evidence["n"])
        if empirical_half is not None: half=max(.020,empirical_half)
        elif accepted and n>0:
            half,evidence_n=_accepted_fallback_half(p,meta); evidence={"cell":None,"n":evidence_n,"source":"accepted_calibration_holdout_95"}
        else: half=BASE_HALF_WIDTH[market]
        half=min(.18,half+penalty); lo,hi=max(0.0,p-half),min(1.0,p+half)
        selections[left]={"probability":p,"lower":lo,"upper":hi,"half_width_pp":100*half,"calibration_active":active,"calibration_accepted":accepted,"evidence_n":max(n,evidence_n),"uncertainty_source":evidence["source"],"uncertainty_cell":evidence["cell"]}
        rp=1-p; selections[right]={**selections[left],"probability":rp,"lower":1-hi,"upper":1-lo}
    return {"schema":"pulsar-v14-probability-uncertainty-v4","method":"exact-generation empirical 95% calibration-aware decision band with conservative fallback","phase":phase,"starter_degraded":bool(starter_degraded),"market_freshness_verified":market_fresh,"quality_penalty_pp":100*penalty,"selections":selections,"note":"Decision-safety intervals; not exact Bayesian credible intervals. Empirical artifacts require exact MODEL_GENERATION."}
