from __future__ import annotations

"""Cost-aware gate in front of the paid Odds close-capture call.

The workflow may wake frequently, but this module makes ZERO network calls until
at least one tracked game is inside the certified-close window and still lacks a
certified close. One Odds snapshot can then serve every due game in that run.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .acquisition import parse_time
from .market_close_ledger import LEDGER, _read, capture

CERTIFIED_DUE_WINDOW_MINUTES = 18.0


def _has_certified_close(row: dict[str, Any]) -> bool:
    best = row.get("best_close") or {}
    if str(best.get("quality") or "") == "CERTIFIED_CLOSE":
        return True
    for close in row.get("close_history") or []:
        if isinstance(close, dict) and str(close.get("quality") or "") == "CERTIFIED_CLOSE":
            return True
    return False


def due_games(path: Path | str = LEDGER, *, now: datetime | None = None) -> list[dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None: current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    due: list[dict[str, Any]] = []
    for row in _read(path):
        if row.get("odds_event_time_verified") is not True or _has_certified_close(row):
            continue
        try: minutes = (parse_time(row.get("game_date")) - current).total_seconds() / 60.0
        except Exception: continue
        if 0 < minutes <= CERTIFIED_DUE_WINDOW_MINUTES:
            due.append({"game_pk": row.get("game_pk"), "minutes_to_game": minutes})
    return due


def run(
    path: Path | str = LEDGER,
    *,
    api_key: str | None = None,
    events_loader: Callable[[], list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    due = due_games(path, now=now)
    if not due:
        return {
            "api_call_performed": False,
            "captured": 0,
            "due_games": 0,
            "reason": "no game needs a first certified close",
            "cost_policy": "wake often, call Odds only when a certified close is due",
        }
    changed = capture(path, api_key=api_key, events_loader=events_loader, now=now)
    return {
        "api_call_performed": True,
        "captured": changed,
        "due_games": len(due),
        "due": due,
        "cost_policy": "one Odds snapshot per due run; already-certified games never trigger another paid call",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cost-aware V14 certified close capture")
    parser.add_argument("--ledger", default=str(LEDGER)); parser.add_argument("--api-key"); args = parser.parse_args()
    print(json.dumps(run(args.ledger, api_key=args.api_key), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__": main()
