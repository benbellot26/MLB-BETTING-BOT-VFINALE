from __future__ import annotations

"""Learn market-specific sharp-book reliability weights with strict OOS proof.

Weights are learned on the older 80% of canonical settled games and evaluated
only on the newest 20%. The candidate never auto-activates. Integer-total pushes
are excluded from binary scoring. A promotion review is emitted only when the
candidate beats the current conservative weights on paired holdout proper scores.
"""

from collections import defaultdict
import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from .sharp_market import DEFAULT_SHARP_BOOK_WEIGHTS
from .tracking import _canonical_settled, _read_jsonl

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_sharp_book_weights_candidate.json")
MIN_MARKET_N=400
MIN_TRAIN_BOOK_N=120
MIN_HOLDOUT_N=80
HOLDOUT_FRACTION=.20
MARKETS={"ML":"home_ml","RL_HOME_-1.5":"home_minus_1_5","RL_AWAY_-1.5":"away_minus_1_5","TOTAL_OVER":"over"}


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _outcome(row:dict[str,Any],market:str)->int|None:
    try: h=int(row["home_score"]); a=int(row["away_score"])
    except Exception: return None
    if market=="ML": return int(h>a)
    if market=="RL_HOME_-1.5": return int(h-a>=2)
    if market=="RL_AWAY_-1.5": return int(a-h>=2)
    if market=="TOTAL_OVER":
        line=_num(row.get("total_line"))
        if line is None or abs((h+a)-line)<1e-9: return None
        return int(h+a>line)
    return None


def _contributors(row:dict[str,Any],market:str)->dict[str,float]:
    selection=MARKETS[market]; block=((((row.get("sharp_market") or {}).get("selections") or {}).get(selection) or {}).get("contributors") or []); out={}
    for c in block:
        book=str(c.get("bookmaker") or ""); p=_num(c.get("fair_probability"))
        if book and p is not None and 0<p<1: out[book]=p
    return out


def _book_metrics(rows:list[dict[str,Any]],market:str)->dict[str,dict[str,Any]]:
    by_book=defaultdict(list)
    for row in rows:
        y=_outcome(row,market)
        if y is None: continue
        for book,p in _contributors(row,market).items(): by_book[book].append((p,y))
    return {book:_metrics(items) for book,items in by_book.items()}


def _metrics(items:list[tuple[float,int]])->dict[str,Any]:
    if not items: return {"n":0,"brier":None,"log_loss":None}
    eps=1e-12
    return {"n":len(items),"brier":sum((p-y)**2 for p,y in items)/len(items),"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in items)/len(items)}


def _learn_weights(rows:list[dict[str,Any]],market:str)->tuple[dict[str,float],dict[str,dict[str,Any]]]:
    metrics=_book_metrics(rows,market); eligible={b:m for b,m in metrics.items() if int(m.get("n") or 0)>=MIN_TRAIN_BOOK_N and m.get("brier") is not None}
    if len(eligible)<2: return {},metrics
    raw={}
    for book,m in eligible.items():
        prior=DEFAULT_SHARP_BOOK_WEIGHTS.get(book,.50); reliability=1/max(.12,float(m["brier"])); raw[book]=.80*prior+.20*(reliability/4.0)
    peak=max(raw.values()); return {b:max(.25,min(1.0,v/peak)) for b,v in raw.items()},metrics


def _consensus(contributors:dict[str,float],weights:dict[str,float])->float|None:
    rows=[(p,weights.get(book)) for book,p in contributors.items() if weights.get(book) is not None and weights.get(book)>0]
    if not rows: return None
    med=median(p for p,_w in rows); bounded=[(max(med-.08,min(med+.08,p)),w) for p,w in rows]; total=sum(w for _p,w in bounded)
    return sum(p*w for p,w in bounded)/total if total>0 else None


def _paired_holdout(rows:list[dict[str,Any]],market:str,candidate:dict[str,float])->dict[str,Any]:
    diffs_b=[]; diffs_l=[]; candidate_items=[]; default_items=[]; eps=1e-12
    for row in rows:
        y=_outcome(row,market)
        if y is None: continue
        contributors=_contributors(row,market); cp=_consensus(contributors,candidate); dp=_consensus(contributors,DEFAULT_SHARP_BOOK_WEIGHTS)
        if cp is None or dp is None: continue
        candidate_items.append((cp,y)); default_items.append((dp,y)); diffs_b.append((dp-y)**2-(cp-y)**2)
        cl=-(y*math.log(max(eps,min(1-eps,cp)))+(1-y)*math.log(max(eps,min(1-eps,1-cp)))); dl=-(y*math.log(max(eps,min(1-eps,dp)))+(1-y)*math.log(max(eps,min(1-eps,1-dp)))); diffs_l.append(dl-cl)
    def ci(values:list[float])->dict[str,Any]:
        if not values: return {"n":0,"mean":None,"ci95_lower":None,"ci95_upper":None}
        mean=sum(values)/len(values)
        if len(values)<2: return {"n":len(values),"mean":mean,"ci95_lower":None,"ci95_upper":None}
        var=sum((x-mean)**2 for x in values)/(len(values)-1); se=math.sqrt(var/len(values)); return {"n":len(values),"mean":mean,"ci95_lower":mean-1.96*se,"ci95_upper":mean+1.96*se}
    bg=ci(diffs_b); lg=ci(diffs_l)
    return {"paired_n":len(candidate_items),"candidate":_metrics(candidate_items),"default":_metrics(default_items),"brier_gain":bg["mean"],"brier_gain_ci95_lower":bg["ci95_lower"],"brier_gain_ci95_upper":bg["ci95_upper"],"logloss_gain":lg["mean"],"logloss_gain_ci95_lower":lg["ci95_lower"],"logloss_gain_ci95_upper":lg["ci95_upper"]}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); result={"schema":"pulsar-v14-sharp-weights-candidate-v2","role":"CHALLENGER_ONLY","validated":False,"auto_activation":False,"games":len(settled),"chronological_holdout":True,"markets":{},"global":DEFAULT_SHARP_BOOK_WEIGHTS}
    for market in MARKETS:
        usable=[r for r in settled if _outcome(r,market) is not None and _contributors(r,market)]
        n=len(usable); holdout_n=max(MIN_HOLDOUT_N,int(round(n*HOLDOUT_FRACTION))); train_n=n-holdout_n
        if n<MIN_MARKET_N or train_n<250 or holdout_n<MIN_HOLDOUT_N:
            result["markets"][market]={"status":"COLLECTING","n":n,"minimum_market_n":MIN_MARKET_N,"weights":{}}; continue
        train,holdout=usable[:train_n],usable[train_n:]; weights,book_metrics=_learn_weights(train,market)
        if not weights:
            result["markets"][market]={"status":"COLLECTING","n":n,"train_n":train_n,"holdout_n":holdout_n,"book_metrics_train":book_metrics,"weights":{},"reason":"fewer_than_two_books_with_train_evidence"}; continue
        evaluation=_paired_holdout(holdout,market,weights); b_lower=evaluation.get("brier_gain_ci95_lower"); l_lower=evaluation.get("logloss_gain_ci95_lower"); promotion=bool(int(evaluation.get("paired_n") or 0)>=MIN_HOLDOUT_N and b_lower is not None and float(b_lower)>0 and l_lower is not None and float(l_lower)>=-.001)
        result["markets"][market]={"status":"PROMOTION_REVIEW" if promotion else "REJECTED_OOS","n":n,"train_n":train_n,"holdout_n":holdout_n,"weights":weights,"book_metrics_train":book_metrics,"holdout":evaluation,"method":"80% prior-shrunk inverse-Brier book reliability learned on chronological train; paired newest-20% holdout","promotion_gate":"paired Brier gain CI95 lower >0 and LogLoss CI95 lower >= -0.001","pushes_excluded":market=="TOTAL_OVER"}
    return result


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    out=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); print(f"PULSAR_V14_SHARP_WEIGHTS games={write(args.predictions,args.output).get('games')}")
