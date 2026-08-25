from __future__ import annotations

"""Pregame analysis phase for Pulsar V14.

The phase is descriptive metadata for the state of the pregame information; it
must never be hard-coded to FINAL.  We use both time-to-first-pitch and lineup
publication state so an early-day run stays EARLY even though the game itself
is scheduled for the same date.
"""

from datetime import datetime, timezone
from typing import Any


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _lineup_count(lineup: Any) -> int:
    if not isinstance(lineup, dict):
        return 0
    try:
        count = int(lineup.get("count") or 0)
    except Exception:
        count = 0
    players = lineup.get("players")
    if isinstance(players, list):
        count = max(count, len(players))
    return max(0, min(9, count))


def infer_phase(*, analyzed_at: Any, game_date: Any, context: dict[str, Any] | None = None) -> str:
    """Return EARLY, LATE or FINAL for a pregame snapshot.

    FINAL is reserved for a genuinely late pregame state: both starting lineups
    are complete and first pitch is within two hours.  LATE covers a game within
    four hours or any published lineup information.  Everything earlier is
    EARLY.  If timestamps are unavailable we fail conservatively toward lineup
    state instead of claiming FINAL.
    """
    ctx = context or {}
    home_count = _lineup_count(ctx.get("home_lineup"))
    away_count = _lineup_count(ctx.get("away_lineup"))
    both_complete = home_count >= 9 and away_count >= 9
    any_lineup = home_count > 0 or away_count > 0

    analyzed = _parse_dt(analyzed_at)
    first_pitch = _parse_dt(game_date)
    minutes_to_game: float | None = None
    if analyzed is not None and first_pitch is not None:
        minutes_to_game = (first_pitch - analyzed).total_seconds() / 60.0

    if minutes_to_game is not None:
        if minutes_to_game <= 120 and both_complete:
            return "FINAL"
        if minutes_to_game <= 240 or any_lineup:
            return "LATE"
        return "EARLY"

    if both_complete:
        return "LATE"
    if any_lineup:
        return "LATE"
    return "EARLY"
