from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import engine_v12 as engine
from .v13_rich_run_residual import SCHEMA, MODULES, _apply, _num

MODEL_FILE = Path("data/v13_rich_run_residual.json")


def load(path: Path = MODEL_FILE) -> dict[str,Any]:
    if not path.exists(): return {"schema":SCHEMA,"shadow_enabled":False,"status":"ABSENT"}
    try: d=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: return {"schema":SCHEMA,"shadow_enabled":False,"status":"INVALID","error":type(exc).__name__}
    if d.get("schema") != SCHEMA: return {"schema":SCHEMA,"shadow_enabled":False,"status":"INCOMPATIBLE"}
    return d


def _variant_options(result: dict[str,Any], hmu: float, amu: float) -> list[dict[str,Any]]:
    home=str((result.get("ctx") or {}).get("home") or "")
    out=[]
    for opt in result.get("options") or []:
        market=str(opt.get("market") or "").upper(); name=str(opt.get("name") or "")
        if market == "ML":
            ph=engine.prob_home_win(hmu,amu); p=ph if name==home else 1-ph
        elif market == "RUNLINE" and opt.get("point") is not None:
            side="home" if name==home else "away"
            win,push=engine.prob_cover_parts(hmu,amu,side,_num(opt.get("point"),0.0)); p=win/max(1e-9,1-push)
        elif market == "TOTAL" and opt.get("point") is not None:
            side=str(name).lower(); win,push=engine.prob_total_parts(hmu,amu,side,_num(opt.get("point"),0.0)); p=win/max(1e-9,1-push)
        else:
            continue
        out.append({"market":market,"name":name,"point":opt.get("point"),"p_baseball_raw":max(.001,min(.999,p))})
    return out


def attach(result: dict[str,Any], artifact: dict[str,Any] | None = None) -> dict[str,Any]:
    artifact=load() if artifact is None else artifact
    phase=str(result.get("phase") or "EARLY").upper()
    shadow=result.get("shadow_v124") or {}; modules=shadow.get("modules") or {}
    payload={"schema":SCHEMA,"status":"UNAVAILABLE","research_only":True,"affects_v13_probability":False,"affects_selector":False,"affects_staking":False}
    if not artifact.get("shadow_enabled"):
        payload["status"]="MODEL_NOT_VALIDATED"; result["shadow_v13_rich_runs"]=payload; return result
    if phase != "FINAL":
        payload["status"]="FINAL_ONLY"; result["shadow_v13_rich_runs"]=payload; return result
    if not modules:
        payload["status"]="MISSING_V124_FEATURES"; result["shadow_v13_rich_runs"]=payload; return result
    hm=result.get("projected_home_runs"); am=result.get("projected_away_runs")
    if hm is None or am is None:
        payload["status"]="MISSING_BASE_MEANS"; result["shadow_v13_rich_runs"]=payload; return result
    model=artifact.get("model") or {}
    h,hd=_apply(_num(hm),"home",modules,model); a,ad=_apply(_num(am),"away",modules,model)
    payload.update({"status":"ACTIVE_SHADOW","home_mu":h,"away_mu":a,"home_delta":hd,"away_delta":ad,
                    "options":_variant_options(result,h,a),"modules":list(MODULES),"model_status":artifact.get("status"),
                    "historical_games":artifact.get("historical_games"),"exact_games":artifact.get("exact_games")})
    result["shadow_v13_rich_runs"]=payload
    return result
