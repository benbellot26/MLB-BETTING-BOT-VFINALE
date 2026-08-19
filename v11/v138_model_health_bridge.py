from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str,Any]:
    p=Path(path)
    if not p.exists():return {}
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return {}


def build() -> dict[str,Any]:
    closure=_load("data/v138_audit_closure.json");research=_load("data/v138_research_models.json")
    monitoring=_load("data/v138_monitoring.json");validation=_load("data/v138_validation.json")
    return {"audit_closure":{"engineering_closed":closure.get("engineering_closed"),"engineering_open":closure.get("engineering_open"),
            "overall_closed":closure.get("overall_closed"),"evidence_gates_pending":closure.get("evidence_gates_pending")},
        "research_challengers":{"status":research.get("status"),"games":research.get("games"),"holdout_games":research.get("holdout_games"),
            "ensemble_weights":research.get("ensemble_weights"),"promotion_eligible":research.get("promotion_eligible")},
        "walk_forward":{"folds":len((validation.get("walk_forward") or {}).get("folds") or []),
            "seasons":(validation.get("walk_forward") or {}).get("seasons")},
        "feature_drift":monitoring.get("feature_drift") or {},"alerts":monitoring.get("alerts") or []}
