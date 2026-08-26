from __future__ import annotations

"""Production pregame acquisition using the single hardened V14 matcher.

There is intentionally no second matching implementation here. Keeping two
independent algorithms caused production to retain wider/greedy behavior after
the core matcher had been hardened. All production and research acquisition now
share the same fail-closed team/time matching contract.
"""

from datetime import datetime, timezone

from .acquisition import (
    PregameSnapshot,
    clear_http_cache,
    future_games,
    match_events,
    mlb_schedule,
    odds_snapshot,
)

# Compatibility alias for callers/tests; implementation is the authoritative
# hardened mutual-nearest matcher in acquisition.py.
match_events_strict = match_events


def collect_pregame_strict(
    target_date: str,
    *,
    analyzed_at: str | None = None,
    api_key: str | None = None,
    schedule_getter=None,
    odds_getter=None,
) -> PregameSnapshot:
    clear_http_cache()
    at = analyzed_at or datetime.now(timezone.utc).isoformat()
    schedule_kwargs = {"getter": schedule_getter} if schedule_getter is not None else {}
    odds_kwargs = {"getter": odds_getter} if odds_getter is not None else {}
    games = future_games(mlb_schedule(target_date, **schedule_kwargs), as_of=at)
    events = odds_snapshot(api_key=api_key, **odds_kwargs)
    matches = match_events(games, events)
    return PregameSnapshot(
        target_date=str(target_date),
        analyzed_at=str(at),
        games=games,
        events=events,
        matches=matches,
    ).validated()
