from __future__ import annotations

"""Market-line selection for V14 display surfaces.

Bookmaker data is used only to select the line that the model should price.
Prices and implied probabilities never enter the baseball probability model.
"""

from collections import Counter
import math
from statistics import median
from typing import Any

PREFERRED_DISPLAY_BOOKS = ("winamax_fr", "pinnacle")


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _half_run(value: Any) -> float | None:
    out = _num(value)
    if out is None or out <= 0:
        return None
    doubled = round(out * 2)
    if abs(out * 2 - doubled) > 1e-9 or doubled % 2 != 1:
        return None
    return out


def complete_total_lines_by_book(event: dict[str, Any]) -> dict[str, set[float]]:
    result: dict[str, set[float]] = {}
    for book in event.get("bookmakers") or []:
        key = str(book.get("key") or "")
        if not key:
            continue
        seen: dict[float, set[str]] = {}
        for market in book.get("markets") or []:
            if str(market.get("key") or "").lower() != "totals":
                continue
            for outcome in market.get("outcomes") or []:
                side = str(outcome.get("name") or "").strip().lower()
                point = _half_run(outcome.get("point"))
                if point is not None and side in {"over", "under"}:
                    seen.setdefault(point, set()).add(side)
        complete = {point for point, sides in seen.items() if {"over", "under"} <= sides}
        if complete:
            result[key] = complete
    return result


def choose_total_line(event: dict[str, Any]) -> dict[str, Any]:
    """Choose a complete half-run line without looking at prices.

    Preferred books win when they expose exactly one complete half-run line.
    Otherwise use the cross-book modal line, with median proximity as a stable
    tie-break. The returned metadata proves prices were irrelevant.
    """
    by_book = complete_total_lines_by_book(event)
    if not by_book:
        raise ValueError("no complete half-run total line available")

    for key in PREFERRED_DISPLAY_BOOKS:
        lines = sorted(by_book.get(key) or [])
        if len(lines) == 1:
            return {
                "line": lines[0],
                "source": key,
                "method": "preferred-book-complete-pair",
                "books_at_line": sum(lines[0] in values for values in by_book.values()),
                "market_price_used_as_feature": False,
            }

    occurrences = [line for lines in by_book.values() for line in lines]
    counts = Counter(occurrences)
    best_count = max(counts.values())
    candidates = sorted(line for line, count in counts.items() if count == best_count)
    center = median(occurrences)
    chosen = min(candidates, key=lambda line: (abs(line - center), line))
    return {
        "line": chosen,
        "source": "cross-book",
        "method": "modal-complete-pair",
        "books_at_line": counts[chosen],
        "market_price_used_as_feature": False,
    }
