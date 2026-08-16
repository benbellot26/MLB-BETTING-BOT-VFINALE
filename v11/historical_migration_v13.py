from __future__ import annotations

from datetime import datetime
from typing import Any


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def classify(row: dict[str,Any]) -> tuple[str,list[str]]:
    """Classify historical rows without fabricating V13 evidence.

    MIGRATABLE_CALIBRATION means the saved prediction itself can calibrate the
    baseball-only probability. MIGRATABLE_FEATURE_TRAINING additionally requires
    explicit point-in-time feature provenance. DIAGNOSTIC_ONLY rows may be used
    for reporting but never fit V13 production parameters.
    """
    reasons: list[str] = []
    analyzed = _dt(row.get("analyzed_at"))
    game_time = _dt(row.get("game_date"))
    if analyzed is None or game_time is None or analyzed >= game_time:
        return "REJECT", ["not_verified_pregame"]
    if row.get("home_score") is None or row.get("away_score") is None:
        return "REJECT", ["unsettled"]
    options = row.get("options") or []
    baseball_saved = any(o.get("p_baseball_raw") is not None or o.get("p_learned") is not None for o in options)
    if not baseball_saved:
        reasons.append("no_saved_baseball_only_probability")
    provenance = row.get("feature_provenance") or {}
    feature_safe = bool(provenance) and all((m or {}).get("point_in_time") is True for m in provenance.values())
    if feature_safe and baseball_saved:
        return "MIGRATABLE_FEATURE_TRAINING", []
    if baseball_saved:
        return "MIGRATABLE_CALIBRATION", ["feature_provenance_not_sufficient_for_feature_refit"]
    return "DIAGNOSTIC_ONLY", reasons or ["legacy_contract_unknown"]


def summarize(rows: list[dict[str,Any]]) -> dict[str,Any]:
    counts: dict[str,int] = {}
    examples: dict[str,list[str]] = {}
    for row in rows:
        status,reasons = classify(row)
        counts[status] = counts.get(status,0)+1
        examples.setdefault(status,[])
        if len(examples[status]) < 5:
            examples[status].append(f"{row.get('game_pk')}:{','.join(reasons)}")
    return {
        "counts":counts,
        "examples":examples,
        "policy":"never relabel diagnostic legacy rows as V13-native evidence",
    }
