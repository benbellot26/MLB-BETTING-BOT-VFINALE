from __future__ import annotations

"""User-reported pick-result ledger analytics.

This is evaluation-only data. It must never be imported by the prediction
pipeline or used as a model feature. It exists to measure how published or
selected picks perform over time by market and at the recorded price.
"""

import json
import math
from pathlib import Path
from typing import Any

PICK_LEDGER = Path("data/v14_pick_ledger.jsonl")


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def read_pick_ledger(path: Path | str = PICK_LEDGER) -> list[dict[str, Any]]:
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
        if isinstance(row, dict) and row.get("schema") == "pulsar-v14-pick-result-v1":
            rows.append(row)
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    graded = [row for row in rows if str(row.get("result") or "").upper() in {"WIN", "LOSS", "PUSH"}]
    wins = sum(str(row.get("result")).upper() == "WIN" for row in graded)
    losses = sum(str(row.get("result")).upper() == "LOSS" for row in graded)
    pushes = sum(str(row.get("result")).upper() == "PUSH" for row in graded)
    decisions = wins + losses

    known_price = [row for row in graded if _num(row.get("odds")) is not None and _num(row.get("odds")) > 1]
    flat_profit = 0.0
    for row in known_price:
        result = str(row.get("result") or "").upper()
        odds = float(row["odds"])
        if result == "WIN":
            flat_profit += odds - 1.0
        elif result == "LOSS":
            flat_profit -= 1.0
    staked = sum(str(row.get("result") or "").upper() in {"WIN", "LOSS"} for row in known_price)

    return {
        "n": len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate": wins / decisions if decisions else None,
        "known_price_n": len(known_price),
        "flat_1u_profit_known_prices": flat_profit,
        "flat_1u_roi_known_prices": flat_profit / staked if staked else None,
    }


def pick_performance_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_market: dict[str, list[dict[str, Any]]] = {}
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_market.setdefault(str(row.get("market") or "UNKNOWN"), []).append(row)
        by_date.setdefault(str(row.get("date") or "UNKNOWN"), []).append(row)
    return {
        "schema": "pulsar-v14-pick-performance-v1",
        "role": "evaluation_only",
        "prediction_feature_usage": False,
        "overall": _summary(rows),
        "by_market": {name: _summary(values) for name, values in sorted(by_market.items())},
        "by_date": {name: _summary(values) for name, values in sorted(by_date.items())},
        "notes": [
            "User-reported outcomes are stored for evaluation and selection review only.",
            "Unknown odds are excluded from flat-unit ROI but remain included in hit rate.",
            "This ledger must not alter model coefficients without a separate validated training process.",
        ],
    }


def load_pick_performance(path: Path | str = PICK_LEDGER) -> dict[str, Any]:
    return pick_performance_report(read_pick_ledger(path))
