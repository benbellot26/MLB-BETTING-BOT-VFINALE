from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .v138_audit_features import offense_talent, park_factor

SCHEMA = "v13-8-advanced-research-challengers-v2"
OUT = Path("data/v138_research_models.json")
FEATURE_NAMES = (
    "bias",
    "home_season_rpg", "away_season_rpg",
    "home_l30_rpg", "away_l30_rpg",
    "home_l14_rpg", "away_l14_rpg",
    "home_l7_rpg", "away_l7_rpg",
    "home_ra_pg", "away_ra_pg",
    "home_win_pct", "away_win_pct",
    "home_rest", "away_rest",
    "park_run_factor",
    "home_offense_talent", "away_offense_talent",
    "home_offense_x_away_defense", "away_offense_x_home_defense",
)
# Fixed a priori: GAM non-linearity is restricted to baseball-continuous signals,
# reducing variance and compute without selecting knots/features from labels.
GAM_NONLINEAR_INDICES = (1, 2, 5, 6, 9, 10, 16, 17, 18, 19)


def _num(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _summary(features: dict[str, Any], side: str, window: str) -> dict[str, Any]:
    return (((features.get(f"{side}_team_form") or {}).get(window)) or {})


def vectorize(row: dict[str, Any]) -> list[float]:
    f = row.get("features") or {}
    hs, aws = _summary(f, "home", "season_to_date"), _summary(f, "away", "season_to_date")
    h30, a30 = _summary(f, "home", "last_30_games"), _summary(f, "away", "last_30_games")
    h14, a14 = _summary(f, "home", "last_14_games"), _summary(f, "away", "last_14_games")
    h7, a7 = _summary(f, "home", "last_7_games"), _summary(f, "away", "last_7_games")
    ht = offense_talent(f.get("home_team_form") or {}).get("runs_per_game", 4.45)
    at = offense_talent(f.get("away_team_form") or {}).get("runs_per_game", 4.45)
    pf = park_factor(f.get("park_prior") or {}).get("run_factor", 1.0)
    hrf = _num(hs.get("runs_for_pg"), 4.45)
    arf = _num(aws.get("runs_for_pg"), 4.45)
    hra = _num(hs.get("runs_against_pg"), 4.45)
    ara = _num(aws.get("runs_against_pg"), 4.45)
    return [
        1.0,
        hrf, arf,
        _num(h30.get("runs_for_pg"), hrf), _num(a30.get("runs_for_pg"), arf),
        _num(h14.get("runs_for_pg"), hrf), _num(a14.get("runs_for_pg"), arf),
        _num(h7.get("runs_for_pg"), hrf), _num(a7.get("runs_for_pg"), arf),
        hra, ara,
        _num(hs.get("win_pct"), .5), _num(aws.get("win_pct"), .5),
        _num((f.get("home_team_form") or {}).get("rest_days"), 1.0),
        _num((f.get("away_team_form") or {}).get("rest_days"), 1.0),
        _num(pf, 1.0), _num(ht, 4.45), _num(at, 4.45),
        _num(ht, 4.45) * _num(ara, 4.45) / 4.45,
        _num(at, 4.45) * _num(hra, 4.45) / 4.45,
    ]


def naive_runs(row: dict[str, Any]) -> tuple[float, float]:
    """Strong transparent baseline retained inside the research ensemble."""
    f = row.get("features") or {}
    hs = ((f.get("home_team_form") or {}).get("season_to_date") or {})
    aws = ((f.get("away_team_form") or {}).get("season_to_date") or {})
    home_off = _num(hs.get("runs_for_pg"), 4.45)
    away_off = _num(aws.get("runs_for_pg"), 4.45)
    home_def = _num(hs.get("runs_against_pg"), 4.45)
    away_def = _num(aws.get("runs_against_pg"), 4.45)
    return max(.2, .5 * (home_off + away_def) + .12), max(.2, .5 * (away_off + home_def))


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 1.0
    m = _mean(xs)
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1))
    return s if s > 1e-9 else 1.0


def fit_scaler(X: list[list[float]]) -> dict[str, list[float]]:
    if not X:
        return {"mean": [], "std": []}
    p = len(X[0])
    means, stds = [], []
    for j in range(p):
        col = [row[j] for row in X]
        if j == 0:
            means.append(0.0)
            stds.append(1.0)
        else:
            means.append(_mean(col))
            stds.append(_std(col))
    return {"mean": means, "std": stds}


def scale(X: list[list[float]], scaler: dict[str, list[float]]) -> list[list[float]]:
    means, stds = scaler.get("mean") or [], scaler.get("std") or []
    return [[(x - means[j]) / stds[j] if j < len(means) else x for j, x in enumerate(row)] for row in X]


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [list(A[i]) + [float(b[i])] for i in range(n)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(M[r][i]))
        if pivot != i:
            M[i], M[pivot] = M[pivot], M[i]
        if abs(M[i][i]) < 1e-12:
            M[i][i] = 1e-12
        d = M[i][i]
        for j in range(i, n + 1):
            M[i][j] /= d
        for r in range(n):
            if r == i:
                continue
            factor = M[r][i]
            if abs(factor) < 1e-15:
                continue
            for j in range(i, n + 1):
                M[r][j] -= factor * M[i][j]
    return [M[i][n] for i in range(n)]


def fit_ridge(X: list[list[float]], y: list[float], alpha: float = 2.0) -> list[float]:
    if not X:
        return []
    p = len(X[0])
    A = [[0.0] * p for _ in range(p)]
    b = [0.0] * p
    # Accumulate only the upper triangle then mirror it. This halves the main
    # pure-Python matrix-work cost for repeated walk-forward/ablation fits.
    for row, target in zip(X, y):
        for j in range(p):
            xj = row[j]
            b[j] += xj * target
            for k in range(j, p):
                A[j][k] += xj * row[k]
    for j in range(p):
        for k in range(j + 1, p):
            A[k][j] = A[j][k]
    for j in range(1, p):
        A[j][j] += alpha
    return _solve(A, b)


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _log_target(y: float) -> float:
    return math.log(max(.05, float(y)))


def _inv_target(z: float) -> float:
    return _clip(math.exp(float(z)), .15, 15.0)


def _gam_expand(row: list[float]) -> list[float]:
    out = list(row)
    # Fixed hinge basis; no target-aware knot or feature selection.
    for j in GAM_NONLINEAR_INDICES:
        if j >= len(row):
            continue
        x = row[j]
        out.extend((max(0.0, x + 1.0), max(0.0, x), max(0.0, x - 1.0)))
    return out


def fit_glm(X: list[list[float]], y: list[float], alpha: float = 3.0) -> dict[str, Any]:
    scaler = fit_scaler(X)
    Z = scale(X, scaler)
    coef = fit_ridge(Z, [_log_target(v) for v in y], alpha)
    return {"kind": "log-link-ridge-glm", "scaler": scaler, "coef": coef, "alpha": alpha}


def predict_glm(model: dict[str, Any], row: list[float]) -> float:
    z = scale([row], model.get("scaler") or {})[0]
    return _inv_target(_dot(model.get("coef") or [], z))


def fit_gam(X: list[list[float]], y: list[float], alpha: float = 7.0) -> dict[str, Any]:
    scaler = fit_scaler(X)
    Z = scale(X, scaler)
    G = [_gam_expand(row) for row in Z]
    coef = fit_ridge(G, [_log_target(v) for v in y], alpha)
    return {
        "kind": "gam-hinge-ridge",
        "scaler": scaler,
        "coef": coef,
        "alpha": alpha,
        "knots": [-1.0, 0.0, 1.0],
        "nonlinear_indices": list(GAM_NONLINEAR_INDICES),
    }


def predict_gam(model: dict[str, Any], row: list[float]) -> float:
    z = scale([row], model.get("scaler") or {})[0]
    return _inv_target(_dot(model.get("coef") or [], _gam_expand(z)))


def _candidate_thresholds(values: list[float]) -> list[float]:
    if not values:
        return []
    vals = sorted(values)
    idx = sorted(set((len(vals) // 4, len(vals) // 2, (3 * len(vals)) // 4)))
    return [vals[min(len(vals) - 1, i)] for i in idx]


def fit_gbdt(X: list[list[float]], y: list[float], rounds: int = 32, lr: float = .06) -> dict[str, Any]:
    scaler = fit_scaler(X)
    Z = scale(X, scaler)
    target = [_log_target(v) for v in y]
    base = _mean(target)
    pred = [base] * len(target)
    trees = []
    p = len(Z[0]) if Z else 0
    thresholds = {j: _candidate_thresholds([r[j] for r in Z]) for j in range(1, p)}
    for _ in range(rounds):
        residual = [a - b for a, b in zip(target, pred)]
        best = None
        for j in range(1, p):
            for threshold in thresholds.get(j) or []:
                left = [residual[i] for i, r in enumerate(Z) if r[j] <= threshold]
                right = [residual[i] for i, r in enumerate(Z) if r[j] > threshold]
                if len(left) < 10 or len(right) < 10:
                    continue
                lv, rv = _mean(left), _mean(right)
                loss = sum((residual[i] - (lv if r[j] <= threshold else rv)) ** 2 for i, r in enumerate(Z))
                if best is None or loss < best[0]:
                    best = (loss, j, threshold, lv, rv)
        if best is None:
            break
        _, j, threshold, lv, rv = best
        tree = {"feature": j, "threshold": threshold, "left": lr * lv, "right": lr * rv}
        trees.append(tree)
        for i, r in enumerate(Z):
            pred[i] += tree["left"] if r[j] <= threshold else tree["right"]
    return {"kind": "portable-gradient-stumps", "scaler": scaler, "base": base, "trees": trees, "learning_rate": lr}


def predict_gbdt(model: dict[str, Any], row: list[float]) -> float:
    z = scale([row], model.get("scaler") or {})[0]
    pred = float(model.get("base") or 0.0)
    for tree in model.get("trees") or []:
        j = int(tree["feature"])
        pred += float(tree["left"] if z[j] <= float(tree["threshold"]) else tree["right"])
    return _inv_target(pred)


def fit_hierarchical(
    rows: list[dict[str, Any]],
    y_home: list[float],
    y_away: list[float],
    base_home: list[float],
    base_away: list[float],
    prior_games: float = 20.0,
) -> dict[str, Any]:
    """Empirical-Bayes team offense/defense residual intercepts."""
    acc: dict[str, dict[str, list[float]]] = {}
    for row, yh, ya, ph, pa in zip(rows, y_home, y_away, base_home, base_away):
        hid = str(row.get("home_id") or row.get("home") or "")
        aid = str(row.get("away_id") or row.get("away") or "")
        for tid in (hid, aid):
            acc.setdefault(tid, {"off": [], "def": []})
        hres = _log_target(yh) - _log_target(ph)
        ares = _log_target(ya) - _log_target(pa)
        acc[hid]["off"].append(hres)
        acc[aid]["def"].append(hres)
        acc[aid]["off"].append(ares)
        acc[hid]["def"].append(ares)
    teams = {}
    for tid, d in acc.items():
        teams[tid] = {}
        for key in ("off", "def"):
            vals = d[key]
            n = len(vals)
            raw = _mean(vals)
            teams[tid][key] = raw * n / (n + prior_games)
            teams[tid][f"{key}_n"] = n
    return {"kind": "empirical-bayes-team-hierarchy", "prior_games": prior_games, "teams": teams}


def apply_hierarchical(model: dict[str, Any], row: dict[str, Any], ph: float, pa: float) -> tuple[float, float]:
    teams = model.get("teams") or {}
    hid = str(row.get("home_id") or row.get("home") or "")
    aid = str(row.get("away_id") or row.get("away") or "")
    h_adj = _num((teams.get(hid) or {}).get("off")) + _num((teams.get(aid) or {}).get("def"))
    a_adj = _num((teams.get(aid) or {}).get("off")) + _num((teams.get(hid) or {}).get("def"))
    return _clip(ph * math.exp(h_adj), .15, 15.0), _clip(pa * math.exp(a_adj), .15, 15.0)


def rmse(y: list[float], p: list[float]) -> float | None:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(y, p)) / len(y)) if y else None


def mae(y: list[float], p: list[float]) -> float | None:
    return sum(abs(a - b) for a, b in zip(y, p)) / len(y) if y else None


def _ensemble_weights(
    yh: list[float],
    ya: list[float],
    preds: dict[str, tuple[list[float], list[float]]],
) -> dict[str, float]:
    names = list(preds)
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: 1.0}
    w = {n: 1.0 / len(names) for n in names}
    step = .10

    def loss(weights: dict[str, float]) -> float:
        hp = [sum(weights[n] * preds[n][0][i] for n in names) for i in range(len(yh))]
        ap = [sum(weights[n] * preds[n][1][i] for n in names) for i in range(len(ya))]
        return sum((a - b) ** 2 for a, b in zip(yh, hp)) + sum((a - b) ** 2 for a, b in zip(ya, ap))

    best = loss(w)
    for _ in range(40):
        improved = False
        for give in names:
            for take in names:
                if give == take or w[give] < step:
                    continue
                cand = dict(w)
                cand[give] -= step
                cand[take] += step
                value = loss(cand)
                if value + 1e-12 < best:
                    w, best, improved = cand, value, True
        if not improved:
            step /= 2.0
            if step < .00625:
                break
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def dataset_fingerprint(rows: list[dict[str, Any]], labels: list[dict[str, Any]]) -> str:
    keys = sorted((str(r.get("game_pk")), str(r.get("as_of") or r.get("game_date") or "")) for r in rows)
    lkeys = sorted((str(r.get("game_pk")), _num(r.get("home_score")), _num(r.get("away_score"))) for r in labels)
    raw = json.dumps({"features": keys, "labels": lkeys}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _candidate_predictions(
    fitted: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, tuple[list[float], list[float]]]:
    X = [vectorize(r) for r in rows]
    out: dict[str, tuple[list[float], list[float]]] = {}
    for name, predictor in (("glm", predict_glm), ("gam", predict_gam), ("gbdt", predict_gbdt)):
        model = fitted.get(name) or {}
        if model:
            out[name] = (
                [predictor(model.get("home") or {}, x) for x in X],
                [predictor(model.get("away") or {}, x) for x in X],
            )
    if "glm" in out and fitted.get("hierarchical"):
        hp, ap = [], []
        for row, ph, pa in zip(rows, out["glm"][0], out["glm"][1]):
            h, a = apply_hierarchical(fitted["hierarchical"], row, ph, pa)
            hp.append(h)
            ap.append(a)
        out["hierarchical"] = (hp, ap)
    naive = [naive_runs(r) for r in rows]
    out["naive"] = ([x[0] for x in naive], [x[1] for x in naive])
    return out


def _metric_block(
    yh: list[float],
    ya: list[float],
    predictions: dict[str, tuple[list[float], list[float]]],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    metrics = {}
    for name, (ph, pa) in predictions.items():
        metrics[name] = {
            "home_rmse": rmse(yh, ph),
            "away_rmse": rmse(ya, pa),
            "home_mae": mae(yh, ph),
            "away_mae": mae(ya, pa),
        }
    if weights and all(name in predictions for name in weights):
        hp = [sum(weights[n] * predictions[n][0][i] for n in weights) for i in range(len(yh))]
        ap = [sum(weights[n] * predictions[n][1][i] for n in weights) for i in range(len(ya))]
        metrics["ensemble"] = {
            "home_rmse": rmse(yh, hp),
            "away_rmse": rmse(ya, ap),
            "home_mae": mae(yh, hp),
            "away_mae": mae(ya, ap),
        }
    return metrics


def fit(
    rows: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    holdout_fraction: float = .20,
    validation_fraction: float = .15,
) -> dict[str, Any]:
    by_label = {
        str(x.get("game_pk")): x
        for x in labels
        if x.get("home_score") is not None and x.get("away_score") is not None
    }
    paired = [(r, by_label.get(str(r.get("game_pk")))) for r in rows]
    paired = [(r, l) for r, l in paired if l is not None]
    paired.sort(key=lambda z: str(z[0].get("game_date") or z[0].get("as_of") or ""))
    n = len(paired)
    if n < 200:
        return {
            "schema": SCHEMA,
            "status": "INSUFFICIENT_DATA",
            "games": n,
            "minimum_games": 200,
            "research_only": True,
            "promotion_eligible": False,
        }
    test_frac = _clip(holdout_fraction, .10, .30)
    val_frac = _clip(validation_fraction, .10, .25)
    test_start = int(n * (1.0 - test_frac))
    val_start = int(n * (1.0 - test_frac - val_frac))
    val_start = max(100, min(val_start, test_start - 30))
    train, validation, test = paired[:val_start], paired[val_start:test_start], paired[test_start:]
    if len(validation) < 30 or len(test) < 30:
        return {
            "schema": SCHEMA,
            "status": "INSUFFICIENT_SPLIT_DATA",
            "games": n,
            "train_games": len(train),
            "validation_games": len(validation),
            "holdout_games": len(test),
            "research_only": True,
            "promotion_eligible": False,
        }

    train_rows = [r for r, _ in train]
    validation_rows = [r for r, _ in validation]
    test_rows = [r for r, _ in test]
    X = [vectorize(r) for r in train_rows]
    yh = [_num(l["home_score"]) for _, l in train]
    ya = [_num(l["away_score"]) for _, l in train]

    fitted: dict[str, Any] = {}
    for name, fitter in (("glm", fit_glm), ("gam", fit_gam), ("gbdt", fit_gbdt)):
        fitted[name] = {"home": fitter(X, yh), "away": fitter(X, ya)}

    base_train_h = [predict_glm(fitted["glm"]["home"], x) for x in X]
    base_train_a = [predict_glm(fitted["glm"]["away"], x) for x in X]
    fitted["hierarchical"] = fit_hierarchical(train_rows, yh, ya, base_train_h, base_train_a)

    val_predictions = _candidate_predictions(fitted, validation_rows)
    yhv = [_num(l["home_score"]) for _, l in validation]
    yav = [_num(l["away_score"]) for _, l in validation]
    weights = _ensemble_weights(yhv, yav, val_predictions)

    test_predictions = _candidate_predictions(fitted, test_rows)
    yht = [_num(l["home_score"]) for _, l in test]
    yat = [_num(l["away_score"]) for _, l in test]
    validation_metrics = _metric_block(yhv, yav, val_predictions, weights)
    holdout_metrics = _metric_block(yht, yat, test_predictions, weights)

    return {
        "schema": SCHEMA,
        "status": "TRAINED_RESEARCH_ONLY",
        "research_only": True,
        "promotion_eligible": False,
        "games": n,
        "train_games": len(train),
        "validation_games": len(validation),
        "holdout_games": len(test),
        "feature_names": list(FEATURE_NAMES),
        "models": fitted,
        "ensemble_weights": weights,
        "validation_metrics": validation_metrics,
        "holdout_metrics": holdout_metrics,
        "dataset_fingerprint": dataset_fingerprint([r for r, _ in paired], [l for _, l in paired]),
        "selection_policy": "component models fit on train; ensemble weights fit only on later validation; final holdout untouched until reporting",
        "holdout_isolation": True,
        "baseline_in_ensemble": True,
        "claims": [
            "historical reconstructed evidence may rank research challengers but cannot satisfy native-live promotion floors",
            "portable models use only pregame feature rows and separate labels",
            "reported holdout is not used to fit component models or ensemble weights",
        ],
    }


def predict(artifact: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    if str(artifact.get("status")) != "TRAINED_RESEARCH_ONLY":
        return {"available": False, "reason": "model_not_trained"}
    x = vectorize(row)
    fitted = artifact.get("models") or {}
    preds: dict[str, tuple[float, float]] = {}
    for name, predictor in (("glm", predict_glm), ("gam", predict_gam), ("gbdt", predict_gbdt)):
        m = fitted.get(name) or {}
        if m:
            preds[name] = (predictor(m.get("home") or {}, x), predictor(m.get("away") or {}, x))
    if "glm" in preds and fitted.get("hierarchical"):
        preds["hierarchical"] = apply_hierarchical(fitted["hierarchical"], row, *preds["glm"])
    preds["naive"] = naive_runs(row)
    weights = artifact.get("ensemble_weights") or {}
    if weights and all(n in preds for n in weights):
        h = sum(float(weights[n]) * preds[n][0] for n in weights)
        a = sum(float(weights[n]) * preds[n][1] for n in weights)
    elif preds:
        h = sum(v[0] for v in preds.values()) / len(preds)
        a = sum(v[1] for v in preds.values()) / len(preds)
    else:
        return {"available": False, "reason": "candidate_models_missing"}
    return {
        "available": True,
        "research_only": True,
        "affects_champion": False,
        "home_runs": _clip(h, .15, 15.0),
        "away_runs": _clip(a, .15, 15.0),
        "candidates": preds,
    }


def _read_jsonl_gz(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def load_free_dataset(base: Path = Path("data/v137")) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, labels = [], []
    for path in sorted(base.glob("team_features_*.jsonl.gz")):
        rows.extend(_read_jsonl_gz(path))
    for path in sorted(base.glob("team_labels_*.jsonl.gz")):
        labels.extend(_read_jsonl_gz(path))
    return rows, labels


def main() -> None:
    rows, labels = load_free_dataset()
    artifact = fit(rows, labels)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    summary = {
        k: artifact.get(k)
        for k in (
            "schema", "status", "games", "train_games", "validation_games", "holdout_games",
            "ensemble_weights", "validation_metrics", "holdout_metrics", "dataset_fingerprint",
            "selection_policy", "holdout_isolation",
        )
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
