from __future__ import annotations

"""Sharp-market consensus separated from execution/display prices.

The baseball model never consumes this module. It is used only after prediction
for benchmarking, diagnostics and (once certified) betting decisions.
"""

import math
from statistics import median
from typing import Any

from .market_lines import DEFAULT_MAX_MARKET_AGE_MINUTES, _book_freshness, _market_outcomes, _num

SHARP_BOOK_WEIGHTS = {"pinnacle": 1.00, "betfair_ex_eu": 0.95, "matchbook": 0.90, "betonlineag": 0.65}


def proportional_devig(a: float, b: float) -> tuple[float, float]:
    ia, ib = 1.0 / float(a), 1.0 / float(b); s = ia + ib
    if not math.isfinite(s) or s <= 0: raise ValueError("invalid two-way prices")
    return ia / s, ib / s


def power_devig(a: float, b: float) -> tuple[float, float]:
    q1, q2 = 1.0 / float(a), 1.0 / float(b)
    if min(q1, q2) <= 0: raise ValueError("invalid prices")
    lo, hi = 0.05, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2; value = q1 ** mid + q2 ** mid
        if value > 1: lo = mid
        else: hi = mid
    k = (lo + hi) / 2; p1, p2 = q1 ** k, q2 ** k; s = p1 + p2
    return p1 / s, p2 / s


def _fair_pair(a: float, b: float) -> tuple[float, float, dict[str, Any]]:
    prop = proportional_devig(a, b); power = power_devig(a, b); p1, p2 = (prop[0] + power[0]) / 2, (prop[1] + power[1]) / 2; s = p1 + p2
    return p1 / s, p2 / s, {"methods": ["proportional", "power"], "proportional": prop, "power": power}


def _weighted_consensus(rows: list[tuple[float, float, str]]) -> float | None:
    if not rows: return None
    med = median(p for p, _w, _b in rows); bounded = [(max(med - .08, min(med + .08, p)), w, b) for p, w, b in rows]; total_w = sum(w for _p, w, _b in bounded)
    return sum(p * w for p, w, _b in bounded) / max(1e-12, total_w)


def _price_pair(outcomes: list[dict[str, Any]], name_a: str, name_b: str, *, point_a: float | None = None, point_b: float | None = None) -> tuple[float, float] | None:
    a = b = None
    for row in outcomes:
        name = str(row.get("name") or ""); point = _num(row.get("point"))
        if name == name_a and (point_a is None or point == point_a): a = _num(row.get("price"))
        if name == name_b and (point_b is None or point == point_b): b = _num(row.get("price"))
    if a is None or b is None or a <= 1 or b <= 1: return None
    return float(a), float(b)


def sharp_consensus(event: dict[str, Any], *, total_line: float, as_of: Any, max_age_minutes: float = DEFAULT_MAX_MARKET_AGE_MINUTES) -> dict[str, Any]:
    home, away = str(event.get("home_team") or ""), str(event.get("away_team") or ""); accum: dict[str, list[tuple[float, float, str]]] = {"home_ml": [], "home_minus_1_5": [], "away_minus_1_5": [], "over": []}; book_rows: list[dict[str, Any]] = []
    for book in event.get("bookmakers") or []:
        key = str(book.get("key") or ""); weight = SHARP_BOOK_WEIGHTS.get(key)
        if weight is None: continue
        freshness = _book_freshness(book, as_of, max_age_minutes)
        if freshness != "VERIFIED_FRESH": continue
        used: list[str] = []
        pair = _price_pair(_market_outcomes(book, "h2h"), home, away)
        if pair:
            ph, _pa, _ = _fair_pair(*pair); accum["home_ml"].append((ph, weight, key)); used.append("ML")
        spreads = _market_outcomes(book, "spreads")
        pair = _price_pair(spreads, home, away, point_a=-1.5, point_b=+1.5)
        if pair:
            phm, _pap, _ = _fair_pair(*pair); accum["home_minus_1_5"].append((phm, weight, key)); used.append("RL_HOME")
        pair = _price_pair(spreads, away, home, point_a=-1.5, point_b=+1.5)
        if pair:
            pam, _php, _ = _fair_pair(*pair); accum["away_minus_1_5"].append((pam, weight, key)); used.append("RL_AWAY")
        totals = [r for r in _market_outcomes(book, "totals") if _num(r.get("point")) == float(total_line)]; pair = _price_pair(totals, "Over", "Under")
        if pair:
            po, _pu, _ = _fair_pair(*pair); accum["over"].append((po, weight, key)); used.append("TOTAL")
        if used: book_rows.append({"bookmaker": key, "weight": weight, "freshness": freshness, "markets": used})
    selections: dict[str, Any] = {}
    for key, rows in accum.items():
        p = _weighted_consensus(rows)
        if p is not None: selections[key] = {"fair_probability": p, "source_count": len(rows), "books": [b for _p, _w, b in rows]}
    for left, right in (("home_ml", "away_ml"), ("home_minus_1_5", "away_plus_1_5"), ("away_minus_1_5", "home_plus_1_5"), ("over", "under")):
        if left in selections: selections[right] = {"fair_probability": 1 - selections[left]["fair_probability"], "source_count": selections[left]["source_count"], "books": list(selections[left]["books"])}
    required = {"home_ml", "away_ml", "over", "under"}
    return {"schema": "pulsar-v14-sharp-consensus-v1", "market_probability_used_as_feature": False, "benchmark_only": True, "actionable": required <= set(selections) and bool(book_rows), "freshness_verified": bool(book_rows), "total_line": float(total_line), "selections": selections, "books": book_rows}
