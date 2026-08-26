from __future__ import annotations

"""Learn market-specific sharp-book reliability weights from paired outcomes.

The candidate artifact is never consumed directly by production. A deliberate
review must copy a validated version to `v14_sharp_book_weights.json` with
`validated=true` after sufficient chronological OOS evidence.
"""

from collections import defaultdict
import argparse
import json
import math
from pathlib import Path
from typing import Any

from .sharp_market import DEFAULT_SHARP_BOOK_WEIGHTS
from .tracking import _canonical_settled, _read_jsonl

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_sharp_book_weights_candidate.json")
MIN_BOOK_N=150
MIN_MARKET_N=400
MARKETS={"ML":("home_ml",lambda h,a,l:int(h>a)),"RL_HOME_-1.5":("home_minus_1_5",lambda h,a,l:int(h-a>=2)),"RL_AWAY_-1.5":("away_minus_1_5",lambda h,a,l:int(a-h>=2)),"TOTAL_OVER":("over",lambda h,a,l:int(l is not None and h+a>l))}


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _book_rows(rows:list[dict[str,Any]],market:str)->dict[str,list[tuple[float,int]]]:
    selection,outcome_fn=MARKETS[market]; out=defaultdict(list)
    for row in rows:
        try: hs=int(row["home_score"]); aws=int(row["away_score"])
        except Exception: continue
        y=outcome_fn(hs,aws,_num(row.get("total_line"))); contributors=((((row.get("sharp_market") or {}).get("selections") or {}).get(selection) or {}).get("contributors") or [])
        for contributor in contributors:
            book=str(contributor.get("bookmaker") or ""); p=_num(contributor.get("fair_probability"))
            if book and p is not None and 0<p<1: out[book].append((p,y))
    return dict(out)


def _metrics(items:list[tuple[float,int]])->dict[str,Any]:
    if not items: return {"n":0,"brier":None,"log_loss":None}
    eps=1e-12; return {"n":len(items),"brier":sum((p-y)**2 for p,y in items)/len(items),"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in items)/len(items)}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); result={"schema":"pulsar-v14-sharp-weights-candidate-v1","role":"CHALLENGER_ONLY","validated":False,"auto_activation":False,"games":len(settled),"markets":{},"global":DEFAULT_SHARP_BOOK_WEIGHTS}
    for market in MARKETS:
        by_book=_book_rows(settled,market); metrics={book:_metrics(items) for book,items in by_book.items()}; eligible={book:m for book,m in metrics.items() if int(m["n"])>=MIN_BOOK_N}
        if sum(int(m["n"]) for m in eligible.values())<MIN_MARKET_N or len(eligible)<2:
            result["markets"][market]={"status":"COLLECTING","book_metrics":metrics,"weights":{},"minimum_book_n":MIN_BOOK_N,"minimum_market_n":MIN_MARKET_N}; continue
        # Reliability is inverse proper-score error with strong shrinkage toward
        # current conservative defaults. Absolute scale is irrelevant; normalize
        # the best book to 1.0 and bound weaker contributors away from zero.
        raw={}
        for book,m in eligible.items():
            prior=DEFAULT_SHARP_BOOK_WEIGHTS.get(book,.60); reliability=1/max(.12,float(m["brier"])); raw[book]=.70*prior+.30*(reliability/4.0)
        peak=max(raw.values()); weights={book:max(.35,min(1.0,value/peak)) for book,value in raw.items()}
        result["markets"][market]={"status":"PROMOTION_REVIEW","book_metrics":metrics,"weights":weights,"minimum_book_n":MIN_BOOK_N,"method":"70% conservative prior + 30% inverse-Brier reliability, normalized","note":"Requires chronological holdout review before copying to validated production weight artifact."}
    return result


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    out=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); print(f"PULSAR_V14_SHARP_WEIGHTS games={write(args.predictions,args.output).get('games')}")
