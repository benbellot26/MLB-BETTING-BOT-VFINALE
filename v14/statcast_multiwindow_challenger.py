from __future__ import annotations

"""Adaptive 14/30/45/60-day Statcast horizon challenger.

Overlapping windows are not naively averaged. For each entity, the challenger
selects the shortest PIT-safe window that reaches the same reliability sample
scale used by the champion shrinkage; otherwise it falls back to the longest
available window. This tests recency while preserving sample-size discipline.
"""

import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path
from typing import Any

from .statcast_shadow import HITTER_SHRINK_PA, LEAGUE, PITCHER_SHRINK_PA

EXPECTED_SCHEMA="pulsar-v14-statcast-id-priors-v2"
WINDOWS=(14,30,45,60)


def _num(value:Any)->float|None:
    try:x=float(value)
    except Exception:return None
    return x if math.isfinite(x) else None


def load(path:Path|str)->dict[str,Any]:
    p=Path(path)
    if not p.exists():return {}
    try:
        with gzip.open(p,"rt",encoding="utf-8") as fh:payload=json.load(fh)
    except Exception:return {}
    if not isinstance(payload,dict) or payload.get("schema")!=EXPECTED_SCHEMA or payload.get("point_in_time") is not True or payload.get("stable_id_only") is not True:return {}
    return payload


def _shrink(value:Any,pa:int,prior:float,k:float)->float:
    raw=_num(value);w=max(0,float(pa))/(max(0,float(pa))+k)
    return prior if raw is None else w*raw+(1-w)*prior


def select_entity(entity_id:Any,artifacts:dict[int,dict[str,Any]],*,kind:str)->dict[str,Any]:
    bucket="hitters" if kind=="hitter" else "pitchers";threshold=HITTER_SHRINK_PA if kind=="hitter" else PITCHER_SHRINK_PA;k=threshold;rows=[]
    for days in WINDOWS:
        artifact=artifacts.get(days) or {};row=(artifact.get(bucket) or {}).get(str(entity_id)) or {};pa=int(_num(row.get("pa")) or 0)
        if row:rows.append((days,pa,row))
    if not rows:return {"status":"UNAVAILABLE","entity_id":str(entity_id),"kind":kind}
    adequate=[item for item in rows if item[1]>=threshold];days,pa,row=(min(adequate,key=lambda x:x[0]) if adequate else max(rows,key=lambda x:x[0]))
    metrics={}
    for key in ("xwoba","hard_hit_rate","barrel_rate","k_minus_bb_rate"):
        metrics[key]=_shrink(row.get(key),pa,LEAGUE[key],k)
    if kind=="pitcher":metrics["avg_release_speed"]=_shrink(row.get("avg_release_speed"),pa,LEAGUE["avg_release_speed"],k)
    return {"status":"READY_SHADOW","entity_id":str(entity_id),"kind":kind,"selected_window_days":days,"pa":pa,"adequate_sample":pa>=threshold,"reliability":pa/(pa+k),"metrics":metrics,"selection_policy":"shortest window reaching shrinkage sample scale; otherwise longest available"}


def build_report(artifacts:dict[int,dict[str,Any]])->dict[str,Any]:
    valid={days:a for days,a in artifacts.items() if a};cutoffs={str(a.get("cutoff_day")) for a in valid.values() if a.get("cutoff_day")}
    base={"schema":"pulsar-v14-statcast-multiwindow-shadow-v1","role":"CHALLENGER_ONLY","champion_impact":False,"auto_activation":False,"market_probability_used_as_feature":False,"network_calls":0,"windows_available":sorted(valid),"same_cutoff":len(cutoffs)<=1,"cutoff_days":sorted(cutoffs)}
    if len(valid)<2 or len(cutoffs)>1:return {**base,"status":"COLLECTING","reason":"need >=2 PIT windows with identical cutoff"}
    hitters=set();pitchers=set()
    for artifact in valid.values():hitters.update((artifact.get("hitters") or {}).keys());pitchers.update((artifact.get("pitchers") or {}).keys())
    hc=Counter();pc=Counter();adequate_h=adequate_p=0
    for pid in hitters:
        row=select_entity(pid,valid,kind="hitter");hc[row.get("selected_window_days")]+=1;adequate_h+=int(row.get("adequate_sample") is True)
    for pid in pitchers:
        row=select_entity(pid,valid,kind="pitcher");pc[row.get("selected_window_days")]+=1;adequate_p+=int(row.get("adequate_sample") is True)
    return {**base,"status":"READY_SHADOW","hitters":len(hitters),"pitchers":len(pitchers),"hitter_selected_windows":{str(k):v for k,v in sorted(hc.items())},"pitcher_selected_windows":{str(k):v for k,v in sorted(pc.items())},"hitters_adequate_short_window":adequate_h,"pitchers_adequate_short_window":adequate_p,"promotion_policy":"must beat fixed 45d champion on preregistered prospective run/probability metrics before any generation change"}


def write(*,window14:Path|str,window30:Path|str,window45:Path|str,window60:Path|str,output:Path|str)->dict[str,Any]:
    paths={14:window14,30:window30,45:window45,60:window60};out=build_report({days:load(path) for days,path in paths.items()});p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return out


def main()->None:
    ap=argparse.ArgumentParser(description="Build adaptive multi-window Statcast shadow report");ap.add_argument("--window14",required=True);ap.add_argument("--window30",required=True);ap.add_argument("--window45",required=True);ap.add_argument("--window60",required=True);ap.add_argument("--output",required=True);args=ap.parse_args();print(json.dumps(write(window14=args.window14,window30=args.window30,window45=args.window45,window60=args.window60,output=args.output),sort_keys=True))

if __name__=="__main__":main()
