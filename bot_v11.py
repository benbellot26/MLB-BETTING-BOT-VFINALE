#!/usr/bin/env python3
"""MLB Betting Bot V11 predictive wrapper.

V11 deliberately keeps the validated V10.0.15 baseball engine intact and
changes only the market-benchmark / observability layer.  The goal is to make
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

# Equal priors avoid hard-coding an unproven bookmaker hierarchy. Freshness and
# outlier robustness differentiate books immediately; empirical skill can only
# change weights after enough settled V11 observations.
DEFAULT_BASE_WEIGHTS = {
    "pinnacle": 1.0,
    "betfair_ex_eu": 1.0,
    "matchbook": 1.0,
    "betonlineag": 1.0,
}

MIN_BOOK_SAMPLES = max(40, int(os.getenv("V11_BOOK_WEIGHT_MIN_N", "80") or 80))
MAX_MARKET_AGE_MIN = max(15.0, float(os.getenv("V11_MAX_MARKET_AGE_MIN", "90") or 90))
ROBUST_SCALE = max(0.015, float(os.getenv("V11_CONSENSUS_ROBUST_SCALE", "0.035") or .035))
SHADOW_MODEL_WEIGHT = core.clamp(float(os.getenv("V11_SHADOW_MODEL_WEIGHT", "0.55") or .55), .25, .80)

_BOOK_WEIGHT_CACHE = None
_ORIGINAL_BUILD_SNAPSHOT = core.build_snapshot
_ORIGINAL_MAKE_RUN_ROWS = core.v1010_make_run_rows

_PHASE_RANK = {"EARLY": 1, "LATE": 2, "FINAL": 3}
_MARKET_CANON = {"h2h": "ML", "spreads": "RUNLINE", "totals": "TOTAL", "alternate_totals": "TOTAL"}


def _canonical_market(market: str) -> str:
    m = str(market or "").strip()
    return _MARKET_CANON.get(m, m.upper())


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
            if row.get("benchmark_version") != BENCHMARK_VERSION or not row.get("benchmark_components"):
                continue
            rows.append(row)
    except Exception as exc:
        logging.warning("V11 benchmark learning disabled: journal unreadable: %s", exc)
        return []
    return rows


def canonical_learning_rows(rows: list[dict], market: str | None = None) -> list[dict]:
    """One independent, model-favoured observation per game/market.

    Complementary sides and repeated manual runs must not inflate sample size.
    The closest-to-game phase wins (FINAL > LATE > EARLY), then latest timestamp.
    """
    target = _canonical_market(market) if market else None
    best = {}
    for row in rows:
        m = _canonical_market(row.get("market"))
        if target and m != target:
            continue
        if row.get("game_pk") is None or row.get("result") not in ("W", "L"):
            continue
        p = row.get("p_effective")
        if p is None or core.num(p, .5) < .5:
            continue
        key = (str(row.get("game_pk")), m)
        rank = (_PHASE_RANK.get(str(row.get("phase") or "EARLY").upper(), 0), str(row.get("analyzed_at") or ""))
        old = best.get(key)
        if old is None or rank > old[0]:
            best[key] = (rank, row)
    return [x[1] for x in sorted(best.values(), key=lambda z: z[0])]


def learned_book_weights(market: str = "ML") -> dict[str, dict]:
    """Learn small market-specific bookmaker weight adjustments.

    Skill is measured on matched observations: each book is compared with the
    mean probability of the *other* sharp books present for the same pick.
    This avoids rewarding a book merely because it happened to cover easier
    games. No adjustment activates before MIN_BOOK_SAMPLES independent rows.
    """
    global _BOOK_WEIGHT_CACHE
    canonical = _canonical_market(market)
    if _BOOK_WEIGHT_CACHE is None:
        _BOOK_WEIGHT_CACHE = {}
    if canonical in _BOOK_WEIGHT_CACHE:
        return _BOOK_WEIGHT_CACHE[canonical]

    losses: dict[str, list[float]] = {}
    gains: dict[str, list[float]] = {}
    allowed = set(sharp_books())
    for row in canonical_learning_rows(_journal_rows(), canonical):
        y = 1.0 if row.get("result") == "W" else 0.0
        comps = [(str(c.get("book") or ""), core.clamp(core.num(c.get("p"), .5), .001, .999))
                 for c in (row.get("benchmark_components") or [])
                 if str(c.get("book") or "") in allowed and c.get("p") is not None]
        if len(comps) < 2:
            continue
        for book, p_book in comps:
            peers = [p for b, p in comps if b != book]
            if not peers:
                continue
            p_peer = sum(peers) / len(peers)
            book_loss = (p_book - y) ** 2
            peer_loss = (p_peer - y) ** 2
            losses.setdefault(book, []).append(book_loss)
            gains.setdefault(book, []).append(peer_loss - book_loss)

    out = {}
    for book in sharp_books():
        n = len(losses.get(book, []))
        brier = sum(losses[book]) / n if n else None
        gain = sum(gains[book]) / n if n and book in gains else None
        learned = n >= MIN_BOOK_SAMPLES and gain is not None
        multiplier = core.clamp(1.0 + gain * 8.0, .85, 1.15) if learned else 1.0
        out[book] = {
            "market": canonical, "n": n, "brier": brier, "relative_brier_gain": gain,
            "multiplier": multiplier, "weight": _base_weight(book) * multiplier, "learned": learned,
        }
    _BOOK_WEIGHT_CACHE[canonical] = out
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
    canonical_market = _canonical_market(market)
    learned = learned_book_weights(canonical_market)
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
            "learned_market": canonical_market,
            "learned_brier": round(core.num(skill.get("brier"), 0), 6) if skill.get("brier") is not None else None,
            "relative_brier_gain": round(core.num(skill.get("relative_brier_gain"), 0), 6) if skill.get("relative_brier_gain") is not None else None,
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
    rows = [r for r in canonical_learning_rows(_journal_rows(), "ML") if r.get("shadow_model_sharp_ensemble") is not None and r.get("benchmark_probability") is not None]
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
    core.VERSION = V11_VERSION
    core.SELECTION_VERSION = SELECTION_VERSION
    core.BOOKMAKERS = ",".join(requested_books())
    core.REF_BOOKS = set(sharp_books())
    core.consensus = sharp_consensus
    core.v1011_consensus_rows = v11_consensus_rows
    core.build_snapshot = v11_build_snapshot
    core.v1010_make_run_rows = v11_make_run_rows

    logging.info(
        "V11 SHARP BENCHMARK | books=%s | execution=%s | requested=%s",
        ",".join(sharp_books()), ",".join(execution_books()), core.BOOKMAKERS,
    )
    for market in ("ML", "RUNLINE", "TOTAL"):
        learned = learned_book_weights(market)
        for book in sharp_books():
            st = learned.get(book, {})
            logging.info(
                "V11 BOOK WEIGHT | %s %s weight=%.3f learned=%s n=%d brier=%s relGain=%s",
                market, book, core.num(st.get("weight"), _base_weight(book)), bool(st.get("learned")),
                int(core.num(st.get("n"), 0)),
                f"{core.num(st.get('brier')):.4f}" if st.get("brier") is not None else "-",
                f"{core.num(st.get('relative_brier_gain')):+.4f}" if st.get("relative_brier_gain") is not None else "-",
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
        m: {b: {"market": m, "n": 0, "brier": None, "relative_brier_gain": None, "multiplier": 1.0, "weight": _base_weight(b), "learned": False} for b in sharp_books()}
        for m in ("ML", "RUNLINE", "TOTAL")
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
        synthetic = [
            {"game_pk": 1, "market": "ML", "pick": "H", "phase": "EARLY", "analyzed_at": "1", "p_effective": .62, "result": "W"},
            {"game_pk": 1, "market": "ML", "pick": "A", "phase": "EARLY", "analyzed_at": "1", "p_effective": .38, "result": "L"},
            {"game_pk": 1, "market": "ML", "pick": "H", "phase": "FINAL", "analyzed_at": "2", "p_effective": .64, "result": "W"},
        ]
        canon = canonical_learning_rows(synthetic, "ML")
        assert len(canon) == 1 and canon[0]["phase"] == "FINAL" and canon[0]["pick"] == "H"
    finally:
        globals()["_BOOK_WEIGHT_CACHE"] = old_cache
    print("SELF-TEST MLB BETTING BOT V11.0.0 OK")


def main() -> None:
    install_v11()
    core.main()


if __name__ == "__main__":
    try:
        if "--self-test" in sys.argv:
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
