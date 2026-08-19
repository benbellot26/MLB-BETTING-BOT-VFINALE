from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import market

FILE = Path(os.getenv("V138_BOOK_TELEMETRY_FILE", "data/v138_book_probabilities.jsonl"))
SCHEMA = "v13-8-book-probability-telemetry-v1"


def _norm(value: Any) -> str:
    return "".join(char.lower() for char in str(value or "") if char.isalnum())


def _canonical_option(result: dict[str, Any], option: dict[str, Any]) -> bool:
    market_name = str(option.get("market") or "").upper()
    name = str(option.get("name") or "")
    home = str((result.get("ctx") or {}).get("home") or "")

    if market_name == "ML":
        return _norm(name) == _norm(home)
    if market_name == "RUNLINE":
        return bool(option.get("is_canonical_line")) and _norm(name) == _norm(home)
    if market_name == "TOTAL":
        return bool(option.get("is_canonical_line")) and name.lower() == "over"
    return False


def capture(results: list[dict[str, Any]] | None, observed_at: str | None = None) -> int:
    """Persist one canonical per-book no-vig probability row per game/market snapshot.

    This is market telemetry only. It never feeds the baseball feature path and
    does not change the currently configured sharp consensus weights.
    """
    recorded_at = observed_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for result in results or []:
        event = result.get("event") or {}
        ctx = result.get("ctx") or {}
        as_of = str(result.get("as_of") or recorded_at)

        for option in result.get("options") or []:
            if not _canonical_option(result, option):
                continue

            market_name = str(option.get("market") or "").upper()
            name = option.get("name")
            point = option.get("point")
            try:
                consensus = market.sharp_consensus(
                    event,
                    market_name,
                    name,
                    point,
                    as_of=as_of,
                )
            except Exception:
                consensus = {}

            book_probs = dict(consensus.get("book_probs") or {})
            if not book_probs:
                continue

            rows.append(
                {
                    "schema": SCHEMA,
                    "game_pk": str(result.get("game_pk") or ""),
                    "game_date": (result.get("game") or {}).get("gameDate")
                    or event.get("commence_time"),
                    "home": ctx.get("home"),
                    "away": ctx.get("away"),
                    "market": market_name,
                    "pick": name,
                    "point": point,
                    "phase": str(result.get("phase") or "EARLY").upper(),
                    "observation_at": as_of,
                    "recorded_at": recorded_at,
                    "canonical": True,
                    "p_model": option.get(
                        "p_baseball_calibrated",
                        option.get("p_effective"),
                    ),
                    "p_market": option.get("p_market"),
                    "book_probs": book_probs,
                    "book_ages_min": consensus.get("book_ages_min") or {},
                    "market_probability_only": True,
                    "baseball_feature": False,
                }
            )

    if not rows:
        return 0

    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    return len(rows)


def read(path: Path = FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get("schema") == SCHEMA:
                rows.append(row)
        except Exception:
            pass
    return rows
