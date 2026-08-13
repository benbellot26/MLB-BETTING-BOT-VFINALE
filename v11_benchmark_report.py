#!/usr/bin/env python3
"""Point-in-time validation for the V11 sharp market benchmark.

Uses only market snapshots already persisted before historical games. It does
not call an odds API and does not reconstruct missing historical prices.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import median

import bot as core
import bot_v11 as v11

OUT = Path("data/v11_benchmark_report.json")
WEIGHT_GRID = tuple(i / 20 for i in range(5, 17))  # model weight .25 -> .80


def _brier(rows, field):
    xs = [(core.num(r.get(field), .5), core.num(r.get("y"), 0)) for r in rows if r.get(field) is not None]
    return sum((p-y) ** 2 for p, y in xs) / len(xs) if xs else None


def _logloss(rows, field):
    xs = [(core.clamp(core.num(r.get(field), .5), .001, .999), core.num(r.get("y"), 0)) for r in rows if r.get(field) is not None]
    return sum(-(y * math.log(p) + (1-y) * math.log(1-p)) for p, y in xs) / len(xs) if xs else None


def _snapshot_rows(snapshot, key):
    out = []
    for b in snapshot.get("market_snapshot") or []:
        book = {"key": b.get("book"), "last_update": b.get("last_update")}
        for m in b.get("markets") or []:
            if m.get("key") == key:
                out.append((book, m))
    return out


def _snapshot_model_home(snapshot, home):
    """Return the independent effective ML probability for the home team."""
    for rec in snapshot.get("open_market_options") or []:
        if rec.get("market") != "ML" or core.norm_name(rec.get("name")) != core.norm_name(home):
            continue
        for key in ("p_effective_independent", "p_effective", "p_model"):
            if rec.get(key) is not None:
                return core.clamp(core.num(rec.get(key), .5), .001, .999)

    rec = (snapshot.get("model_recommendations") or {}).get("ML") or {}
    if rec:
        value = None
        for key in ("p_effective_independent", "p_effective", "p_model"):
            if rec.get(key) is not None:
                value = core.clamp(core.num(rec.get(key), .5), .001, .999); break
        if value is not None:
            return value if core.norm_name(rec.get("name")) == core.norm_name(home) else 1-value

    return core.clamp(core.num(snapshot.get("p_model"), .5), .001, .999) if snapshot.get("p_model") is not None else None


def historical_sharp(snapshot, name, market="h2h", point=None):
    """V11 consensus evaluated at the historical snapshot timestamp."""
    try:
        asof = core.parse_dt(snapshot.get("analyzed_at"))
    except Exception:
        return None, []

    comps = []
    for book, mk in _snapshot_rows(snapshot, market):
        key = str(book.get("key") or "")
        if key not in set(v11.sharp_books()):
            continue
        p = core.fair_book_probability(mk.get("outcomes") or [], name, point, market)
        if p is None:
            continue
        try:
            stamp = mk.get("last_update", book.get("last_update"))
            age = max(0.0, (asof - core.parse_dt(stamp)).total_seconds() / 60.0) if stamp else 10.0
        except Exception:
            age = 10.0
        if age > v11.MAX_MARKET_AGE_MIN:
            continue
        comps.append({"book": key, "p": core.clamp(p, .001, .999), "age_min": age})

    if not comps:
        return None, []
    med = median([x["p"] for x in comps])
    for c in comps:
        freshness = v11._freshness_weight(c["age_min"])
        robust = 1.0 / (1.0 + (abs(c["p"] - med) / v11.ROBUST_SCALE) ** 2)
        c["weight"] = freshness * robust  # equal prior / no learned look-ahead
    den = sum(x["weight"] for x in comps)
    p = sum(x["p"] * x["weight"] for x in comps) / den if den > 0 else None
    return (core.clamp(p, .001, .999) if p is not None else None), comps


def _latest_snapshot(record):
    xs = [s for s in record.get("snapshots") or [] if core.num(s.get("seconds_to_game"), -1) >= 0 and s.get("market_snapshot")]
    if not xs:
        return None
    return min(xs, key=lambda s: (core.num(s.get("seconds_to_game"), 10**12), -core.parse_dt(s.get("analyzed_at")).timestamp()))


def collect(hist):
    rows = []
    book_rows = {b: [] for b in v11.sharp_books()}
    for rec in hist.values():
        if rec.get("status") != "FINAL" or rec.get("home_win") not in (0, 1):
            continue
        snap = _latest_snapshot(rec)
        if not snap:
            continue
        home = rec.get("home")
        sharp, comps = historical_sharp(snap, home, "h2h")
        row = {
            "date": rec.get("game_date") or snap.get("analyzed_at") or "",
            "game_pk": rec.get("game_pk"),
            "y": int(rec.get("home_win")),
            "model": _snapshot_model_home(snap, home),
            "legacy_market": core.num(snap.get("market_home"), .5) if snap.get("market_home") is not None and snap.get("benchmark_version") != v11.BENCHMARK_VERSION else None,
            "sharp": sharp,
            "sharp_refs": len(comps),
        }
        rows.append(row)
        by_book = {x["book"]: x["p"] for x in comps}
        for book, p in by_book.items():
            book_rows.setdefault(book, []).append({"y": row["y"], "p": p})
    rows.sort(key=lambda r: (str(r.get("date")), str(r.get("game_pk"))))
    return rows, book_rows


def select_blend_weight(train):
    candidates = []
    for w in WEIGHT_GRID:
        vals = []
        for r in train:
            p = core.clamp(w * r["model"] + (1-w) * r["sharp"], .001, .999)
            vals.append((p-r["y"]) ** 2)
        if vals:
            candidates.append((sum(vals) / len(vals), abs(w-.5), w))
    return min(candidates)[2] if candidates else None


def add_blend(rows, weight):
    out = []
    for r in rows:
        z = dict(r)
        z["blend"] = core.clamp(weight * r["model"] + (1-weight) * r["sharp"], .001, .999) if weight is not None else None
        out.append(z)
    return out


def metric_block(rows):
    return {
        "n": len(rows),
        "brier_model": _brier(rows, "model"),
        "brier_legacy_market": _brier(rows, "legacy_market"),
        "brier_sharp": _brier(rows, "sharp"),
        "brier_blend": _brier(rows, "blend"),
        "logloss_model": _logloss(rows, "model"),
        "logloss_legacy_market": _logloss(rows, "legacy_market"),
        "logloss_sharp": _logloss(rows, "sharp"),
        "logloss_blend": _logloss(rows, "blend"),
    }


def main():
    hist = core.load_history()
    all_rows, books = collect(hist)
    usable = [r for r in all_rows if r.get("model") is not None and r.get("sharp") is not None]
    cut = int(len(usable) * .75)
    train = usable[:cut]
    holdout = usable[cut:]
    weight = select_blend_weight(train) if len(train) >= 40 and len(holdout) >= 20 else None
    matched_blend = add_blend(usable, weight)
    holdout_blend = add_blend(holdout, weight)
    holdout_multi = sum(core.num(r.get("sharp_refs"), 0) >= 2 for r in holdout)

    report = {
        "version": v11.V11_VERSION,
        "benchmark_version": v11.BENCHMARK_VERSION,
        "method": "point-in-time persisted snapshots; independent effective model; matched comparisons; no reconstructed historical odds",
        "sharp_books": list(v11.sharp_books()),
        "coverage": {
            "final_games_with_pregame_market_snapshot": len(all_rows),
            "matched_model_and_sharp": len(usable),
            "matched_pct": (len(usable) / len(all_rows)) if all_rows else None,
            "one_sharp_ref": sum(r.get("sharp_refs") == 1 for r in usable),
            "two_or_more_sharp_refs": sum(core.num(r.get("sharp_refs"), 0) >= 2 for r in usable),
            "holdout_two_or_more_sharp_refs": holdout_multi,
            "holdout_multiref_pct": (holdout_multi / len(holdout)) if holdout else None,
        },
        "matched_all": metric_block(matched_blend),
        "holdout": metric_block(holdout_blend),
        "blend_model_weight_selected_on_train": weight,
        "train_n": len(train),
        "holdout_n": len(holdout),
        "books": {},
    }
    for book, xs in books.items():
        if not xs:
            continue
        br = sum((core.num(x["p"], .5)-x["y"])**2 for x in xs) / len(xs)
        ll = sum(-(x["y"]*math.log(core.clamp(core.num(x["p"], .5),.001,.999)) + (1-x["y"])*math.log(1-core.clamp(core.num(x["p"], .5),.001,.999))) for x in xs) / len(xs)
        report["books"][book] = {"n": len(xs), "brier": br, "logloss": ll}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
