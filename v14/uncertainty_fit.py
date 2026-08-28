from __future__ import annotations

"""Fit empirical calibration-aware decision bands by market/phase/probability bucket."""

from collections import defaultdict
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .tracking import _canonical_settled, _read_jsonl

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_uncertainty.json")
MIN_BUCKET_N=80
BUCKET_WIDTH=.10
Z95=1.96
MARKETS={"ML":"home_ml","RL_HOME_-1.5":"home_minus_1_5","RL_AWAY_-1.5":"away_minus_1_5","TOTAL_OVER":"over"}


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _outcome(row:dict[str,Any],market:str)->int|None:
    try: hs=int(row["home_score"]); aws=int(row["away_score"])
    except Exception: return None
    if market=="ML": return int(hs>aws)
    if market=="RL_HOME_-1.5": return int(hs-aws>=2)
    if market=="RL_AWAY_-1.5": return int(aws-hs>=2)
    if market=="TOTAL_OVER":
        line=_num(row.get("total_line"))
        if line is None or abs((hs+aws)-line)<1e-9: return None
        return int(hs+aws>line)
    return None


def _bucket(p:float)->str:
    lo=min(.9,max(0.0,math.floor(float(p)/BUCKET_WIDTH)*BUCKET_WIDTH)); return f"{lo:.1f}-{lo+BUCKET_WIDTH:.1f}"


def _wilson_half(rate:float,n:int,z:float=Z95)->float:
    if n<=0: return .20
    denom=1+z*z/n
    return z*math.sqrt(max(0.0,rate*(1-rate)/n+z*z/(4*n*n)))/denom


def _fit(items:list[tuple[float,int]])->dict[str,Any]:
    n=len(items)
    if not items: return {"n":0,"ready":False}
    mean_p=sum(p for p,_ in items)/n; rate=sum(y for _,y in items)/n; bias=rate-mean_p; sampling=_wilson_half(rate,n); half=min(.20,max(.025,abs(bias)+sampling))
    return {"n":n,"ready":n>=MIN_BUCKET_N,"mean_probability":mean_p,"observed_rate":rate,"calibration_bias":bias,"wilson_95_half_width":sampling,"empirical_half_width":half,"method":"|calibration bias| + Wilson 95% binomial half-width"}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); grouped=defaultdict(list)
    for row in settled:
        phase=str(row.get("phase") or "EARLY").upper(); probs=row.get("probabilities") or {}
        for market,key in MARKETS.items():
            p=_num(probs.get(key)); y=_outcome(row,market)
            if p is None or y is None: continue
            grouped[(market,phase,_bucket(p))].append((p,y)); grouped[(market,"ALL",_bucket(p))].append((p,y))
    cells={f"{m}:{phase}:{bucket}":_fit(items) for (m,phase,bucket),items in grouped.items()}
    return {
        "schema":"pulsar-v14-uncertainty-fit-v3",
        "model_generation":MODEL_GENERATION,
        "probability_policy_id":PROBABILITY_POLICY_ID,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "games":len(settled),
        "minimum_bucket_n":MIN_BUCKET_N,
        "bucket_width":BUCKET_WIDTH,
        "confidence_level":.95,
        "total_push_policy":"excluded from binary cells",
        "cells":cells,
        "role":"DECISION_SAFETY_ONLY",
        "note":"Empirical calibration decision bands bound to exact model generation and probability policy; not Bayesian credible intervals.",
    }


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    out=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); out=write(args.predictions,args.output); print(f"PULSAR_V14_UNCERTAINTY games={out['games']} cells={len(out['cells'])}")

if __name__=="__main__": main()
