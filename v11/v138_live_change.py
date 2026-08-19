from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA = "v13-8-critical-change-v1"


def _player_id(player: Any) -> str:
    if isinstance(player, dict):
        return str(player.get("id") or player.get("person_id") or player.get("personId") or "")
    return str(player or "")


def _lineup_ids(lineup: Any) -> list[str]:
    if isinstance(lineup, dict):
        players = lineup.get("players") or lineup.get("lineup") or []
    elif isinstance(lineup, list):
        players = lineup
    else:
        players = []
    return [_player_id(x) for x in players[:9] if _player_id(x)]


def personnel_state(result: dict[str, Any]) -> dict[str, Any]:
    ctx = result.get("ctx") or {}
    home_starter = ctx.get("home_starter") or {}
    away_starter = ctx.get("away_starter") or {}
    home_sp = _player_id(home_starter) or str(ctx.get("home_sp") or "")
    away_sp = _player_id(away_starter) or str(ctx.get("away_sp") or "")
    return {
        "game_pk": str(result.get("game_pk") or ""),
        "home_starter": home_sp,
        "away_starter": away_sp,
        "home_lineup": _lineup_ids(ctx.get("home_lineup")),
        "away_lineup": _lineup_ids(ctx.get("away_lineup")),
    }


def signature(result: dict[str, Any]) -> str:
    raw = json.dumps(personnel_state(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def classify(previous: dict[str, Any] | None, current_result: dict[str, Any]) -> dict[str, Any]:
    current = personnel_state(current_result)
    current_sig = signature(current_result)
    previous = previous or {}
    previous_state = previous.get("personnel_state") or {}
    previous_sig = str(previous.get("analysis_signature") or "")
    if not previous_sig:
        return {"schema": SCHEMA, "changed": False, "critical": False, "reason": "NO_PREVIOUS_SIGNATURE",
                "analysis_signature": current_sig, "personnel_state": current}
    if previous_sig == current_sig:
        return {"schema": SCHEMA, "changed": False, "critical": False, "reason": "UNCHANGED",
                "analysis_signature": current_sig, "personnel_state": current}
    reasons = []
    for side in ("home", "away"):
        key = f"{side}_starter"
        old, new = str(previous_state.get(key) or ""), str(current.get(key) or "")
        if old and new and old != new:
            reasons.append(f"{side.upper()}_STARTER_CHANGED")
        lk = f"{side}_lineup"
        old_l, new_l = list(previous_state.get(lk) or []), list(current.get(lk) or [])
        if old_l and new_l and old_l != new_l:
            old_set, new_set = set(old_l), set(new_l)
            if old_set != new_set:
                reasons.append(f"{side.upper()}_LINEUP_PERSONNEL_CHANGED")
            else:
                reasons.append(f"{side.upper()}_LINEUP_ORDER_CHANGED")
    critical = any("STARTER_CHANGED" in r or "LINEUP_PERSONNEL_CHANGED" in r for r in reasons)
    return {"schema": SCHEMA, "changed": True, "critical": critical,
            "reason": "+".join(reasons) if reasons else "SIGNATURE_CHANGED_NONCRITICAL",
            "analysis_signature": current_sig, "personnel_state": current, "reasons": reasons}
