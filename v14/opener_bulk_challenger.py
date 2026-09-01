from __future__ import annotations

"""Opener/bulk-pitcher depth challenger.

The current starter-depth module intentionally floors expected starter innings at
3.0, which is safe for ordinary starters but cannot represent true opener games.
This challenger detects point-in-time opener-like usage separately and estimates
an opener/bulk/bullpen innings allocation. It does not guess a bulk-pitcher
identity: promotion requires that identity to be captured explicitly first.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID

PREDICTIONS=Path("data/v14_predictions.jsonl")
OUTPUT=Path("data/v14_opener_bulk_candidate.json")


def _num(value:Any)->float|None:
    try:x=float(value)
    except Exception:return None
    return x if math.isfinite(x) else None


def classify(starter:dict[str,Any]|None)->dict[str,Any]:
    row=starter if isinstance(starter,dict) else {};starts=int(max(0,_num(row.get("gamesStarted")) or 0));ip_start=_num(row.get("inningsPerStart"))
    if ip_start is None:
        total=_num(row.get("inningsPitched"));ip_start=(total/starts) if total is not None and starts>0 else None
    recent=[]
    for item in row.get("recent_starts") or []:
        if not isinstance(item,dict):continue
        value=_num(item.get("innings") or item.get("inningsPitched"))
        if value is not None and 0<=value<=9:recent.append(value)
    recent_mean=sum(recent[:5])/len(recent[:5]) if recent[:5] else None
    evidence=[x for x in (ip_start,recent_mean) if x is not None]
    if starts<2 or not evidence:return {"schema":"pulsar-v14-opener-bulk-challenger-v1","role":"CHALLENGER_ONLY","status":"COLLECTING","champion_impact":False,"auto_activation":False,"market_probability_used_as_feature":False,"reason":"insufficient starter-depth evidence"}
    raw=sum(evidence)/len(evidence);opener_like=raw<=3.25 or (ip_start is not None and ip_start<=3.0)
    if not opener_like:return {"schema":"pulsar-v14-opener-bulk-challenger-v1","role":"CHALLENGER_ONLY","status":"ORDINARY_STARTER","champion_impact":False,"auto_activation":False,"market_probability_used_as_feature":False,"season_starts":starts,"season_innings_per_start":ip_start,"recent_innings_mean":recent_mean}
    opener=max(.7,min(3.25,raw));remaining=max(0.0,9.0-opener);bulk=min(4.5,max(2.0,remaining*.62));bullpen=max(0.0,9.0-opener-bulk)
    bulk_identity=row.get("bulk_pitcher") or row.get("bulkPitcher")
    return {"schema":"pulsar-v14-opener-bulk-challenger-v1","role":"CHALLENGER_ONLY","status":"READY_SHADOW" if bulk_identity else "OPENER_DETECTED_BULK_IDENTITY_COLLECTING","champion_impact":False,"auto_activation":False,"market_probability_used_as_feature":False,"season_starts":starts,"season_innings_per_start":ip_start,"recent_innings_mean":recent_mean,"opener_like":True,"projected_innings":{"opener":opener,"bulk":bulk,"remaining_bullpen":bullpen},"bulk_pitcher_identity":bulk_identity,"bulk_pitcher_identity_required_for_promotion":True,"promotion_policy":"capture explicit probable bulk pitcher and validate prospectively before production use"}


def _read(path:Path|str)->list[dict[str,Any]]:
    p=Path(path)
    if not p.exists():return []
    out=[]
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:r=json.loads(line)
        except Exception:continue
        if isinstance(r,dict):out.append(r)
    return out


def build(path:Path|str=PREDICTIONS)->dict[str,Any]:
    candidates=[];rows=0
    for row in _read(path):
        if row.get("model_generation")!=MODEL_GENERATION or str(row.get("phase") or "").upper()!="FINAL":continue
        policy=row.get("probability_policy_id") or ((row.get("calibration") or {}).get("probability_policy_id"))
        if policy!=PROBABILITY_POLICY_ID:continue
        tf=row.get("training_features") or {};rows+=1
        for side in ("home","away"):
            result=classify(tf.get(f"{side}_starter") or {})
            if result.get("opener_like") is True:candidates.append({"game_pk":row.get("game_pk"),"side":side,"analyzed_at":row.get("analyzed_at"),**result})
    return {"schema":"pulsar-v14-opener-bulk-report-v1","generated_at":datetime.now(timezone.utc).isoformat(),"role":"CHALLENGER_ONLY","champion_impact":False,"auto_activation":False,"network_calls":0,"model_generation":MODEL_GENERATION,"final_rows_scanned":rows,"opener_candidates":len(candidates),"with_bulk_identity":sum(bool(x.get("bulk_pitcher_identity")) for x in candidates),"candidates":candidates,"status":"COLLECTING_BULK_IDENTITY" if any(not x.get("bulk_pitcher_identity") for x in candidates) else ("READY_SHADOW" if candidates else "NO_OPENER_EVIDENCE_YET")}


def write(*,predictions:Path|str=PREDICTIONS,output:Path|str=OUTPUT)->dict[str,Any]:
    out=build(predictions);p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return out


def main()->None:
    ap=argparse.ArgumentParser(description="Audit V14 opener/bulk usage in shadow");ap.add_argument("--predictions",default=str(PREDICTIONS));ap.add_argument("--output",default=str(OUTPUT));args=ap.parse_args();print(json.dumps(write(predictions=args.predictions,output=args.output),sort_keys=True))

if __name__=="__main__":main()
