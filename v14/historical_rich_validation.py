from __future__ import annotations

"""Audit the 1,801-game 2026 walk-forward replay without overstating its evidence.

This dataset can diagnose starter-identity / prior-IP and lineup-known coverage,
and compare the historical V9/V10 predictions on exactly the same games.  It
cannot validate V14 Statcast, pitch-mix, weather, defense or catcher features
because those feature values are not embedded in the replay rows.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

SOURCE = Path("data/mlb_backtest_2026.jsonl")
OUTPUT = Path("runtime/v14/v14_rich_historical_validation.json")


def _num(value: Any) -> float | None:
    try:
        out=float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _read(path: Path=SOURCE) -> list[dict[str,Any]]:
    rows=[]
    with path.open("r",encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row=json.loads(line)
                if isinstance(row,dict): rows.append(row)
    return rows


def _brier(rows:list[dict[str,Any]],key:str)->dict[str,Any]:
    vals=[]
    for row in rows:
        p=_num((row.get(key) or {}).get("p_home")); y=_num(row.get("y"))
        if p is None or y is None: continue
        vals.append((p-y)**2)
    return {"n":len(vals),"brier":sum(vals)/len(vals) if vals else None}


def _logloss(rows:list[dict[str,Any]],key:str)->dict[str,Any]:
    vals=[]
    for row in rows:
        p=_num((row.get(key) or {}).get("p_home")); y=_num(row.get("y"))
        if p is None or y is None: continue
        p=max(1e-9,min(1-1e-9,p)); vals.append(-(y*math.log(p)+(1-y)*math.log(1-p)))
    return {"n":len(vals),"logloss":sum(vals)/len(vals) if vals else None}


def _run_mae(rows:list[dict[str,Any]],key:str)->dict[str,Any]:
    team=[]; total=[]
    for row in rows:
        ph=_num((row.get(key) or {}).get("home_mu")); pa=_num((row.get(key) or {}).get("away_mu")); hs=_num(row.get("home_score")); aws=_num(row.get("away_score"))
        if None in {ph,pa,hs,aws}: continue
        team.extend((abs(hs-ph),abs(aws-pa))); total.append(abs((hs+aws)-(ph+pa)))
    return {"n":len(total),"team_mae":sum(team)/len(team) if team else None,"total_mae":sum(total)/len(total) if total else None}


def _coverage(rows:list[dict[str,Any]])->dict[str,Any]:
    n=len(rows); both_ids=both_prior=home_lineup=away_lineup=both_lineups=0
    statcast_keys=weather_keys=defense_keys=0
    for row in rows:
        starters=row.get("starters") or {}; lineup=row.get("lineup_known") or {}
        if starters.get("home_id") and starters.get("away_id"): both_ids+=1
        if (_num(starters.get("home_prior_ip")) or 0)>0 and (_num(starters.get("away_prior_ip")) or 0)>0: both_prior+=1
        h=bool(lineup.get("home")); a=bool(lineup.get("away")); home_lineup+=int(h); away_lineup+=int(a); both_lineups+=int(h and a)
        keys={str(k).lower() for k in row.keys()}
        statcast_keys+=int(any("statcast" in k or "xwoba" in k or "barrel" in k or "hard_hit" in k or "pitch_mix" in k for k in keys))
        weather_keys+=int(any("weather" in k or "temperature" in k or "wind" in k for k in keys))
        defense_keys+=int(any("defense" in k or "fielding" in k or "catcher" in k or "baserunning" in k for k in keys))
    def rate(x:int)->float: return x/n if n else 0.0
    return {"rows":n,"both_starter_ids":{"n":both_ids,"rate":rate(both_ids)},"both_starter_prior_ip_positive":{"n":both_prior,"rate":rate(both_prior)},"home_lineup_known":{"n":home_lineup,"rate":rate(home_lineup)},"away_lineup_known":{"n":away_lineup,"rate":rate(away_lineup)},"both_lineups_known":{"n":both_lineups,"rate":rate(both_lineups)},"rows_with_statcast_like_top_level_keys":statcast_keys,"rows_with_weather_like_top_level_keys":weather_keys,"rows_with_defense_like_top_level_keys":defense_keys}


def build(path:Path=SOURCE)->dict[str,Any]:
    rows=_read(path); coverage=_coverage(rows)
    v9={**_brier(rows,"v9"),**_logloss(rows,"v9"),**_run_mae(rows,"v9")}
    v10={**_brier(rows,"v10"),**_logloss(rows,"v10"),**_run_mae(rows,"v10")}
    limitations=[]
    if coverage["rows_with_statcast_like_top_level_keys"]==0: limitations.append("STATCAST_NOT_PRESENT")
    if coverage["rows_with_weather_like_top_level_keys"]==0: limitations.append("WEATHER_NOT_PRESENT")
    if coverage["rows_with_defense_like_top_level_keys"]==0: limitations.append("DEFENSE_CATCHER_BASERUNNING_NOT_PRESENT")
    return {"schema":"pulsar-v14-rich-historical-validation-v1","source":str(path),"role":"DIAGNOSTIC_ONLY","auto_activation":False,"rows":len(rows),"coverage":coverage,"historical_models":{"v9":v9,"v10":v10},"evidence":{"starter_identity":"AVAILABLE_DIAGNOSTIC" if coverage["both_starter_ids"]["n"] else "MISSING","starter_prior_ip":"AVAILABLE_DIAGNOSTIC" if coverage["both_starter_prior_ip_positive"]["n"] else "MISSING","lineup_known":"AVAILABLE_DIAGNOSTIC" if coverage["both_lineups_known"]["n"] else "MISSING","statcast":"NEEDS_RICH_PIT","weather":"NEEDS_RICH_PIT","defense_catcher_baserunning":"NEEDS_RICH_PIT"},"limitations":limitations,"claim":"This replay can diagnose only fields actually embedded in each pregame row; it cannot validate absent V14 advanced features.","native_live_confirmation_required":True}


def write(output:Path|str=OUTPUT)->dict[str,Any]:
    artifact=build(); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--output",default=str(OUTPUT)); args=parser.parse_args(); out=write(args.output); print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__": main()
