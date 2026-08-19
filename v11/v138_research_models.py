from __future__ import annotations

import gzip
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Callable

from .v138_audit_features import offense_talent, park_factor

SCHEMA = "v13-8-advanced-research-challengers-v1"
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
    hrf = _num(hs.get("runs_for_pg"), 4.45); arf = _num(aws.get("runs_for_pg"), 4.45)
    hra = _num(hs.get("runs_against_pg"), 4.45); ara = _num(aws.get("runs_against_pg"), 4.45)
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
            means.append(0.0); stds.append(1.0)
        else:
            means.append(_mean(col)); stds.append(_std(col))
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
    for row, target in zip(X, y):
        for j in range(p):
            b[j] += row[j] * target
            for k in range(p):
                A[j][k] += row[j] * row[k]
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
    # Fixed hinge basis avoids data leakage from target-aware knot selection.
    for x in row[1:]:
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
    return {"kind": "gam-hinge-ridge", "scaler": scaler, "coef": coef, "alpha": alpha, "knots": [-1.0, 0.0, 1.0]}


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
    for _ in range(rounds):
        residual = [a - b for a, b in zip(target, pred)]
        best = None
        for j in range(1, p):
            vals = [r[j] for r in Z]
            for threshold in _candidate_thresholds(vals):
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
    y_home: list[float], y_away: list[float],
    base_home: list[float], base_away: list[float], prior_games: float = 20.0,
) -> dict[str, Any]:
    """Empirical-Bayes team offense/defense residual intercepts."""
    acc: dict[str, dict[str, list[float]]] = {}
    for row, yh, ya, ph, pa in zip(rows, y_home, y_away, base_home, base_away):
        hid, aid = str(row.get("home_id") or row.get("home") or ""), str(row.get("away_id") or row.get("away") or "")
        for tid in (hid, aid):
            acc.setdefault(tid, {"off": [], "def": []})
        acc[hid]["off"].append(_log_target(yh) - _log_target(ph)); acc[aid]["def"].append(_log_target(yh) - _log_target(ph))
        acc[aid]["off"].append(_log_target(ya) - _log_target(pa)); acc[hid]["def"].append(_log_target(ya) - _log_target(pa))
    teams = {}
    for tid, d in acc.items():
        teams[tid] = {}
        for key in ("off", "def"):
            vals = d[key]; n = len(vals); raw = _mean(vals)
            teams[tid][key] = raw * n / (n + prior_games)
            teams[tid][f"{key}_n"] = n
    return {"kind": "empirical-bayes-team-hierarchy", "prior_games": prior_games, "teams": teams}


def apply_hierarchical(model: dict[str, Any], row: dict[str, Any], ph: float, pa: float) -> tuple[float, float]:
    teams = model.get("teams") or {}
    hid, aid = str(row.get("home_id") or row.get("home") or ""), str(row.get("away_id") or row.get("away") or "")
    h_adj = _num((teams.get(hid) or {}).get("off")) + _num((teams.get(aid) or {}).get("def"))
    a_adj = _num((teams.get(aid) or {}).get("off")) + _num((teams.get(hid) or {}).get("def"))
    return _clip(ph * math.exp(h_adj), .15, 15.0), _clip(pa * math.exp(a_adj), .15, 15.0)


def rmse(y: list[float], p: list[float]) -> float | None:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(y, p)) / len(y)) if y else None


def mae(y: list[float], p: list[float]) -> float | None:
    return sum(abs(a - b) for a, b in zip(y, p)) / len(y) if y else None


def _ensemble_weights(yh: list[float], ya: list[float], preds: dict[str, tuple[list[float], list[float]]]) -> dict[str, float]:
    names = list(preds)
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: 1.0}
    # Coordinate-style non-negative search, deterministic and dependency free.
    w = {n: 1.0 / len(names) for n in names}
    step = .10
    def loss(weights: dict[str, float]) -> float:
        hp = [sum(weights[n] * preds[n][0][i] for n in names) for i in range(len(yh))]
        ap = [sum(weights[n] * preds[n][1][i] for n in names) for i in range(len(ya))]
        return sum((a - b) ** 2 for a, b in zip(yh, hp)) + sum((a - b) ** 2 for a, b in zip(ya, ap))
    best = loss(w)
    for _ in range(30):
        improved = False
        for give in names:
            for take in names:
                if give == take or w[give] < step:
                    continue
                cand = dict(w); cand[give] -= step; cand[take] += step
                val = loss(cand)
                if val + 1e-12 < best:
                    w, best, improved = cand, val, True
        if not improved:
            step /= 2.0
            if step < .0125:
                break
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def dataset_fingerprint(rows: list[dict[str, Any]], labels: list[dict[str, Any]]) -> str:
    keys = sorted((str(r.get("game_pk")), str(r.get("as_of") or r.get("game_date") or "")) for r in rows)
    lkeys = sorted((str(r.get("game_pk")), _num(r.get("home_score")), _num(r.get("away_score"))) for r in labels)
    raw = json.dumps({"features": keys, "labels": lkeys}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def fit(rows: list[dict[str, Any]], labels: list[dict[str, Any]], holdout_fraction: float = .20) -> dict[str, Any]:
    by_label = {str(x.get("game_pk")): x for x in labels if x.get("home_score") is not None and x.get("away_score") is not None}
    paired = [(r, by_label.get(str(r.get("game_pk")))) for r in rows]
    paired = [(r, l) for r, l in paired if l is not None]
    paired.sort(key=lambda z: str(z[0].get("game_date") or z[0].get("as_of") or ""))
    if len(paired) < 200:
        return {"schema": SCHEMA, "status": "INSUFFICIENT_DATA", "games": len(paired), "minimum_games": 200,
                "research_only": True, "promotion_eligible": False}
    cut = max(150, int(len(paired) * (1.0 - _clip(holdout_fraction, .10, .35))))
    train, test = paired[:cut], paired[cut:]
    train_rows = [r for r, _ in train]; test_rows = [r for r, _ in test]
    X = [vectorize(r) for r in train_rows]; Xt = [vectorize(r) for r in test_rows]
    yh = [_num(l["home_score"]) for _, l in train]; ya = [_num(l["away_score"]) for _, l in train]
    yht = [_num(l["home_score"]) for _, l in test]; yat = [_num(l["away_score"]) for _, l in test]

    models: dict[str, Any] = {}
    predictions: dict[str, tuple[list[float], list[float]]] = {}
    for name, fitter, predictor in (("glm", fit_glm, predict_glm), ("gam", fit_gam, predict_gam), ("gbdt", fit_gbdt, predict_gbdt)):
        mh, ma = fitter(X, yh), fitter(X, ya)
        ph = [predictor(mh, x) for x in Xt]; pa = [predictor(ma, x) for x in Xt]
        models[name] = {"home": mh, "away": ma}
        predictions[name] = (ph, pa)

    # Hierarchical layer sits on top of the GLM baseline.
    base_train_h = [predict_glm(models["glm"]["home"], x) for x in X]
    base_train_a = [predict_glm(models["glm"]["away"], x) for x in X]
    hierarchy = fit_hierarchical(train_rows, yh, ya, base_train_h, base_train_a)
    hier_h, hier_a = [], []
    for r, ph, pa in zip(test_rows, predictions["glm"][0], predictions["glm"][1]):
        h, a = apply_hierarchical(hierarchy, r, ph, pa); hier_h.append(h); hier_a.append(a)
    models["hierarchical"] = hierarchy; predictions["hierarchical"] = (hier_h, hier_a)

    weights = _ensemble_weights(yht, yat, predictions)
    ens_h = [sum(weights[n] * predictions[n][0][i] for n in weights) for i in range(len(yht))]
    ens_a = [sum(weights[n] * predictions[n][1][i] for n in weights) for i in range(len(yat))]
    metrics = {}
    for name, (ph, pa) in predictions.items():
        metrics[name] = {"home_rmse": rmse(yht, ph), "away_rmse": rmse(yat, pa),
                         "home_mae": mae(yht, ph), "away_mae": mae(yat, pa)}
    metrics["ensemble"] = {"home_rmse": rmse(yht, ens_h), "away_rmse": rmse(yat, ens_a),
                           "home_mae": mae(yht, ens_h), "away_mae": mae(yat, ens_a)}
    return {
        "schema": SCHEMA,
        "status": "TRAINED_RESEARCH_ONLY",
        "research_only": True,
        "promotion_eligible": False,
        "games": len(paired), "train_games": len(train), "holdout_games": len(test),
        "feature_names": list(FEATURE_NAMES), "models": models, "ensemble_weights": weights,
        "holdout_metrics": metrics,
        "dataset_fingerprint": dataset_fingerprint([r for r, _ in paired], [l for _, l in paired]),
        "claims": [
            "historical reconstructed evidence may rank research challengers but cannot satisfy native-live promotion floors",
            "portable models use only pregame feature rows and separate labels",
        ],
    }


def predict(artifact: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    if str(artifact.get("status")) != "TRAINED_RESEARCH_ONLY":
        return {"available": False, "reason": "model_not_trained"}
    x = vectorize(row); models = artifact.get("models") or {}
    preds = {}
    for name, predictor in (("glm", predict_glm), ("gam", predict_gam), ("gbdt", predict_gbdt)):
        m = models.get(name) or {}
        if m:
            preds[name] = (predictor(m.get("home") or {}, x), predictor(m.get("away") or {}, x))
    if "glm" in preds and models.get("hierarchical"):
        preds["hierarchical"] = apply_hierarchical(models["hierarchical"], row, *preds["glm"])
    weights = artifact.get("ensemble_weights") or {}
    if weights and all(n in preds for n in weights):
        h = sum(float(weights[n]) * preds[n][0] for n in weights)
        a = sum(float(weights[n]) * preds[n][1] for n in weights)
    elif preds:
        h = sum(x[0] for x in preds.values()) / len(preds); a = sum(x[1] for x in preds.values()) / len(preds)
    else:
        return {"available": False, "reason": "candidate_models_missing"}
    return {"available": True, "research_only": True, "affects_champion": False,
            "home_runs": _clip(h, .15, 15.0), "away_runs": _clip(a, .15, 15.0), "candidates": preds}


def _read_jsonl_gz(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try: out.append(json.loads(line))
                except Exception: pass
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
    summary = {k: artifact.get(k) for k in ("schema", "status", "games", "train_games", "holdout_games", "ensemble_weights", "holdout_metrics", "dataset_fingerprint")}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
