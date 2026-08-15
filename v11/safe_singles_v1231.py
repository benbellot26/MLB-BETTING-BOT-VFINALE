from __future__ import annotations

import math
import os

_INSTALLED = False
_ORIGINAL_VALUE_GATE = None
_ORIGINAL_ANALYZE = None
_ORIGINAL_ALLOCATE = None
_config = _selector = _engine = _core = _market = None


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _exact_point(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(_num(a, 999)-_num(b, 999)) <= 1e-6


def _reference_market(event, rec, as_of=None):
    """Return a robust fresh sharp reference quote for the exact option.

    Selection must not depend on Winamax availability. We use only configured
    sharp books, exact side/point matching and point-in-time freshness. When at
    least two fresh sharp quotes exist, the second-best effective price is used
    so one isolated outlier cannot manufacture value. With one quote, that
    single quote is retained but DQ/refs gates still apply downstream.
    """
    market_name = str(rec.get("market") or "").upper()
    keys = {
        "ML": {"h2h"},
        "RUNLINE": {"spreads", "alternate_spreads"},
        "TOTAL": {"totals"},
    }.get(market_name, set())
    if not keys:
        return {"price": None, "best_price": None, "book": None, "quote_count": 0, "source": "sharp_unavailable"}

    per_book = {}
    for book in (event or {}).get("bookmakers") or []:
        bkey = str(book.get("key") or "")
        if bkey not in _core.SHARP_BOOKS:
            continue
        for market in book.get("markets") or []:
            if market.get("key") not in keys:
                continue
            age = _market._age_minutes(book, market, as_of)
            if age is None or age > _config.MAX_SHARP_AGE_MIN:
                continue
            for outcome in market.get("outcomes") or []:
                if _norm(outcome.get("name")) != _norm(rec.get("name")):
                    continue
                if market_name in {"RUNLINE", "TOTAL"} and not _exact_point(outcome.get("point"), rec.get("point")):
                    continue
                price = _market._effective_decimal(outcome.get("price"), bkey)
                if price is None or price <= 1:
                    continue
                prev = per_book.get(bkey)
                candidate = {"book": bkey, "price": price, "age_min": age, "market_key": market.get("key")}
                if prev is None or price > prev["price"]:
                    per_book[bkey] = candidate

    quotes = sorted(per_book.values(), key=lambda x: (x["price"], -x["age_min"]), reverse=True)
    if not quotes:
        return {"price": None, "best_price": None, "book": None, "quote_count": 0, "source": "sharp_unavailable"}
    best = quotes[0]
    robust = quotes[1] if len(quotes) >= 2 else best
    return {
        "price": round(robust["price"], 4),
        "best_price": round(best["price"], 4),
        "book": robust["book"],
        "best_book": best["book"],
        "age_min": round(robust["age_min"], 3),
        "quote_count": len(quotes),
        "source": "sharp_second_best" if len(quotes) >= 2 else "sharp_single",
        "market_key": robust["market_key"],
    }


def analyze_with_reference_market(game, event, as_of=None):
    result = _ORIGINAL_ANALYZE(game, event, as_of=as_of)
    for rec in result.get("options") or []:
        rec["reference_market"] = _reference_market(event, rec, as_of)
    return result


def _confidence_floor(rec):
    market_name = str(rec.get("market") or "ML").upper()
    if market_name == "RUNLINE":
        return float(getattr(_config, "V123_MIN_CONFIDENCE_RUNLINE", .55))
    if market_name == "TOTAL":
        return float(getattr(_config, "V123_MIN_CONFIDENCE_TOTAL", .58))
    return float(getattr(_config, "V123_MIN_CONFIDENCE_ML", .58))


def value_gate_with_reference_market(rec):
    """Professional informational selector independent of Winamax execution.

    A candidate must satisfy the existing conservative EV/edge/uncertainty
    requirements, a market-specific confidence floor, and a robust fresh sharp
    reference price >= 1.40. Winamax remains an execution/display quote only.
    """
    reference = rec.get("reference_market") or {}
    price = _num(reference.get("price"), 0.0)
    minimum = _selector.required_price(rec)
    push = max(0.0, min(.95, _num(rec.get("p_push"), 0)))
    raw_p = max(.001, min(.999, _num(rec.get("p_effective"), .5)))
    p_cons = _selector.conservative_probability(rec)
    raw_win = _num(rec.get("p_win"), raw_p*(1-push))
    pwin = max(0.0, min(1-push, raw_win*(p_cons/raw_p)))
    ploss = max(0.0, 1-pwin-push)
    ev = pwin*(price-1)-ploss if price > 1 else None

    price_floor = float(getattr(_config, "V123_MIN_REFERENCE_PRICE", 1.40))
    confidence_floor = _confidence_floor(rec)
    model_value_ok = bool(price > 1 and price+1e-12 >= minimum)
    price_floor_ok = bool(price + 1e-12 >= price_floor)
    confidence_ok = bool(raw_p + 1e-12 >= confidence_floor)

    p_market = rec.get("p_market")
    p_model_raw = rec.get("p_learned", rec.get("p_effective"))
    sharp_gap = None
    if p_market is not None and p_model_raw is not None:
        sharp_gap = abs(_num(p_model_raw)-_num(p_market))

    winamax_price = _num((rec.get("winamax_eval") or {}).get("price"), 0.0)
    return {
        "ok": bool(model_value_ok and price_floor_ok and confidence_ok),
        "model_value_ok": model_value_ok,
        "price_floor_ok": price_floor_ok,
        "confidence_ok": confidence_ok,
        "price": price if price > 1 else None,
        "price_source": reference.get("source"),
        "reference_book": reference.get("book"),
        "reference_best_book": reference.get("best_book"),
        "reference_best_price": reference.get("best_price"),
        "reference_quote_count": int(_num(reference.get("quote_count"), 0)),
        "winamax_price": winamax_price if winamax_price > 1 else None,
        "required_price": round(minimum, 4),
        "min_reference_price": price_floor,
        "min_official_single_price": price_floor,
        "min_confidence": confidence_floor,
        "ev_at_price": round(ev, 6) if ev is not None else None,
        "p_win": round(pwin, 6),
        "p_push": round(push, 6),
        "p_conservative": round(p_cons, 6),
        "uncertainty": round(_num(rec.get("model_uncertainty"), _config.FALLBACK_MODEL_UNCERTAINTY), 6),
        "sharp_disagreement": round(sharp_gap, 6) if sharp_gap is not None else None,
    }


def allocate_with_reference_market(*args, **kwargs):
    portfolio, chosen, combo, pool = _ORIGINAL_ALLOCATE(*args, **kwargs)
    for item in pool:
        rec, gate, dq = item["rec"], item["gate"], item["dq"]
        e = rec.get("winamax_eval") or {}
        if e.get("official_selected"):
            e["official_reason"] = (
                f"V12.3.2 value: score {item['score']:.1f}/100, DQ {dq['score']:.2f}, "
                f"EV prudent {100*_num(gate.get('ev_at_price')):+.1f}% à la cote sharp réf. {_num(gate.get('price')):.2f}"
            )
    portfolio = dict(portfolio)
    portfolio["selector_version"] = "V12.3.2-value-selection-v1"
    portfolio["selection_price_source"] = "robust fresh sharp reference; Winamax execution optional"
    return portfolio, chosen, combo, pool


def install():
    global _INSTALLED, _ORIGINAL_VALUE_GATE, _ORIGINAL_ANALYZE, _ORIGINAL_ALLOCATE
    global _config, _selector, _engine, _core, _market
    if _INSTALLED:
        return True
    from . import config, selector, core, market
    from . import engine_v12

    _config, _selector, _engine, _core, _market = config, selector, engine_v12, core, market
    config.V123_MIN_REFERENCE_PRICE = float(os.getenv("V123_MIN_REFERENCE_PRICE", "1.40") or 1.40)
    config.V123_MIN_CONFIDENCE_RUNLINE = float(os.getenv("V123_MIN_CONFIDENCE_RUNLINE", "0.55") or .55)
    config.V123_MIN_CONFIDENCE_ML = float(os.getenv("V123_MIN_CONFIDENCE_ML", "0.58") or .58)
    config.V123_MIN_CONFIDENCE_TOTAL = float(os.getenv("V123_MIN_CONFIDENCE_TOTAL", "0.58") or .58)
    config.V123_SHARP_GAP_FREE = float(os.getenv("V123_SHARP_GAP_FREE", "0.08") or .08)
    config.V123_SHARP_GAP_SCORE_PENALTY = float(os.getenv("V123_SHARP_GAP_SCORE_PENALTY", "200") or 200)
    # Backward-compatible name used by older report/test surfaces.
    config.MIN_OFFICIAL_SINGLE_PRICE = config.V123_MIN_REFERENCE_PRICE

    _ORIGINAL_VALUE_GATE = selector.value_gate
    _ORIGINAL_ANALYZE = engine_v12.analyze
    _ORIGINAL_ALLOCATE = selector.allocate
    selector.value_gate = value_gate_with_reference_market
    selector.allocate = allocate_with_reference_market
    engine_v12.analyze = analyze_with_reference_market
    config.VERSION = "12.3.2-value-selection-v1"
    _INSTALLED = True
    return True


def installed():
    return _INSTALLED
