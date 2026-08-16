from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

MODEL_FILE = Path("data/v13_run_mean_prior.json")
SCHEMA = "v13-run-mean-prior-v1"


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def load(path: Path = MODEL_FILE) -> dict[str,Any]:
    if not path.exists():
        return {"active":False,"status":"ABSENT"}
    try:
        d=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"active":False,"status":"INVALID","error":type(exc).__name__}
    if d.get("schema") != SCHEMA:
        return {"active":False,"status":"INCOMPATIBLE"}
    return d


def apply_pair(home_mu: float, away_mu: float, phase: str, artifact: dict[str,Any] | None = None):
    artifact=load() if artifact is None else artifact
    phase=str(phase or "EARLY").upper()
    if not artifact.get("active") or phase != str(artifact.get("phase_scope") or "FINAL").upper():
        return home_mu,away_mu,{"active":False,"source":"none"}
    model=artifact.get("model") or {}
    cap=max(0.0,min(1.0,_num(model.get("max_adjustment"),.75)))
    sd=_num(model.get("slope_delta"))
    def one(mu,side):
        raw=_num(model.get(f"{side}_bias"))+sd*_num(mu)
        adj=max(-cap,min(cap,raw))
        return max(1.4,_num(mu)+adj),adj
    h,hd=one(home_mu,"home"); a,ad=one(away_mu,"away")
    return h,a,{"active":True,"source":"v13-historical-run-mean-prior","home_delta":hd,"away_delta":ad,
                "variant":artifact.get("selected_variant"),"historical_games":artifact.get("historical_games"),
                "exact_transfer_games":artifact.get("exact_games")}
