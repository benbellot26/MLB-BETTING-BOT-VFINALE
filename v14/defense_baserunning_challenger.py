from __future__ import annotations

"""Defense, catcher and baserunning shadow contract.

Expected artifacts should be built from authenticated PIT run-value data (e.g.
OAA/fielding run value, catcher framing/blocking/throwing and baserunning run
value).  Missing components are never silently imputed for promotion.
"""

from datetime import date
import json
import math
from pathlib import Path
from typing import Any

ROLE="CHALLENGER_ONLY"
ARTIFACT=Path("data/v14_defense_baserunning_priors.json")


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def load(path:Path|str=ARTIFACT)->dict[str,Any]:
    target=Path(path)
    if not target.exists(): return {}
    try: payload=json.loads(target.read_text(encoding="utf-8"))
    except Exception: return {}
    return payload if isinstance(payload,dict) and payload.get("point_in_time") is True else {}


def _safe(payload:dict[str,Any],target_date:str)->bool:
    try: return date.fromisoformat(str(payload.get("cutoff_day")))<=date.fromisoformat(str(target_date)[:10])
    except Exception: return False


def _team(payload:dict[str,Any],team_id:Any)->dict[str,Any]:
    teams=payload.get("teams") or {}; return teams.get(str(team_id)) or {}


def _factor(run_value:float|None,scale:float,low:float,high:float)->float|None:
    if run_value is None: return None
    # Positive defensive run value prevents runs, so opponent scoring factor <1.
    return max(low,min(high,1.0-float(run_value)/scale))


def build(*,home_team_id:Any,away_team_id:Any,target_date:str,artifact:dict[str,Any]|None=None)->dict[str,Any]:
    payload=load() if artifact is None else artifact
    base={"schema":"pulsar-v14-defense-baserunning-challenger-v1","role":ROLE,"auto_activation":False,"target_date":str(target_date),"market_probability_used_as_feature":False}
    if not payload or not _safe(payload,target_date): return {**base,"status":"COLLECTING","reason":"PIT defense/baserunning artifact unavailable or unsafe"}
    out={}
    for side,team_id in (("home",home_team_id),("away",away_team_id)):
        row=_team(payload,team_id); defense=_num(row.get("fielding_run_value_per_150") or row.get("defense_runs_per_150")); catcher=_num(row.get("catcher_run_value_per_150")); running=_num(row.get("baserunning_runs_per_600_pa"))
        missing=[name for name,value in (("defense",defense),("catcher",catcher),("baserunning",running)) if value is None]
        out[side]={"status":"READY_SHADOW" if not missing else "COLLECTING","missing":missing,"fielding_run_value_per_150":defense,"catcher_run_value_per_150":catcher,"baserunning_runs_per_600_pa":running,"defense_factor":_factor(defense,120.0,.88,1.12),"catcher_factor":_factor(catcher,180.0,.94,1.06),"baserunning_run_adjustment":max(-.12,min(.12,(running or 0.0)/600.0*38.0)) if running is not None else None}
    return {**base,"status":"READY_SHADOW" if all(v.get("status")=="READY_SHADOW" for v in out.values()) else "COLLECTING","cutoff_day":payload.get("cutoff_day"),**out}
