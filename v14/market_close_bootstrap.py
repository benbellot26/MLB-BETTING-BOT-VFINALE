from __future__ import annotations

"""Fail-safe bootstrap for the V14 prospective market-close archive.

Prediction rows are themselves persisted strictly pregame evidence. This module
may use them only to register a still-future event for subsequent close capture.
It never fabricates historical closes, never creates a paper bet, and never
changes model probabilities or champion behavior.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .acquisition import MATCH_TIME_TOLERANCE_MINUTES, parse_time
from .market_close_ledger import LEDGER, ROLE, SCHEMA, _line_key, _num, _read, _write
from .tracking import PREDICTIONS


def _read_predictions(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _event_identity(row: dict[str, Any]) -> tuple[str, bool, float | None]:
    market = row.get("market_snapshot") or {}
    event_id = str(market.get("event_id") or "")
    try:
        game = parse_time(row.get("game_date"))
        event = parse_time(market.get("commence_time"))
    except Exception:
        return event_id, False, None
    delta = abs((event - game).total_seconds()) / 60.0
    return event_id, bool(event_id) and delta <= MATCH_TIME_TOLERANCE_MINUTES, delta


def bootstrap(
    predictions_path: Path | str = PREDICTIONS,
    ledger_path: Path | str = LEDGER,
    *,
    now: datetime | None = None,
) -> int:
    """Register still-future events from already-persisted pregame predictions.

    Only exact current-generation/current-policy rows are accepted. A prediction
    must itself be strictly pregame, must carry a verified fresh market snapshot,
    and the event commence time must match the MLB game time. Rows for games that
    have already started are ignored, preventing postgame reconstruction.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    archives = _read(ledger_path)
    by_game = {
        str(row.get("game_pk") or ""): row
        for row in archives
        if row.get("model_generation") == MODEL_GENERATION
        and row.get("probability_policy_id") == PROBABILITY_POLICY_ID
        and str(row.get("game_pk") or "")
    }
    before = len(archives)
    changed = False

    # Process in chronological snapshot order so the latest strictly-pregame
    # tracked total line becomes the current line while all prior lines remain
    # available for exact paper-entry hydration.
    rows = sorted(
        _read_predictions(predictions_path),
        key=lambda row: str(row.get("analyzed_at") or ""),
    )
    for row in rows:
        if row.get("model_generation") != MODEL_GENERATION:
            continue
        if row.get("probability_policy_id") != PROBABILITY_POLICY_ID:
            continue
        if str(row.get("schema") or "") != "pulsar-v14-prediction-record-v6":
            continue
        game_pk = str(row.get("game_pk") or "")
        analyzed_at = str(row.get("analyzed_at") or "")
        game_date = row.get("game_date")
        if not game_pk or not analyzed_at or not game_date:
            continue
        try:
            analyzed = parse_time(analyzed_at)
            game = parse_time(game_date)
        except Exception:
            continue
        if not analyzed < game:
            continue
        if not current < game:
            continue
        market = row.get("market_snapshot") or {}
        if market.get("freshness_verified") is not True:
            continue
        event_id, event_verified, event_delta = _event_identity(row)
        if not event_verified:
            continue
        line = _num(row.get("total_line"))
        existing = by_game.get(game_pk)
        if existing is None:
            archive = {
                "schema": SCHEMA,
                "ledger_role": ROLE,
                "research_only": True,
                "certification_eligible": False,
                "champion_impact": False,
                "auto_activation": False,
                "model_generation": MODEL_GENERATION,
                "probability_policy_id": PROBABILITY_POLICY_ID,
                "game_pk": game_pk,
                "odds_event_id": event_id,
                "odds_event_time_verified": True,
                "odds_event_time_delta_minutes": event_delta,
                "target_date": str(row.get("target_date") or ""),
                "game_date": game_date,
                "home": row.get("home"),
                "away": row.get("away"),
                "first_tracked_at": analyzed_at,
                "latest_tracked_at": analyzed_at,
                "tracked_total_lines": [_line_key(line)] if line is not None else [],
                "latest_total_line": line,
                "close_history": [],
                "best_close": None,
                "bootstrap_source": "PERSISTED_PREGAME_PREDICTION",
            }
            archives.append(archive)
            by_game[game_pk] = archive
            changed = True
            continue

        if str(existing.get("odds_event_id") or "") != event_id:
            continue
        try:
            newer = analyzed > parse_time(existing.get("latest_tracked_at"))
        except Exception:
            newer = False
        lines = list(existing.get("tracked_total_lines") or [])
        if line is not None and _line_key(line) not in lines:
            lines.append(_line_key(line))
            existing["tracked_total_lines"] = sorted(lines, key=float)
            changed = True
        if newer:
            existing["latest_tracked_at"] = analyzed_at
            existing["latest_total_line"] = line
            changed = True

    if changed or (not Path(ledger_path).exists() and archives):
        archives.sort(key=lambda row: (str(row.get("game_date") or ""), str(row.get("game_pk") or "")))
        _write(archives, ledger_path)
    return len(archives) - before


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap V14 close tracking from persisted pregame predictions")
    parser.add_argument("--predictions", default=str(PREDICTIONS))
    parser.add_argument("--ledger", default=str(LEDGER))
    args = parser.parse_args()
    print(json.dumps({"bootstrapped": bootstrap(args.predictions, args.ledger)}, sort_keys=True))


if __name__ == "__main__":
    main()
