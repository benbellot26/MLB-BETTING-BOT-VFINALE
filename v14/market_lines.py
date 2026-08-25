from __future__ import annotations

"""Market-line and price snapshot helpers for V14.

Prices are persisted only for post-prediction diagnostics (edge/EV/CLV). They
never enter the baseball probability model. Total-line selection remains based
on complete paired lines, with an optional freshness gate in production.
"""

from collections import Counter
from datetime import datetime, timezone
import math
from statistics import median
from typing import Any

PREFERRED_DISPLAY_BOOKS = ("winamax_fr", "pinnacle")
DEFAULT_MAX_MARKET_AGE_MINUTES = 20.0


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _half_run(value: Any) -> float | None:
    out = _num(value)
    if out is None or out <= 0:
        return None
    doubled = round(out * 2)
    if abs(out * 2 - doubled) > 1e-9 or doubled % 2 != 1:
        return None
    return out


def market_age_minutes(book: dict[str, Any], as_of: Any) -> float | None:
    updated = _time(book.get("last_update"))
    at = _time(as_of)
    if updated is None or at is None:
        return None
    return max(0.0, (at - updated).total_seconds() / 60.0)


def _fresh_books(
    event: dict[str, Any],
    *,
    as_of: Any | None = None,
    max_age_minutes: float = DEFAULT_MAX_MARKET_AGE_MINUTES,
) -> list[dict[str, Any]]:
    books = [b for b in event.get("bookmakers") or [] if isinstance(b, dict)]
    if as_of is None:
        return books
    fresh = []
    for book in books:
        age = market_age_minutes(book, as_of)
        # Fail closed only when the source actually provides a timestamp.
        if age is None or age <= max_age_minutes:
            fresh.append(book)
    return fresh


def complete_total_lines_by_book(
    event: dict[str, Any],
    *,
    as_of: Any | None = None,
    max_age_minutes: float = DEFAULT_MAX_MARKET_AGE_MINUTES,
) -> dict[str, set[float]]:
    result: dict[str, set[float]] = {}
    for book in _fresh_books(event, as_of=as_of, max_age_minutes=max_age_minutes):
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


def choose_total_line(
    event: dict[str, Any],
    *,
    as_of: Any | None = None,
    max_age_minutes: float = DEFAULT_MAX_MARKET_AGE_MINUTES,
) -> dict[str, Any]:
    """Choose a complete half-run line without looking at prices."""
    by_book = complete_total_lines_by_book(event, as_of=as_of, max_age_minutes=max_age_minutes)
    if not by_book:
        raise ValueError("no fresh complete half-run total line available")

    for key in PREFERRED_DISPLAY_BOOKS:
        lines = sorted(by_book.get(key) or [])
        if len(lines) == 1:
            return {
                "line": lines[0],
                "source": key,
                "method": "preferred-book-complete-pair",
                "books_at_line": sum(lines[0] in values for values in by_book.values()),
                "max_market_age_minutes": max_age_minutes if as_of is not None else None,
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
        "max_market_age_minutes": max_age_minutes if as_of is not None else None,
        "market_price_used_as_feature": False,
    }


def _market_outcomes(book: dict[str, Any], key: str) -> list[dict[str, Any]]:
    for market in book.get("markets") or []:
        if str(market.get("key") or "").lower() == key:
            return [x for x in market.get("outcomes") or [] if isinstance(x, dict)]
    return []


def _preferred_book_order(books: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {name: i for i, name in enumerate(PREFERRED_DISPLAY_BOOKS)}
    return sorted(
        books,
        key=lambda b: (
            rank.get(str(b.get("key") or ""), len(rank)),
            -(_time(b.get("last_update")).timestamp() if _time(b.get("last_update")) else 0.0),
        ),
    )


def canonical_market_snapshot(
    event: dict[str, Any],
    *,
    total_line: float,
    as_of: Any,
    max_age_minutes: float = DEFAULT_MAX_MARKET_AGE_MINUTES,
) -> dict[str, Any]:
    """Persist one fresh paired price source for ML, RL ±1.5 and selected total."""
    books = _preferred_book_order(_fresh_books(event, as_of=as_of, max_age_minutes=max_age_minutes))
    snapshot: dict[str, Any] = {
        "schema": "pulsar-v14-market-snapshot-v1",
        "captured_at": str(as_of),
        "event_id": event.get("id"),
        "commence_time": event.get("commence_time"),
        "max_age_minutes": max_age_minutes,
        "market_probability_used_as_feature": False,
        "markets": {},
    }

    def store(name: str, book: dict[str, Any], selections: dict[str, dict[str, Any]]) -> None:
        snapshot["markets"][name] = {
            "bookmaker": book.get("key"),
            "bookmaker_title": book.get("title"),
            "last_update": book.get("last_update"),
            "age_minutes": market_age_minutes(book, as_of),
            "selections": selections,
        }

    for book in books:
        outcomes = _market_outcomes(book, "h2h")
        by_name = {str(x.get("name") or ""): x for x in outcomes}
        home, away = str(event.get("home_team") or ""), str(event.get("away_team") or "")
        if home in by_name and away in by_name:
            store("ML", book, {
                "home": {"name": home, "price": _num(by_name[home].get("price"))},
                "away": {"name": away, "price": _num(by_name[away].get("price"))},
            })
            break

    for book in books:
        outcomes = _market_outcomes(book, "spreads")
        home, away = str(event.get("home_team") or ""), str(event.get("away_team") or "")
        home_rows = [x for x in outcomes if str(x.get("name") or "") == home]
        away_rows = [x for x in outcomes if str(x.get("name") or "") == away]
        selections: dict[str, dict[str, Any]] = {}
        for row in home_rows:
            point = _num(row.get("point"))
            if point in {-1.5, 1.5}:
                selections[f"home_{point:+.1f}"] = {"name": home, "point": point, "price": _num(row.get("price"))}
        for row in away_rows:
            point = _num(row.get("point"))
            if point in {-1.5, 1.5}:
                selections[f"away_{point:+.1f}"] = {"name": away, "point": point, "price": _num(row.get("price"))}
        if len(selections) >= 2:
            store("RL", book, selections)
            break

    for book in books:
        outcomes = _market_outcomes(book, "totals")
        selected = [x for x in outcomes if _num(x.get("point")) == float(total_line)]
        by_side = {str(x.get("name") or "").lower(): x for x in selected}
        if "over" in by_side and "under" in by_side:
            store("TOTAL", book, {
                "over": {"name": "Over", "point": float(total_line), "price": _num(by_side["over"].get("price"))},
                "under": {"name": "Under", "point": float(total_line), "price": _num(by_side["under"].get("price"))},
            })
            break

    return snapshot
