from __future__ import annotations

import math
import os
from datetime import datetime, timezone

_INSTALLED = False
_ORIGINALS = {}
_core = _market = _engine = _config = None


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _parse_dt(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _event_is_target_date(event):
    dt = _parse_dt((event or {}).get("commence_time"))
    if dt is None:
        return False
    try:
        return dt.astimezone(_core.PARIS).date().isoformat() == str(_core.TARGET_DATE)
    except Exception:
        return False


def _merge_alternate_market(event, extra):
    if not isinstance(extra, dict):
        return event
    by_key = {str(b.get("key")): b for b in event.get("bookmakers") or []}
    for alt_book in extra.get("bookmakers") or []:
        bkey = str(alt_book.get("key") or "")
        if not bkey:
            continue
        dst = by_key.get(bkey)
        if dst is None:
            dst = {
                "key": alt_book.get("key"),
                "title": alt_book.get("title"),
                "last_update": alt_book.get("last_update") or alt_book.get("lastUpdate"),
                "markets": [],
            }
            event.setdefault("bookmakers", []).append(dst)
            by_key[bkey] = dst
        existing = {m.get("key"): m for m in dst.get("markets") or []}
        for alt_market in alt_book.get("markets") or []:
            if alt_market.get("key") != "alternate_spreads":
                continue
            if "alternate_spreads" in existing:
                existing["alternate_spreads"].clear()
                existing["alternate_spreads"].update(alt_market)
            else:
                dst.setdefault("markets", []).append(alt_market)
    event["alternate_runlines_fetched"] = True
    return event


def odds_api_with_alternate_runlines():
    events = _ORIGINALS["core.odds_api"]()
    if str(os.getenv("V1231_ENABLE_ALT_RUNLINES", "1")).lower() not in {"1", "true", "yes"}:
        return events
    params = {
        "apiKey": _core.ODDS_KEY or "replay",
        "bookmakers": ",".join(_core.BOOKMAKERS),
        "markets": "alternate_spreads",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    for event in events or []:
        event_id = event.get("id")
        if not event_id or not _event_is_target_date(event):
            continue
        try:
            extra = _core.http_json(
                f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
                params,
            ) or {}
            _merge_alternate_market(event, extra)
        except Exception as exc:
            # Additional markets are optional coverage. Never fail the whole production run.
            event["alternate_runlines_fetched"] = False
            event["alternate_runlines_error"] = type(exc).__name__
            _core.logging.warning("Alternate run lines unavailable event=%s: %s", event_id, exc)
    return events


def _fresh_market_age(book, market):
    now = _parse_dt(_core.replay_as_of()) if _core.replay_as_of() else datetime.now(timezone.utc)
    stamp = market.get("last_update") or market.get("lastUpdate") or book.get("last_update") or book.get("lastUpdate")
    updated = _parse_dt(stamp)
    if updated is None:
        return None
    return max(0.0, (now-updated).total_seconds()/60.0)


def fresh_winamax_price_with_alternates(event, market_name, name, point=None):
    price = _ORIGINALS["core.winamax_price"](event, market_name, name, point)
    if price is not None or market_name != "RUNLINE":
        return price
    max_age = float(getattr(_config, "V123_MAX_WINAMAX_AGE_MIN", 15.0))
    candidates = []
    for book in event.get("bookmakers") or []:
        if book.get("key") != _core.WINAMAX_KEY:
            continue
        for market in book.get("markets") or []:
            if market.get("key") != "alternate_spreads":
                continue
            age = _fresh_market_age(book, market)
            if age is None or age > max_age:
                continue
            for outcome in market.get("outcomes") or []:
                if _norm(outcome.get("name")) != _norm(name):
                    continue
                if point is not None and abs(_num(outcome.get("point"), 999)-_num(point)) > 1e-6:
                    continue
                p = _num(outcome.get("price"), 0)
                if p > 1:
                    candidates.append((age, p))
    return min(candidates, key=lambda x: x[0])[1] if candidates else None


def _alternate_sharp_consensus(event, name, point, as_of=None):
    vals, books, ages, excluded = [], [], [], []
    for book in event.get("bookmakers") or []:
        bkey = book.get("key")
        if bkey not in _core.SHARP_BOOKS:
            continue
        market = next((m for m in book.get("markets") or [] if m.get("key") == "alternate_spreads"), None)
        if not market:
            continue
        age = _market._age_minutes(book, market, as_of)
        if age is None:
            excluded.append({"book": bkey, "reason": "timestamp_missing"})
            continue
        if age > _config.MAX_SHARP_AGE_MIN:
            excluded.append({"book": bkey, "reason": "stale", "age_min": age})
            continue
        target = next((o for o in market.get("outcomes") or []
                       if _norm(o.get("name")) == _norm(name)
                       and o.get("point") is not None
                       and abs(_num(o.get("point"))-_num(point)) <= 1e-6), None)
        opposite = next((o for o in market.get("outcomes") or []
                         if _norm(o.get("name")) != _norm(name)
                         and o.get("point") is not None
                         and abs(_num(o.get("point"))+_num(point)) <= 1e-6), None)
        if target is None or opposite is None:
            excluded.append({"book": bkey, "reason": "complementary_pair_missing"})
            continue
        tp = _market._effective_decimal(target.get("price"), bkey)
        op = _market._effective_decimal(opposite.get("price"), bkey)
        if tp is None or op is None:
            excluded.append({"book": bkey, "reason": "invalid_price"})
            continue
        inv_t, inv_o = 1/tp, 1/op
        s = inv_t+inv_o
        if s <= 0:
            continue
        p = inv_t/s
        freshness = max(.10, 1-age/max(1.0, _config.MAX_SHARP_AGE_MIN)*.90)
        book_weight = max(.25, _num(_config.SHARP_BOOK_WEIGHTS.get(bkey), 1.0))
        weight = freshness*book_weight
        vals.append((p, weight))
        books.append(bkey)
        ages.append(age)
    if not vals:
        return {"p": None, "n": 0, "books": [], "dispersion": None, "max_age_min": None,
                "robustness": 0.0, "effective_n": 0.0, "excluded": excluded, "as_of": as_of}
    wsum = sum(w for _, w in vals)
    p = sum(v*w for v, w in vals)/wsum
    variance = sum(w*(v-p)**2 for v, w in vals)/wsum if wsum else 0.0
    dispersion = math.sqrt(max(0.0, variance))
    robustness = max(.20, min(1.0, 1-dispersion/max(.001, _config.SHARP_DISAGREEMENT_SCALE)))
    sumw2 = sum(w*w for _, w in vals)
    effective_n = (wsum*wsum/sumw2) if sumw2 else 0.0
    return {"p": p, "n": len(vals), "books": books, "dispersion": dispersion,
            "max_age_min": max(ages) if ages else None, "robustness": robustness,
            "effective_n": effective_n, "excluded": excluded, "as_of": as_of,
            "market_source": "alternate_spreads"}


def sharp_consensus_with_alternates(event, market, name, point=None, as_of=None):
    standard = _ORIGINALS["market.sharp_consensus"](event, market, name, point, as_of)
    if market != "RUNLINE" or standard.get("p") is not None:
        return standard
    return _alternate_sharp_consensus(event, name, point, as_of)


def _candidate_home_points(event, home):
    points = set()
    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") not in {"spreads", "alternate_spreads"}:
                continue
            for outcome in market.get("outcomes") or []:
                if _norm(outcome.get("name")) != _norm(home) or outcome.get("point") is None:
                    continue
                point = round(_num(outcome.get("point")), 2)
                if abs(abs(point)-1.5) <= 1e-6:
                    points.add(point)
    return sorted(points)


def analysis_points_with_alternates(event, key, home=None, as_of=None):
    if key != "spreads" or not home:
        return _ORIGINALS["engine._analysis_points"](event, key, home, as_of)
    away = str(event.get("away_team") or "") if _norm(event.get("home_team")) == _norm(home) else str(event.get("home_team") or "")
    points = []
    has_winamax = False
    has_sharp = False
    for point in _candidate_home_points(event, home):
        home_price = _core.winamax_price(event, "RUNLINE", home, point)
        away_price = _core.winamax_price(event, "RUNLINE", away, -point) if away else None
        sh_home = _market.sharp_consensus(event, "RUNLINE", home, point, as_of=as_of)
        sh_away = _market.sharp_consensus(event, "RUNLINE", away, -point, as_of=as_of) if away else {"n": 0}
        executable_pair = bool(home_price and away_price)
        sharp_pair = sh_home.get("n", 0) > 0 and sh_away.get("n", 0) > 0
        if executable_pair or sharp_pair:
            points.append(point)
            has_winamax = has_winamax or executable_pair
            has_sharp = has_sharp or sharp_pair
    if points:
        source = "mixed" if has_winamax and has_sharp else "winamax" if has_winamax else "sharp"
        return sorted(set(points)), source
    return _ORIGINALS["engine._analysis_points"](event, key, home, as_of)


def analyze_with_alternate_line_sources(game, event, as_of=None):
    result = _ORIGINALS["engine.analyze"](game, event, as_of=as_of)
    sources = set()
    for option in result.get("options") or []:
        if option.get("market") != "RUNLINE":
            continue
        price = _core.winamax_price(event, "RUNLINE", option.get("name"), option.get("point"))
        sharp = _market.sharp_consensus(event, "RUNLINE", option.get("name"), option.get("point"), as_of=as_of)
        if price and price > 1:
            option["line_source"] = "winamax"
            option["execution_available"] = True
            sources.add("winamax")
        elif sharp.get("p") is not None:
            option["line_source"] = "sharp"
            option["execution_available"] = False
            sources.add("sharp")
    runline = (result.get("analysis_lines") or {}).get("RUNLINE")
    if isinstance(runline, dict):
        runline["alternate_spreads_enabled"] = True
        runline["source"] = "mixed" if len(sources) > 1 else next(iter(sources), runline.get("source"))
        runline["points"] = sorted({o.get("point") for o in result.get("options") or []
                                    if o.get("market") == "RUNLINE"
                                    and _norm(o.get("name")) == _norm(result.get("ctx", {}).get("home"))
                                    and o.get("point") is not None})
    return result


def install():
    global _INSTALLED, _core, _market, _engine, _config
    if _INSTALLED:
        return True
    from . import config, core, market
    from . import engine_v12
    _config, _core, _market, _engine = config, core, market, engine_v12
    _ORIGINALS.update({
        "core.odds_api": core.odds_api,
        "core.winamax_price": core.winamax_price,
        "market.sharp_consensus": market.sharp_consensus,
        "engine._analysis_points": engine_v12._analysis_points,
        "engine.analyze": engine_v12.analyze,
    })
    config.VERSION = "12.3.1-alternate-runlines-v1"
    core.odds_api = odds_api_with_alternate_runlines
    core.winamax_price = fresh_winamax_price_with_alternates
    market.sharp_consensus = sharp_consensus_with_alternates
    engine_v12._analysis_points = analysis_points_with_alternates
    engine_v12.analyze = analyze_with_alternate_line_sources
    _INSTALLED = True
    return True


def installed():
    return _INSTALLED
