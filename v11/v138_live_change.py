from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA = "v13-8-critical-change-v1"


def _player_id(player: Any) -> str:
    if isinstance(player, dict):
        return str(
            player.get("id")
            or player.get("person_id")
            or player.get("personId")
            or ""
        )
    return str(player or "")


def _lineup_ids(lineup: Any) -> list[str]:
    if isinstance(lineup, dict):
        players = lineup.get("players") or lineup.get("lineup") or []
    elif isinstance(lineup, list):
        players = lineup
    else:
        players = []

    player_ids: list[str] = []
    for player in players[:9]:
        player_id = _player_id(player)
        if player_id:
            player_ids.append(player_id)
    return player_ids


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
    raw = json.dumps(
        personnel_state(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def classify(
    previous: dict[str, Any] | None,
    current_result: dict[str, Any],
) -> dict[str, Any]:
    current = personnel_state(current_result)
    current_sig = signature(current_result)
    previous = previous or {}
    previous_state = previous.get("personnel_state") or {}
    previous_sig = str(previous.get("analysis_signature") or "")

    if not previous_sig:
        return {
            "schema": SCHEMA,
            "changed": False,
            "critical": False,
            "reason": "NO_PREVIOUS_SIGNATURE",
            "analysis_signature": current_sig,
            "personnel_state": current,
        }

    if previous_sig == current_sig:
        return {
            "schema": SCHEMA,
            "changed": False,
            "critical": False,
            "reason": "UNCHANGED",
            "analysis_signature": current_sig,
            "personnel_state": current,
        }

    reasons: list[str] = []
    for side in ("home", "away"):
        starter_key = f"{side}_starter"
        old_starter = str(previous_state.get(starter_key) or "")
        new_starter = str(current.get(starter_key) or "")
        if old_starter and new_starter and old_starter != new_starter:
            reasons.append(f"{side.upper()}_STARTER_CHANGED")

        lineup_key = f"{side}_lineup"
        old_lineup = list(previous_state.get(lineup_key) or [])
        new_lineup = list(current.get(lineup_key) or [])
        if old_lineup and new_lineup and old_lineup != new_lineup:
            if set(old_lineup) != set(new_lineup):
                reasons.append(f"{side.upper()}_LINEUP_PERSONNEL_CHANGED")
            else:
                reasons.append(f"{side.upper()}_LINEUP_ORDER_CHANGED")

    critical = any(
        "STARTER_CHANGED" in reason or "LINEUP_PERSONNEL_CHANGED" in reason
        for reason in reasons
    )
    return {
        "schema": SCHEMA,
        "changed": True,
        "critical": critical,
        "reason": "+".join(reasons) if reasons else "SIGNATURE_CHANGED_NONCRITICAL",
        "analysis_signature": current_sig,
        "personnel_state": current,
        "reasons": reasons,
    }
