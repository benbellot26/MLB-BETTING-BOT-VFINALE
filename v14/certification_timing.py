from __future__ import annotations

"""Shared timing/provenance contract for betting-certification evidence.

Research and manual analytics may observe any strictly-pregame snapshot. Betting
certification is narrower: it uses only automated ``SCHEDULED_FINAL`` snapshots
that were actually observed 10-60 minutes before first pitch and whose native
phase was FINAL. Missing observations stay missing; nothing is reconstructed
retrospectively.
"""

from datetime import datetime, timezone
from typing import Any

CERTIFICATION_PHASE = "FINAL"
CERTIFICATION_RUN_TRIGGER = "SCHEDULED_FINAL"
FINAL_MIN_MINUTES_TO_GAME = 10.0
FINAL_MAX_MINUTES_TO_GAME = 60.0
FINAL_TARGET_MINUTES_TO_GAME = 30.0
ALLOWED_RUN_TRIGGERS = {"MANUAL", CERTIFICATION_RUN_TRIGGER}


def _dt(value: Any) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if out.tzinfo is None:
            out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def normalize_run_trigger(value: Any, *, default: str = "MANUAL") -> str:
    trigger = str(value or default).strip().upper()
    if trigger not in ALLOWED_RUN_TRIGGERS:
        raise ValueError(f"unsupported V14 run trigger: {trigger}")
    return trigger


def row_run_trigger(row: dict[str, Any]) -> str:
    direct = row.get("run_trigger")
    if direct:
        return str(direct).strip().upper()
    nested = (row.get("v14_prediction") or {}).get("run_trigger")
    return str(nested or "LEGACY_UNSPECIFIED").strip().upper()


def minutes_to_game(row: dict[str, Any]) -> float | None:
    game = _dt(row.get("game_date")); analyzed = _dt(row.get("analyzed_at"))
    if game is None or analyzed is None:
        return None
    return (game - analyzed).total_seconds() / 60.0


def is_certification_snapshot(row: dict[str, Any]) -> bool:
    minutes = minutes_to_game(row)
    return bool(
        row_run_trigger(row) == CERTIFICATION_RUN_TRIGGER
        and str(row.get("phase") or "").upper() == CERTIFICATION_PHASE
        and minutes is not None
        and FINAL_MIN_MINUTES_TO_GAME <= minutes <= FINAL_MAX_MINUTES_TO_GAME
    )


def first_certification_snapshots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return first observed certification snapshot per game.

    The selector is deliberately first-observation, not closest-to-target. The
    automated scheduler is responsible for when observations happen; selecting a
    later prettier snapshot after the result would reintroduce timing selection.
    """
    first: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not is_certification_snapshot(row):
            continue
        game_pk = str(row.get("game_pk") or "")
        analyzed = _dt(row.get("analyzed_at"))
        if not game_pk or analyzed is None:
            continue
        current = first.get(game_pk)
        if current is None:
            first[game_pk] = row
            continue
        current_at = _dt(current.get("analyzed_at"))
        if current_at is None or analyzed < current_at:
            first[game_pk] = row
    return sorted(
        first.values(),
        key=lambda row: (_dt(row.get("game_date")) or datetime.min.replace(tzinfo=timezone.utc), _dt(row.get("analyzed_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("game_pk") or "")),
    )
