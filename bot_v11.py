#!/usr/bin/env python3
"""MLB Betting Bot V11 predictive wrapper.

V11 deliberately keeps the validated V10.0.15 baseball engine intact and
changes only the market-benchmark / observability layer. The goal is to make
market comparison more predictive without contaminating the independent
baseball model with French execution prices.

Key principles:
- the V10.0.15 baseball probability remains the independent model;
- Winamax remains execution/information only;
- the reference market is a de-vigged, freshness-weighted sharp consensus;
- bookmaker-level benchmark probabilities are journaled for later validation;
- learned bookmaker weights activate only after enough settled V11 samples;
- a model+sharp ensemble is recorded in shadow, not used for official picks
  until point-in-time evidence proves it improves calibration.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from pathlib import Path
from statistics import median

import bot as core

V11_VERSION = "11.0.0"
BENCHMARK_VERSION = "sharp-consensus-v1"
SELECTION_VERSION = "official-selector-lab-v6+sharp-benchmark-v1"

DEFAULT_SHARP_BOOKS = (
    "pinnacle",
    "betfair_ex_eu",
    "matchbook",
    "betonlineag",
)
DEFAULT_EXECUTION_BOOKS = ("winamax_fr",)

# Priors stay deliberately close to 1.0. They only break ties until enough
# settled V11 observations exist to learn small empirical adjustments.
DEFAULT_BASE_WEIGHTS = {
    "pinnacle": 1.15,
    "betfair_ex_eu": 1.10,
    "matchbook": 1.05,
    "betonlineag": 0.95,
}

MIN_BOOK_SAMPLES = max(40, int(os.getenv("V11_BOOK_WEIGHT_MIN_N", "80") or 80))
MAX_MARKET_AGE_MIN = max(15.0, float(os.getenv("V11_MAX_MARKET_AGE_MIN", "90") or 90))
ROBUST_SCALE = max(0.015, float(os.getenv("V11_CONSENSUS_ROBUST_SCALE", "0.035") or .035))
SHADOW_MODEL_WEIGHT = core.clamp(float(os.getenv("V11_SHADOW_MODEL_WEIGHT", "0.55") or .55), .25, .80)

_BOOK_WEIGHT_CACHE = None
_ORIGINAL_BUILD_SNAPSHOT = core.build_snapshot
_ORIGINAL_MAKE_RUN_ROWS = core.v1010_make_run_rows


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return tuple(dict.fromkeys(x.strip() for x in raw.split(",") if x.strip()))


def sharp_books() -> tuple[str, ...]:
    return _csv_env("V11_SHARP_BOOKS", DEFAULT_SHARP_BOOKS)


def execution_books() -> tuple[str, ...]:
    return _csv_env("V11_EXECUTION_BOOKS", DEFAULT_EXECUTION_BOOKS)


def requested_books() -> tuple[str, ...]:
    explicit = os.getenv("ODDS_BOOKMAKERS", "").strip()
    if explicit:
        return tuple(dict.fromkeys(x.strip() for x in explicit.split(",") if x.strip()))
    return tuple(dict.fromkeys((*execution_books(), *sharp_books())))


def _base_weight(book: str) -> float:
    env_name = "V11_WEIGHT_" + "".join(c if c.isalnum() else "_" for c in book.upper())
    if os.getenv(env_name):
        try:
            return core.clamp(float(os.getenv(env_name)), .50, 1.50)
        except Exception:
            pass
    return DEFAULT_BASE_WEIGHTS.get(book, 1.0)


def _journal_rows() -> list[dict]:
    path = Path(getattr(core, "JOURNAL_FILE", "data/mlb_bet_journal_v1.jsonl"))
    if not path.exists():
        return []
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("result") not in ("W", "L") or row.get("market") == "COMBO":
                continue
            if row.get("benchmark_version") != BENCHMARK_VERSION:
                continue
            if not row.get("benchmark_components"):
                continue
            rows.append(row)
    except Exception as exc:
        logging.warning("V11 benchmark learning disabled: journal unreadable: %s", exc)
        return []
    return rows


def learned_book_weights() -> dict[str, dict]:
    """Learn small bookmaker-weight adjustments from settled V11 samples."""
    global _BOOK_WEIGHT_CACHE
    if _BOOK_WEIGHT_CACHE is not None:
        return _BOOK_WEIGHT_CACHE

    latest = {}
    for row in _journal_rows():
        key = (
            str(row.get("game_pk")),
            str(row.get("market")),
            core.norm_name(row.get("pick")),
            None if row.get("point") is None else round(core.num(row.get("point")), 3),
        )
        old = latest.get(key)
        if old is None or str(row.get("analyzed_at", "")) > str(old.get("analyzed_at", "")):
            latest[key] = row

    losses: dict[str, list[float]] = {}
    for row in latest.values():
        y = 1.0 if row.get("result") == "W" else 0.0
        for comp in row.get("benchmark_components") or []:
            book = str(comp.get("book") or "")
            if book not in sharp_books() or comp.get("p") is None:
                continue
            p = core.clamp(core.num(comp.get("p"), .5), .001, .999)
            losses.setdefault(book, []).append((p - y) ** 2)

    qualified = {b: sum(v) / len(v) for b, v in losses.items() if len(v) >= MIN_BOOK_SAMPLES}
    center = median(qualified.values()) if qualified else None
    out = {}
    for book in sharp_books():
        n = len(losses.get(book, []))
        brier = sum(losses[book]) / n if n else None
        multiplier = 1.0
        if center is not None and book in qualified:
            # 0.01 Brier better/worse than the peer median -> about 8% adjustment.
            multiplier = core.clamp(1.0 + (center - qualified[book]) * 8.0, .85, 1.15)
        out[book] = {
            "n": n,
            "brier": brier,
            "multiplier": multiplier,
            "weight": _base_weight(book) * multiplier,
            "learned": book in qualified,
        }
    _BOOK_WEIGHT_CACHE = out
    return out


def _market_age_minutes(book: dict, market: dict) -> float:
    try:
        stamp = market.get("last_update", book.get("last_update"))
        if not stamp:
            return 10.0
        return max(0.0, (core.NOW - core.parse_dt(stamp)).total_seconds() / 60.0)
    except Exception:
        return 10.0


def _freshness_weight(age_min: float) -> float:
    return max(.30, math.exp(-age_min / 75.0))


def _weighted_mean(items: list[dict]) -> float:
    den = sum(core.num(x.get("weight"), 0) for x in items)
    return sum(core.num(x.get("p"), .5) * core.num(x.get("weight"), 0) for x in items) / den if den > 0 else .5


def _weighted_std(items: list[dict], center: float) -> float:
    den = sum(core.num(x.get("weight"), 0) for x in items)
    if den <= 0:
        return 0.0
    return math.sqrt(sum(core.num(x.get("weight"), 0) * (core.num(x.get("p"), center) - center) ** 2 for x in items) / den)


def sharp_consensus_from_rows(rows, name, point=None, market="h2h") -> dict:
    learned = learned_book_weights()
    comps = []
    allowed = set(sharp_books())
    for book, mk in rows:
        key = str(book.get("key") or "")
        if key not in allowed:
            continue
        p = core.fair_book_probability(mk.get("outcomes", []), name, point, market)
        if p is None:
            continue
        age = _market_age_minutes(book, mk)
        if age > MAX_MARKET_AGE_MIN:
            continue
        skill = learned.get(key, {})
        prior = _base_weight(key)
        empirical = core.num(skill.get("multiplier"), 1.0)
        freshness = _freshness_weight(age)
        comps.append({
            "book": key,
            "p": core.clamp(p, .001, .999),
            "age_min": round(age, 2),
            "prior_weight": round(prior, 4),
            "empirical_multiplier": round(empirical, 4),
            "freshness_weight": round(freshness, 4),
            "learned_n": int(core.num(skill.get("n"), 0)),
            "learned_brier": round(core.num(skill.get("brier"), 0), 6) if skill.get("brier") is not None else None,
        })

    if not comps:
        return {
            "p": None,
            "n": 0,
            "disp": None,
            "age_min": None,
            "source": BENCHMARK_VERSION,
            "books": [],
            "components": [],
            "effective_n": 0.0,
        }

    med = median([x["p"] for x in comps])
    for c in comps:
        # One outlier/stale feed cannot dominate the benchmark.
        distance = abs(c["p"] - med)
        robust = 1.0 / (1.0 + (distance / ROBUST_SCALE) ** 2)
        c["robust_weight"] = round(robust, 4)
        c["weight"] = c["prior_weight"] * c["empirical_multiplier"] * c["freshness_weight"] * robust

    p = core.clamp(_weighted_mean(comps), .001, .999)
    disp = _weighted_std(comps, p) if len(comps) > 1 else 0.0
    ages = [c["age_min"] for c in comps]
    weights = [core.num(c.get("weight"), 0) for c in comps]
    sw = sum(weights)
    effective_n = (sw * sw / sum(w * w for w in weights)) if sw > 0 and any(w > 0 for w in weights) else 0.0
    for c in comps:
        c["weight"] = round(core.num(c.get("weight"), 0), 6)

    return {
        "p": p,
        "n": len(comps),
        "disp": disp,
        "age_min": median(ages),
        "source": BENCHMARK_VERSION,
        "books": [c["book"] for c in comps],
        "components": comps,
        "effective_n": round(effective_n, 3),
    }


def sharp_consensus(event, market, name, point=None) -> dict:
    return sharp_consensus_from_rows(core.market_rows(event, market), name, point, market)


def v11_consensus_rows(rows, name, point=None, market="totals") -> dict:
    return sharp_consensus_from_rows(rows, name, point, market)


def _benchmark_for_row(result: dict, row: dict) -> dict:
    market = str(row.get("market") or "")
    api_market = {"ML": "h2h", "RUNLINE": "spreads", "TOTAL": "totals"}.get(market)
    if not api_market:
        return {}
    if market == "TOTAL":
        try:
            rows = core.v1011_total_rows(result)
            return sharp_consensus_from_rows(rows, row.get("pick"), row.get("point"), "totals")
        except Exception:
            pass
    return sharp_consensus(result.get("event") or {}, api_market, row.get("pick"), row.get("point"))


def v11_build_snapshot(result, rec):
    snap = _ORIGINAL_BUILD_SNAPSHOT(result, rec)
    con = result.get("con") or {}
    snap["benchmark_version"] = BENCHMARK_VERSION
    snap["sharp_consensus_home"] = round(core.num(con.get("p"), 0), 6) if con.get("p") is not None else None
    snap["sharp_consensus_books"] = list(con.get("books") or [])
    snap["sharp_consensus_components"] = list(con.get("components") or [])
    snap["sharp_consensus_effective_n"] = con.get("effective_n")
    p_model = core.num(result.get("p_model"), .5)
    p_market = con.get("p")
    snap["shadow_model_sharp_ensemble"] = (
        round(core.clamp(SHADOW_MODEL_WEIGHT * p_model + (1 - SHADOW_MODEL_WEIGHT) * core.num(p_market, .5)), 6)
        if p_market is not None else None
    )
    snap["shadow_model_weight"] = SHADOW_MODEL_WEIGHT
    return snap


def v11_make_run_rows(results, run_id=None, analyzed_at=None):
    rows = _ORIGINAL_MAKE_RUN_ROWS(results, run_id, analyzed_at)
    by_game = {str(r.get("game_pk")): r for r in results or []}
    for row in rows:
        row["benchmark_version"] = BENCHMARK_VERSION
        row["bot_wrapper_version"] = V11_VERSION
        if row.get("market") == "COMBO" or row.get("game_pk") is None:
            continue
        result = by_game.get(str(row.get("game_pk")))
        if not result:
            continue
        bm = _benchmark_for_row(result, row)
        row["benchmark_probability"] = round(core.num(bm.get("p"), 0), 6) if bm.get("p") is not None else None
        row["benchmark_refs"] = int(core.num(bm.get("n"), 0))
        row["benchmark_dispersion"] = round(core.num(bm.get("disp"), 0), 6) if bm.get("disp") is not None else None
        row["benchmark_effective_n"] = bm.get("effective_n")
        row["benchmark_books"] = list(bm.get("books") or [])
        row["benchmark_components"] = list(bm.get("components") or [])
        p_model = core.num(row.get("p_effective", row.get("p_model_raw")), .5)
        if bm.get("p") is not None:
            p_bm = core.num(bm.get("p"), .5)
            row["shadow_model_sharp_ensemble"] = round(core.clamp(SHADOW_MODEL_WEIGHT * p_model + (1 - SHADOW_MODEL_WEIGHT) * p_bm), 6)
            row["shadow_model_weight"] = SHADOW_MODEL_WEIGHT
        else:
            row["shadow_model_sharp_ensemble"] = None
            row["shadow_model_weight"] = SHADOW_MODEL_WEIGHT
    return rows


def _shadow_metrics_from_journal() -> dict:
    path = Path(getattr(core, "JOURNAL_FILE", "data/mlb_bet_journal_v1.jsonl"))
    if not path.exists():
        return {"n": 0}
    latest = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("benchmark_version") != BENCHMARK_VERSION or r.get("result") not in ("W", "L"):
                continue
            if r.get("market") != "ML" or r.get("shadow_model_sharp_ensemble") is None:
                continue
            key = str(r.get("game_pk"))
            if key not in latest or str(r.get("analyzed_at", "")) > str(latest[key].get("analyzed_at", "")):
                latest[key] = r
    except Exception:
        return {"n": 0}
    rows = list(latest.values())
    if not rows:
        return {"n": 0}
    ys = [1.0 if r.get("result") == "W" else 0.0 for r in rows]
    model = [core.clamp(core.num(r.get("p_effective"), .5), .001, .999) for r in rows]
    blend = [core.clamp(core.num(r.get("shadow_model_sharp_ensemble"), .5), .001, .999) for r in rows]
    market = [core.clamp(core.num(r.get("benchmark_probability"), .5), .001, .999) for r in rows]
    def brier(ps):
        return sum((p-y)**2 for p, y in zip(ps, ys)) / len(ys)
    return {"n": len(rows), "brier_model": brier(model), "brier_blend": brier(blend), "brier_market": brier(market)}


def install_v11() -> None:
    # Baseball feature/model versions stay unchanged in V11.0.0. This is a
    # benchmark improvement, not an unvalidated rewrite of the run engine.
    core.VERSION = V11_VERSION
    core.SELECTION_VERSION = SELECTION_VERSION
    core.BOOKMAKERS = ",".join(requested_books())
    core.REF_BOOKS = set(sharp_books())
    core.consensus = sharp_consensus
    core.v1011_consensus_rows = v11_consensus_rows
    core.build_snapshot = v11_build_snapshot
    core.v1010_make_run_rows = v11_make_run_rows

    learned = learned_book_weights()
    logging.info(
        "V11 SHARP BENCHMARK | books=%s | execution=%s | requested=%s",
        ",".join(sharp_books()), ",".join(execution_books()), core.BOOKMAKERS,
    )
    for book in sharp_books():
        s = learned.get(book, {})
        logging.info(
            "V11 BOOK WEIGHT | %s weight=%.3f learned=%s n=%d brier=%s",
            book, core.num(s.get("weight"), _base_weight(book)), bool(s.get("learned")),
            int(core.num(s.get("n"), 0)),
            f"{core.num(s.get('brier')):.4f}" if s.get("brier") is not None else "-",
        )
    shadow = _shadow_metrics_from_journal()
    if shadow.get("n", 0):
        logging.info(
            "V11 SHADOW ENSEMBLE | n=%d Brier model=%.4f sharp=%.4f blend=%.4f (NOT active)",
            shadow["n"], shadow["brier_model"], shadow["brier_market"], shadow["brier_blend"],
        )


def v11_self_test() -> None:
    old_cache = globals().get("_BOOK_WEIGHT_CACHE")
    globals()["_BOOK_WEIGHT_CACHE"] = {
        b: {"n": 0, "brier": None, "multiplier": 1.0, "weight": _base_weight(b), "learned": False}
        for b in sharp_books()
    }
    try:
        event = {
            "bookmakers": [
                {"key": "pinnacle", "last_update": core.NOW.isoformat(), "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 1.80}, {"name": "A", "price": 2.10}]}]},
                {"key": "betfair_ex_eu", "last_update": core.NOW.isoformat(), "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 1.82}, {"name": "A", "price": 2.08}]}]},
                {"key": "winamax_fr", "last_update": core.NOW.isoformat(), "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 1.55}, {"name": "A", "price": 2.30}]}]},
            ]
        }
        c = sharp_consensus(event, "h2h", "H")
        assert c["source"] == BENCHMARK_VERSION
        assert c["n"] == 2
        assert "winamax_fr" not in c["books"]
        assert .52 < c["p"] < .56
        assert c["effective_n"] > 1.5
        assert all(x.get("weight", 0) > 0 for x in c["components"])
        assert "winamax_fr" in requested_books()
        assert set(sharp_books()).issubset(set(requested_books()))
    finally:
        globals()["_BOOK_WEIGHT_CACHE"] = old_cache
    print("SELF-TEST MLB BETTING BOT V11.0.0 OK")


def main() -> None:
    install_v11()
    core.main()


if __name__ == "__main__":
    try:
        if "--self-test" in sys.argv:
            # First prove the frozen V10.0.15 regression chain still passes.
            core.v10_self_test()
            install_v11()
            v11_self_test()
        else:
            main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        logging.exception("ERREUR FATALE V11")
        raise
