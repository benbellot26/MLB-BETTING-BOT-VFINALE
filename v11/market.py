from __future__ import annotations

import math
from datetime import datetime, timezone
from . import core, config


def _age_minutes(book, market=None):
    source = market or book
    s = source.get("last_update") or source.get("lastUpdate") or book.get("last_update") or book.get("lastUpdate")
    if not s:
        return None
    try:
        dt = core.parse_dt(s)
        return max(0.0, (datetime.now(timezone.utc)-dt).total_seconds()/60.0)
    except Exception:
        return None


def _effective_decimal(price, book_key):
    price = core.num(price, 0)
    if price <= 1:
        return None
    commission = max(0.0, min(.25, core.num(config.EXCHANGE_COMMISSION.get(book_key), 0)))
    return 1 + (price-1) * (1-commission)


def _line_match(market_name, outcome_point, target_point):
    if target_point is None:
        return True
    op = core.num(outcome_point, 999)
    tp = core.num(target_point, 999)
    if market_name == "RUNLINE":
        return abs(abs(op)-abs(tp)) <= 1e-6
    return abs(op-tp) <= 1e-6


def sharp_consensus(event, market, name, point=None):
    """Freshness/book-quality weighted, book-by-book de-vig consensus.

    Missing timestamps are excluded rather than treated as perfectly fresh. Exchange
    prices are commission-adjusted before implied-probability conversion.
    """
    key = {"ML": "h2h", "RUNLINE": "spreads", "TOTAL": "totals"}[market]
    vals = []
    books = []
    ages = []
    excluded = []
    for b in event.get("bookmakers") or []:
        bkey = b.get("key")
        if bkey not in core.SHARP_BOOKS:
            continue
        m = next((x for x in b.get("markets") or [] if x.get("key") == key), None)
        if not m:
            continue
        age = _age_minutes(b, m)
        if age is None:
            excluded.append({"book": bkey, "reason": "timestamp_missing"})
            continue
        if age > config.MAX_SHARP_AGE_MIN:
            excluded.append({"book": bkey, "reason": "stale", "age_min": age})
            continue
        relevant = []
        for o in m.get("outcomes") or []:
            if not _line_match(market, o.get("point"), point):
                continue
            ep = _effective_decimal(o.get("price"), bkey)
            if ep is not None:
                relevant.append((o, ep))
        if len(relevant) < 2:
            excluded.append({"book": bkey, "reason": "incomplete_market"})
            continue
        target = next((pair for pair in relevant
                       if core.norm_name(pair[0].get("name")) == core.norm_name(name)
                       and (point is None or market != "RUNLINE" or abs(core.num(pair[0].get("point"))-core.num(point)) < 1e-6)), None)
        if target is None:
            excluded.append({"book": bkey, "reason": "target_missing"})
            continue
        inv = [1/p for _, p in relevant]
        s = sum(inv)
        if s <= 0:
            continue
        target_idx = relevant.index(target)
        p = inv[target_idx] / s
        freshness = max(.10, 1-age/max(1.0, config.MAX_SHARP_AGE_MIN)*.90)
        book_weight = max(.25, core.num(config.SHARP_BOOK_WEIGHTS.get(bkey), 1.0))
        weight = freshness * book_weight
        vals.append((p, weight))
        books.append(bkey)
        ages.append(age)

    if not vals:
        return {
            "p": None, "n": 0, "books": [], "dispersion": None,
            "max_age_min": None, "robustness": 0.0, "effective_n": 0.0,
            "excluded": excluded,
        }
    wsum = sum(w for _, w in vals)
    p = sum(v*w for v, w in vals) / wsum
    variance = sum(w*(v-p)**2 for v, w in vals) / wsum if wsum else 0.0
    disp = math.sqrt(max(0.0, variance))
    robustness = max(.20, min(1.0, 1-disp/max(.001, config.SHARP_DISAGREEMENT_SCALE)))
    sumw2 = sum(w*w for _, w in vals)
    effective_n = (wsum*wsum/sumw2) if sumw2 else 0.0
    return {
        "p": p, "n": len(vals), "books": books, "dispersion": disp,
        "max_age_min": max(ages) if ages else None, "robustness": robustness,
        "effective_n": effective_n, "excluded": excluded,
    }


def blend_weight(consensus):
    n_eff = core.num(consensus.get("effective_n"), 0)
    if n_eff <= 0:
        return 0.0
    coverage = min(1.0, n_eff/3.0)
    robustness = max(.20, min(1.0, core.num(consensus.get("robustness"), .2)))
    return max(config.MIN_MARKET_BLEND_WEIGHT,
               min(config.MAX_MARKET_BLEND_WEIGHT,
                   config.MIN_MARKET_BLEND_WEIGHT +
                   (config.MAX_MARKET_BLEND_WEIGHT-config.MIN_MARKET_BLEND_WEIGHT)*coverage*robustness))
