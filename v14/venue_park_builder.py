from __future__ import annotations

"""Build the V14 venue-keyed park-factor shadow artifact.

The builder does not scrape current-season results. It transforms the existing
prior-season Savant store into a venue-ID contract and requires the source window
to end exactly one season before the target season. Source promotion eligibility
is propagated rather than upgraded by the transformation.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

SOURCE=Path("data/v137_park_factors.json")
OUTPUT=Path("data/v14_venue_park_factors.json")
EXPECTED_SOURCE_SCHEMA="v13-7-prior-park-factors-store-v5"


def _key(row:dict[str,Any])->str:
    return str(row.get("venue_id") or "") or str(row.get("venue") or "")


def _factor(row:dict[str,Any])->float|None:
    raw=row.get("runs_index")
    if raw is None: raw=row.get("park_factor_index")
    try: value=float(raw)/100.0
    except Exception: return None
    return value if .75<=value<=1.35 else None


def build(source:dict[str,Any],*,target_season:int)->dict[str,Any]:
    season=int(target_season)
    if source.get("schema")!=EXPECTED_SOURCE_SCHEMA: raise ValueError("unexpected source park schema")
    sides=((source.get("seasons") or {}).get(str(season)) or {})
    all_block=sides.get("ALL") or {}
    rows=list(all_block.get("rows") or [])
    source_end=all_block.get("source_window_end_season")
    if source_end is None or int(source_end)!=season-1: raise ValueError("park source window is not strictly previous-season")
    by_side={}
    for side in ("L","R"):
        by_side[side]={_key(row):row for row in ((sides.get(side) or {}).get("rows") or []) if _key(row)}
    venues={}
    for row in rows:
        key=_key(row); factor=_factor(row)
        if not key or factor is None: continue
        handedness={}
        for side in ("L","R"):
            side_row=by_side[side].get(key) or {}; side_factor=_factor(side_row)
            if side_factor is not None: handedness[side]={"factor":side_factor,"runs_index":side_row.get("runs_index"),"park_factor_index":side_row.get("park_factor_index")}
        venues[key]={"venue_id":str(row.get("venue_id")) if row.get("venue_id") is not None else None,"venue_name":row.get("venue"),"factor":factor,"handedness":handedness,"components":{"runs_index":row.get("runs_index"),"park_factor_index":row.get("park_factor_index"),"hr_index":row.get("hr_index"),"hard_hit_index":row.get("hard_hit_index"),"woba_contact_index":row.get("woba_contact_index"),"xwoba_contact_index":row.get("xwoba_contact_index")},"source_method":row.get("source_method"),"promotion_eligible":bool(all_block.get("promotion_eligible") and source.get("promotion_eligible"))}
        name=str(row.get("venue") or "")
        if name and name not in venues: venues[name]=venues[key]
    return {"schema":"pulsar-v14-venue-park-artifact-v1","point_in_time":True,"target_season":season,"cutoff_day":f"{season-1}-12-31","generated_at":datetime.now(timezone.utc).isoformat(),"source_path":str(SOURCE),"source_schema":EXPECTED_SOURCE_SCHEMA,"source_window_end_season":season-1,"source_window_years":all_block.get("source_window_years"),"provider":all_block.get("provider") or "Baseball Savant Statcast Park Factors","promotion_eligible":bool(all_block.get("promotion_eligible") and source.get("promotion_eligible")),"transformation_only":True,"venues":venues}


def build_file(*,source_path:Path|str=SOURCE,output_path:Path|str=OUTPUT,target_season:int)->dict[str,Any]:
    source=json.loads(Path(source_path).read_text(encoding="utf-8")); artifact=build(source,target_season=target_season); target=Path(output_path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--target-season",type=int,required=True); parser.add_argument("--source",default=str(SOURCE)); parser.add_argument("--output",default=str(OUTPUT)); args=parser.parse_args(); out=build_file(source_path=args.source,output_path=args.output,target_season=args.target_season); print(f"PULSAR_V14_VENUE_PARK venues={len(out['venues'])} target={out['target_season']} promotion_eligible={out['promotion_eligible']}")


if __name__=="__main__": main()
