from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import core, journal
from . import probability_contract_v13 as contract


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def captured_game_phases(rows: list[dict[str, Any]] | None = None) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in journal.load_rows() if rows is None else rows:
        if not contract.row_is_predictively_compatible(row):
            continue
        gid = str(row.get("game_pk") or "")
        phase = str(row.get("phase") or "EARLY").upper()
        analyzed = _dt(row.get("analyzed_at"))
        start = _dt(row.get("game_date"))
        if gid and analyzed is not None and start is not None and analyzed < start:
            out.add((gid, phase))
    return out


def build(now: datetime | None = None, games: list[dict[str, Any]] | None = None,
          rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Decide whether a research run needs the paid Odds API.

    MLB schedule lookup is free. A paid research analysis is only needed when at
    least one future game has entered an EARLY/LATE/FINAL phase that has not yet
    been captured under the current predictive contract.
    """
    now = now or datetime.now(timezone.utc)
    games = core.mlb_schedule(core.TARGET_DATE) if games is None else games
    captured = captured_game_phases(rows)
    missing = []
    future = 0
    for game in games or []:
        gid = str(game.get("gamePk") or "")
        start = _dt(game.get("gameDate"))
        if not gid or start is None or start <= now:
            continue
        future += 1
        phase = core.phase_for_game(game, now)
        if (gid, phase) not in captured:
            missing.append({"game_pk": game.get("gamePk"), "game_date": game.get("gameDate"), "phase": phase})
    return {
        "schema": "v13-research-gate-v1",
        "target_date": core.TARGET_DATE,
        "checked_at": now.isoformat(),
        "future_games": future,
        "captured_current_generation_game_phases": len(captured),
        "missing_game_phases": missing,
        "run_needed": bool(missing),
        "paid_odds_api_required": bool(missing),
        "reason": "uncaptured-current-phase" if missing else "all-current-phases-already-captured-or-no-future-games",
    }


def main() -> None:
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
