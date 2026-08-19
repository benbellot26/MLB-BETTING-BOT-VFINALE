from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from typing import Any, Callable

from . import engine_v12 as engine
from . import v138_research_models as models

SCHEMA = "v13-8-validation-suite-v1"


def _num(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d


def _clip(x: float, lo: float = .001, hi: float = .999) -> float:
    return max(lo, min(hi, float(x)))


def brier(y: list[int], p: list[float]) -> float | None:
    return sum((a - b) ** 2 for a, b in zip(y, p)) / len(y) if y else None


def logloss(y: list[int], p: list[float]) -> float | None:
    if not y:
        return None
    return -sum(a * math.log(_clip(b)) + (1 - a) * math.log(_clip(1 - b)) for a, b in zip(y, p)) / len(y)


def home_win_probability(hmu: float, amu: float) -> float:
    return _clip(engine.prob_home_win(max(.05, hmu), max(.05, amu)))


def naive_runs(row: dict[str, Any]) -> tuple[float, float]:
    f = row.get("features") or {}
    hs = ((f.get("home_team_form") or {}).get("season_to_date") or {})
    aws = ((f.get("away_team_form") or {}).get("season_to_date") or {})
    home_off = _num(hs.get("runs_for_pg"), 4.45); away_off = _num(aws.get("runs_for_pg"), 4.45)
    home_def = _num(hs.get("runs_against_pg"), 4.45); away_def = _num(aws.get("runs_against_pg"), 4.45)
    return max(.2, .5 * (home_off + away_def) + .12), max(.2, .5 * (away_off + home_def))


def calibration_bins(y: list[int], p: list[float], bins: int = 10) -> list[dict[str, Any]]:
    out = []
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        idx = [i for i, q in enumerate(p) if lo <= q < hi or (k == bins - 1 and q == 1.0)]
        if not idx:
            continue
        out.append({"low": lo, "high": hi, "n": len(idx),
                    "mean_probability": sum(p[i] for i in idx) / len(idx),
                    "empirical_rate": sum(y[i] for i in idx) / len(idx)})
    return out


def expected_calibration_error(y: list[int], p: list[float], bins: int = 10) -> float | None:
    if not y:
        return None
    rows = calibration_bins(y, p, bins)
    return sum(r["n"] / len(y) * abs(r["mean_probability"] - r["empirical_rate"]) for r in rows)


def bootstrap_difference(
    y: list[Any], a: list[float], b: list[float], metric: Callable[[list[Any], list[float]], float | None],
    iterations: int = 600, seed: int = 138,
) -> dict[str, Any]:
    """Paired bootstrap CI for metric(A)-metric(B). Negative favors A."""
    n = len(y)
    if n < 30 or len(a) != n or len(b) != n:
        return {"available": False, "n": n, "minimum_n": 30}
    rng = random.Random(seed)
    vals = []
    for _ in range(max(100, int(iterations))):
        idx = [rng.randrange(n) for __ in range(n)]
        ys = [y[i] for i in idx]; aa = [a[i] for i in idx]; bb = [b[i] for i in idx]
        ma, mb = metric(ys, aa), metric(ys, bb)
        if ma is not None and mb is not None:
            vals.append(float(ma) - float(mb))
    vals.sort()
    if not vals:
        return {"available": False, "n": n}
    def q(frac: float) -> float:
        return vals[min(len(vals) - 1, max(0, int(frac * (len(vals) - 1))))]
    point_a, point_b = metric(y, a), metric(y, b)
    return {"available": True, "n": n, "iterations": len(vals),
            "difference": None if point_a is None or point_b is None else float(point_a) - float(point_b),
            "ci95_low": q(.025), "ci95_high": q(.975),
            "probability_a_better": sum(v < 0 for v in vals) / len(vals)}


def _paired(rows: list[dict[str, Any]], labels: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by = {str(l.get("game_pk")): l for l in labels if l.get("home_score") is not None and l.get("away_score") is not None}
    out = [(r, by.get(str(r.get("game_pk")))) for r in rows]
    return [(r, l) for r, l in out if l is not None]


def evaluate_predictions(paired: list[tuple[dict[str, Any], dict[str, Any]]], run_preds: list[tuple[float, float]]) -> dict[str, Any]:
    yh = [_num(l.get("home_score")) for _, l in paired]; ya = [_num(l.get("away_score")) for _, l in paired]
    ph = [x[0] for x in run_preds]; pa = [x[1] for x in run_preds]
    ywin = [int(l.get("home_score", 0) > l.get("away_score", 0)) for _, l in paired]
    pwin = [home_win_probability(h, a) for h, a in run_preds]
    return {"n": len(paired), "home_rmse": models.rmse(yh, ph), "away_rmse": models.rmse(ya, pa),
            "home_mae": models.mae(yh, ph), "away_mae": models.mae(ya, pa),
            "ml_brier": brier(ywin, pwin), "ml_logloss": logloss(ywin, pwin),
            "ml_ece": expected_calibration_error(ywin, pwin), "calibration_bins": calibration_bins(ywin, pwin)}


def baseline_predictions(paired: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    ywin = [int(l.get("home_score", 0) > l.get("away_score", 0)) for _, l in paired]
    naive = [naive_runs(r) for r, _ in paired]
    naive_ml = [home_win_probability(h, a) for h, a in naive]
    home_field = [.54] * len(paired)
    coin = [.50] * len(paired)
    market = []
    market_y = []
    for (r, l) in paired:
        p = r.get("p_market_home")
        if p is not None:
            market.append(_clip(_num(p, .5))); market_y.append(int(l.get("home_score", 0) > l.get("away_score", 0)))
    return {
        "coin_flip": {"n": len(ywin), "brier": brier(ywin, coin), "logloss": logloss(ywin, coin)},
        "home_field_54": {"n": len(ywin), "brier": brier(ywin, home_field), "logloss": logloss(ywin, home_field)},
        "naive_team_runs": {**evaluate_predictions(paired, naive)},
        "market_if_present": {"n": len(market_y), "brier": brier(market_y, market), "logloss": logloss(market_y, market)} if market_y else {"n": 0, "status": "NO_PIT_MARKET_IN_FREE_DATA"},
    }


def walk_forward(rows: list[dict[str, Any]], labels: list[dict[str, Any]]) -> dict[str, Any]:
    paired = _paired(rows, labels)
    seasons = sorted({int(r.get("season") or str(r.get("official_date") or "")[:4]) for r, _ in paired if str(r.get("official_date") or "")[:4].isdigit()})
    folds = []
    for season in seasons[1:]:
        train_rows = [r for r, _ in paired if int(r.get("season") or str(r.get("official_date"))[:4]) < season]
        train_ids = {str(r.get("game_pk")) for r in train_rows}
        train_labels = [l for r, l in paired if str(r.get("game_pk")) in train_ids]
        test = [(r, l) for r, l in paired if int(r.get("season") or str(r.get("official_date"))[:4]) == season]
        artifact = models.fit(train_rows, train_labels)
        if artifact.get("status") != "TRAINED_RESEARCH_ONLY":
            folds.append({"season": season, "status": artifact.get("status"), "train_games": len(train_rows), "test_games": len(test)})
            continue
        preds = []
        for r, _ in test:
            p = models.predict(artifact, r)
            preds.append((_num(p.get("home_runs"), 4.45), _num(p.get("away_runs"), 4.45)))
        candidate = evaluate_predictions(test, preds)
        base = baseline_predictions(test)
        ywin = [int(l.get("home_score", 0) > l.get("away_score", 0)) for _, l in test]
        pc = [home_win_probability(h, a) for h, a in preds]
        pn = [home_win_probability(*naive_runs(r)) for r, _ in test]
        folds.append({"season": season, "status": "PASS", "train_games": len(train_rows), "test_games": len(test),
                      "candidate": candidate, "baselines": base,
                      "candidate_vs_naive_brier_bootstrap": bootstrap_difference(ywin, pc, pn, brier)})
    return {"schema": SCHEMA, "folds": folds, "seasons": seasons,
            "strict_temporal_policy": "each test season is trained only on earlier seasons"}


def ablation_report(rows: list[dict[str, Any]], labels: list[dict[str, Any]], seed: int = 138) -> dict[str, Any]:
    paired = _paired(rows, labels)
    if len(paired) < 300:
        return {"available": False, "n": len(paired), "minimum_n": 300}
    paired.sort(key=lambda z: str(z[0].get("game_date") or z[0].get("as_of") or ""))
    cut = int(len(paired) * .8); train, test = paired[:cut], paired[cut:]
    X = [models.vectorize(r) for r, _ in train]; Xt = [models.vectorize(r) for r, _ in test]
    yh = [_num(l.get("home_score")) for _, l in train]; ya = [_num(l.get("away_score")) for _, l in train]
    yht = [_num(l.get("home_score")) for _, l in test]; yat = [_num(l.get("away_score")) for _, l in test]
    groups = {
        "team_season": [1, 2, 9, 10, 11, 12],
        "recent_30": [3, 4], "recent_14": [5, 6], "recent_7": [7, 8],
        "rest": [13, 14], "park": [15], "talent_shrinkage": [16, 17], "offense_defense_interaction": [18, 19],
    }
    all_idx = set(range(len(models.FEATURE_NAMES)))
    def score(drop: set[int]) -> float:
        keep = [j for j in range(len(models.FEATURE_NAMES)) if j not in drop]
        Xk = [[r[j] for j in keep] for r in X]; Xtk = [[r[j] for j in keep] for r in Xt]
        mh, ma = models.fit_glm(Xk, yh), models.fit_glm(Xk, ya)
        ph = [models.predict_glm(mh, x) for x in Xtk]; pa = [models.predict_glm(ma, x) for x in Xtk]
        return ((models.rmse(yht, ph) or 0.0) + (models.rmse(yat, pa) or 0.0)) / 2.0
    full = score(set())
    rows_out = []
    for name, idx in groups.items():
        s = score(set(idx)); rows_out.append({"group": name, "rmse_without": s, "rmse_full": full, "delta_rmse": s - full})
    rows_out.sort(key=lambda r: r["delta_rmse"], reverse=True)
    return {"available": True, "train_n": len(train), "holdout_n": len(test), "full_rmse": full, "groups": rows_out,
            "interpretation": "positive delta means the removed feature group helped on the temporal holdout"}


def subgroup_validation(paired: list[tuple[dict[str, Any], dict[str, Any]]], preds: list[tuple[float, float]]) -> dict[str, Any]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, ((r, _), (h, a)) in enumerate(zip(paired, preds)):
        season = str(r.get("season") or str(r.get("official_date") or "")[:4])
        buckets[f"season:{season}"].append(i)
        total = h + a
        buckets["run_env:low" if total < 8 else "run_env:high" if total >= 10 else "run_env:mid"].append(i)
        park = _num((((r.get("features") or {}).get("park_prior") or {}).get("ALL")), 100.0)
        buckets["park:pitcher" if park < 98 else "park:hitter" if park > 102 else "park:neutral"].append(i)
    out = {}
    for key, idx in buckets.items():
        sub = [paired[i] for i in idx]; pp = [preds[i] for i in idx]
        out[key] = evaluate_predictions(sub, pp)
    return out


def empirical_interval_coverage(outcomes: list[int], lows: list[float], highs: list[float]) -> dict[str, Any]:
    n = min(len(outcomes), len(lows), len(highs))
    if n < 50:
        return {"available": False, "n": n, "minimum_n": 50}
    covered = sum(float(lows[i]) <= float(outcomes[i]) <= float(highs[i]) for i in range(n))
    widths = [max(0.0, float(highs[i]) - float(lows[i])) for i in range(n)]
    return {"available": True, "n": n, "empirical_coverage": covered / n, "mean_width": sum(widths) / n}


def learn_extra_innings_home_prior(rows: list[dict[str, Any]], prior_games: float = 80.0) -> dict[str, Any]:
    vals = [int(r.get("home_win")) for r in rows if r.get("extra_innings") and r.get("home_win") in (0, 1)]
    n = len(vals)
    if n == 0:
        return {"active": False, "n": 0, "home_probability": .5}
    p = (sum(vals) + .5 * prior_games) / (n + prior_games)
    return {"active": n >= 200, "n": n, "home_probability": _clip(p, .45, .55),
            "prior_games": prior_games, "policy": "remains 0.50 until at least 200 authenticated examples"}


def learn_bookmaker_weights(rows: list[dict[str, Any]], min_games: int = 300) -> dict[str, Any]:
    """Learn non-negative book weights only from rows with PIT book probabilities."""
    usable = [r for r in rows if r.get("outcome") in (0, 1) and isinstance(r.get("book_probs"), dict) and r.get("book_probs")]
    books = sorted({b for r in usable for b, p in (r.get("book_probs") or {}).items() if p is not None})
    if len(usable) < min_games or len(books) < 2:
        return {"active": False, "n": len(usable), "books": books, "minimum_games": min_games}
    w = {b: 1.0 / len(books) for b in books}
    def predict(r: dict[str, Any], ww: dict[str, float]) -> float:
        vals = [(ww[b], _num((r.get("book_probs") or {}).get(b), .5)) for b in books if (r.get("book_probs") or {}).get(b) is not None]
        z = sum(x for x, _ in vals)
        return sum(x * p for x, p in vals) / z if z else .5
    def loss(ww: dict[str, float]) -> float:
        y = [int(r["outcome"]) for r in usable]; p = [predict(r, ww) for r in usable]
        return brier(y, p) or 1.0
    best = loss(w); step = .10
    for _ in range(40):
        improved = False
        for give in books:
            for take in books:
                if give == take or w[give] < step:
                    continue
                c = dict(w); c[give] -= step; c[take] += step; val = loss(c)
                if val + 1e-12 < best:
                    w, best, improved = c, val, True
        if not improved:
            step /= 2
            if step < .01: break
    return {"active": True, "n": len(usable), "books": books, "weights": w, "in_sample_brier": best,
            "requires_oos_confirmation": True}


def gap_bins(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bands = ((-9, -.05, "<-5pp"), (-.05, -.02, "-5..-2pp"), (-.02, 0, "-2..0pp"),
             (0, .02, "0..2pp"), (.02, .05, "2..5pp"), (.05, 9, ">=5pp"))
    out = {}
    for lo, hi, name in bands:
        xs = [r for r in rows if r.get("outcome") in (0, 1) and r.get("p_model") is not None and r.get("p_market") is not None
              and lo <= _num(r.get("p_model")) - _num(r.get("p_market")) < hi]
        if not xs: continue
        y = [int(r["outcome"]) for r in xs]; pm = [_clip(_num(r["p_model"), .5)) for r in xs]; pk = [_clip(_num(r["p_market"), .5)) for r in xs]
        out[name] = {"n": len(xs), "mean_gap": sum(a - b for a, b in zip(pm, pk)) / len(xs),
                     "model_brier": brier(y, pm), "market_brier": brier(y, pk),
                     "empirical_rate": sum(y) / len(y)}
    return out


def feature_drift(reference: list[list[float]], recent: list[list[float]]) -> dict[str, Any]:
    if len(reference) < 50 or len(recent) < 30:
        return {"available": False, "reference_n": len(reference), "recent_n": len(recent)}
    out = {}
    p = min(len(reference[0]), len(recent[0]))
    for j in range(1, p):
        ref = [r[j] for r in reference]; rec = [r[j] for r in recent]
        mr, mc = sum(ref)/len(ref), sum(rec)/len(rec)
        sr = math.sqrt(sum((x-mr)**2 for x in ref)/max(1,len(ref)-1)) or 1.0
        out[models.FEATURE_NAMES[j] if j < len(models.FEATURE_NAMES) else str(j)] = {
            "reference_mean": mr, "recent_mean": mc, "standardized_shift": (mc-mr)/sr,
            "alert": abs((mc-mr)/sr) >= .75,
        }
    return {"available": True, "features": out, "alerts": sorted(k for k,v in out.items() if v["alert"])}


def reproducibility_manifest(rows: list[dict[str, Any]], labels: list[dict[str, Any]], code_sha: str | None = None, seed: int = 138) -> dict[str, Any]:
    fp = models.dataset_fingerprint(rows, labels)
    contract = json.dumps({"feature_names": list(models.FEATURE_NAMES), "schema": models.SCHEMA}, sort_keys=True, separators=(",", ":"))
    feature_contract_hash = hashlib.sha256(contract.encode()).hexdigest()
    return {"dataset_fingerprint": fp, "feature_contract_hash": feature_contract_hash,
            "code_sha": code_sha, "seed": int(seed), "split_policy": "strict temporal / walk-forward",
            "reproducible": bool(code_sha and fp and feature_contract_hash)}


def full_report(rows: list[dict[str, Any]], labels: list[dict[str, Any]]) -> dict[str, Any]:
    paired = _paired(rows, labels)
    return {"schema": SCHEMA, "games": len(paired), "baselines": baseline_predictions(paired),
            "walk_forward": walk_forward(rows, labels), "ablation": ablation_report(rows, labels),
            "claim": "research validation only; no automatic champion promotion"}
