from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import random
from typing import Any

FEATURE_FILE = Path("data/v13_feature_store.jsonl")
LABEL_FILE = Path("data/v13_label_store.jsonl")
MODEL_FILE = Path("data/v14_run_model.json")
SCHEMA = "v14-native-run-model-v1"
SOURCE_FEATURE_SCHEMA = "v13-pit-feature-store-v1"
SOURCE_FEATURE_CONTRACT = "v13-baseball-features-v1"
SOURCE_LABEL_SCHEMA = "v13-label-store-v1"

FEATURE_NAMES = (
    "home_indicator",
    "offense_ops",
    "lineup_ops",
    "opponent_team_era",
    "opponent_starter_era",
    "opponent_starter_whip",
    "park_factor",
)

MIN_NATIVE_GAMES = 300
MIN_HOLDOUT_GAMES = 60
BOOTSTRAP_DRAWS = 1500
BOOTSTRAP_MIN_POSITIVE_PROBABILITY = 0.90
RIDGE_GRID = (0.1, 1.0, 10.0)
MIN_MU = 0.20
MAX_MU = 15.0


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _num(value: Any) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except Exception:
            continue
    return rows


def _source_attested(row: dict[str, Any], names: tuple[str, ...] = ("team_stats", "lineup", "starter_stats")) -> bool:
    as_of = _dt(row.get("as_of"))
    if as_of is None:
        return False
    provenance = row.get("feature_provenance") or {}
    for name in names:
        source = provenance.get(name) or {}
        observed = _dt(source.get("observed_at"))
        if not source.get("source") or not source.get("timestamp_basis"):
            return False
        if source.get("source_timestamp_attested") is not True or source.get("point_in_time") is not True:
            return False
        if source.get("postgame_identity") is True:
            return False
        if observed is None or observed > as_of:
            return False
    return True


def _feature_valid(row: dict[str, Any]) -> tuple[bool, str]:
    if row.get("schema") != SOURCE_FEATURE_SCHEMA:
        return False, "wrong_feature_schema"
    if row.get("feature_contract") != SOURCE_FEATURE_CONTRACT:
        return False, "wrong_feature_contract"
    if str(row.get("phase") or "").upper() != "FINAL":
        return False, "not_final_phase"
    if row.get("point_in_time") is not True:
        return False, "not_point_in_time"
    as_of, game_time = _dt(row.get("as_of")), _dt(row.get("game_date"))
    if as_of is None or game_time is None or as_of >= game_time:
        return False, "not_pregame"
    if not _source_attested(row):
        return False, "source_timestamp_not_promotion_grade"
    features = row.get("features") or {}
    park = features.get("park_factor_runtime") or {}
    if park.get("leakage_safe") is not True:
        return False, "park_factor_not_leakage_safe"
    return True, "PASS"


def _label_valid(row: dict[str, Any]) -> tuple[bool, str]:
    if row.get("schema") != SOURCE_LABEL_SCHEMA:
        return False, "wrong_label_schema"
    if not row.get("game_pk") or row.get("home_score") is None or row.get("away_score") is None:
        return False, "incomplete_label"
    game_time, settled = _dt(row.get("game_date")), _dt(row.get("settled_at"))
    if game_time is None or settled is None or settled < game_time:
        return False, "label_not_postgame_attested"
    try:
        home_score, away_score = int(row["home_score"]), int(row["away_score"])
    except Exception:
        return False, "invalid_score"
    if home_score < 0 or away_score < 0 or home_score == away_score:
        return False, "invalid_mlb_final_score"
    return True, "PASS"


def _side_features(row: dict[str, Any], home_side: bool) -> list[float] | None:
    features = row.get("features") or {}
    context = row.get("context") or {}
    offense = _num(features.get("home_ops" if home_side else "away_ops"))
    lineup = _num(features.get("home_lineup_ops" if home_side else "away_lineup_ops"))
    opp_era = _num(features.get("away_team_era" if home_side else "home_team_era"))
    starter = context.get("away_starter" if home_side else "home_starter") or {}
    starter_era = _num(starter.get("era"))
    starter_whip = _num(starter.get("whip"))
    park_factor = _num(features.get("park_factor"))
    values = [1.0 if home_side else 0.0, offense, lineup, opp_era, starter_era, starter_whip, park_factor]
    if any(v is None for v in values):
        return None
    # Broad sanity envelope only. No value is winsorized into plausibility.
    if not (0.25 <= offense <= 1.50 and 0.25 <= lineup <= 1.50):
        return None
    if not (0.0 <= opp_era <= 20.0 and 0.0 <= starter_era <= 20.0 and 0.0 <= starter_whip <= 5.0):
        return None
    if not (0.70 <= park_factor <= 1.35):
        return None
    return [float(v) for v in values]


def native_games(feature_rows: list[dict[str, Any]], label_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    feature_best: dict[str, dict[str, Any]] = {}
    feature_rejects: Counter = Counter()
    source_generations: Counter = Counter()
    for row in feature_rows:
        valid, reason = _feature_valid(row)
        if not valid:
            feature_rejects[reason] += 1
            continue
        home_x, away_x = _side_features(row, True), _side_features(row, False)
        if home_x is None or away_x is None:
            feature_rejects["missing_or_invalid_minimal_features"] += 1
            continue
        gid = str(row.get("game_pk") or "")
        if not gid:
            feature_rejects["missing_game_pk"] += 1
            continue
        rank = str(row.get("as_of") or "")
        old = feature_best.get(gid)
        if old is None or rank > str(old.get("as_of") or ""):
            clone = dict(row)
            clone["_home_x"] = home_x
            clone["_away_x"] = away_x
            feature_best[gid] = clone
        source_generations[str(row.get("model_generation") or "unknown")] += 1

    labels: dict[str, dict[str, Any]] = {}
    label_rejects: Counter = Counter()
    for row in label_rows:
        valid, reason = _label_valid(row)
        if not valid:
            label_rejects[reason] += 1
            continue
        gid = str(row.get("game_pk"))
        old = labels.get(gid)
        if old is None or str(row.get("settled_at") or "") > str(old.get("settled_at") or ""):
            labels[gid] = row

    games: list[dict[str, Any]] = []
    for gid, feature in feature_best.items():
        label = labels.get(gid)
        if label is None:
            continue
        games.append({
            "game_pk": gid,
            "game_date": feature.get("game_date"),
            "as_of": feature.get("as_of"),
            "home_x": feature["_home_x"],
            "away_x": feature["_away_x"],
            "home_runs": int(label["home_score"]),
            "away_runs": int(label["away_score"]),
        })
    games.sort(key=lambda g: (str(g.get("game_date") or ""), g["game_pk"]))
    report = {
        "eligible_feature_games": len(feature_best),
        "eligible_label_games": len(labels),
        "joined_native_games": len(games),
        "feature_rejections": dict(feature_rejects),
        "label_rejections": dict(label_rejects),
        "source_model_generations": dict(source_generations),
    }
    return games, report


def _scaler(samples: list[list[float]]) -> tuple[list[float], list[float]]:
    if not samples:
        raise ValueError("empty training samples")
    p = len(samples[0])
    means = [sum(row[j] for row in samples) / len(samples) for j in range(p)]
    scales = []
    for j in range(p):
        variance = sum((row[j] - means[j]) ** 2 for row in samples) / len(samples)
        scales.append(max(math.sqrt(variance), 1e-6))
    return means, scales


def _design(x: list[float], means: list[float], scales: list[float]) -> list[float]:
    return [1.0] + [(x[j] - means[j]) / scales[j] for j in range(len(x))]


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    a = [list(matrix[i]) + [float(vector[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular V14 run-model system")
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [v / scale for v in a[col]]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if abs(factor) <= 1e-18:
                continue
            a[row] = [a[row][j] - factor * a[col][j] for j in range(n + 1)]
    return [a[i][-1] for i in range(n)]


def _fit_poisson(xs: list[list[float]], ys: list[int], ridge: float) -> dict[str, Any]:
    if len(xs) != len(ys) or not xs:
        raise ValueError("invalid training matrix")
    means, scales = _scaler(xs)
    design = [_design(x, means, scales) for x in xs]
    p = len(design[0])
    mean_y = max(MIN_MU, sum(ys) / len(ys))
    beta = [math.log(mean_y)] + [0.0] * (p - 1)
    iterations = 0
    for iteration in range(40):
        lhs = [[0.0] * p for _ in range(p)]
        rhs = [0.0] * p
        for row, y in zip(design, ys):
            eta = max(-3.0, min(3.0, sum(b * x for b, x in zip(beta, row))))
            mu = max(MIN_MU, min(MAX_MU, math.exp(eta)))
            z = eta + (float(y) - mu) / mu
            weight = mu
            for j in range(p):
                rhs[j] += weight * row[j] * z
                for k in range(p):
                    lhs[j][k] += weight * row[j] * row[k]
        for j in range(1, p):
            lhs[j][j] += float(ridge) * len(xs)
        new_beta = _solve(lhs, rhs)
        iterations = iteration + 1
        if max(abs(a - b) for a, b in zip(new_beta, beta)) < 1e-8:
            beta = new_beta
            break
        beta = new_beta
    return {"feature_names": list(FEATURE_NAMES), "means": means, "scales": scales,
            "coefficients": beta, "ridge": float(ridge), "iterations": iterations}


def _predict(model: dict[str, Any], x: list[float]) -> float:
    means = [float(v) for v in model["means"]]
    scales = [float(v) for v in model["scales"]]
    beta = [float(v) for v in model["coefficients"]]
    row = _design(x, means, scales)
    eta = max(-3.0, min(3.0, sum(b * v for b, v in zip(beta, row))))
    return max(MIN_MU, min(MAX_MU, math.exp(eta)))


def _poisson_nll(mu: float, y: int) -> float:
    mu = max(MIN_MU, min(MAX_MU, float(mu)))
    return mu - int(y) * math.log(mu)


def _game_errors(model: dict[str, Any], game: dict[str, Any], baseline: tuple[float, float] | None = None) -> dict[str, float]:
    if baseline is None:
        home_mu = _predict(model, game["home_x"])
        away_mu = _predict(model, game["away_x"])
    else:
        home_mu, away_mu = baseline
    hs, aps = int(game["home_runs"]), int(game["away_runs"])
    sq = 0.5 * ((home_mu - hs) ** 2 + (away_mu - aps) ** 2)
    ae = 0.5 * (abs(home_mu - hs) + abs(away_mu - aps))
    nll = 0.5 * (_poisson_nll(home_mu, hs) + _poisson_nll(away_mu, aps))
    return {"mse": sq, "mae": ae, "poisson_nll": nll, "home_mu": home_mu, "away_mu": away_mu}


def _metrics(errors: list[dict[str, float]]) -> dict[str, float | int | None]:
    if not errors:
        return {"n_games": 0, "rmse": None, "mae": None, "poisson_nll": None}
    n = len(errors)
    return {"n_games": n,
            "rmse": math.sqrt(sum(e["mse"] for e in errors) / n),
            "mae": sum(e["mae"] for e in errors) / n,
            "poisson_nll": sum(e["poisson_nll"] for e in errors) / n}


def _flatten(games: list[dict[str, Any]]) -> tuple[list[list[float]], list[int]]:
    xs: list[list[float]] = []
    ys: list[int] = []
    for game in games:
        xs.extend((game["home_x"], game["away_x"]))
        ys.extend((int(game["home_runs"]), int(game["away_runs"])))
    return xs, ys


def _baseline_means(games: list[dict[str, Any]]) -> tuple[float, float]:
    return (sum(g["home_runs"] for g in games) / len(games),
            sum(g["away_runs"] for g in games) / len(games))


def _bootstrap(candidate_errors: list[dict[str, float]], baseline_errors: list[dict[str, float]]) -> dict[str, Any]:
    n = len(candidate_errors)
    if n < MIN_HOLDOUT_GAMES or n != len(baseline_errors):
        return {"draws": 0, "mse_gain_positive_probability": None,
                "poisson_nll_gain_positive_probability": None, "passes": False}
    mse_gain = [b["mse"] - c["mse"] for c, b in zip(candidate_errors, baseline_errors)]
    nll_gain = [b["poisson_nll"] - c["poisson_nll"] for c, b in zip(candidate_errors, baseline_errors)]
    rng = random.Random("v14-native-run-model-bootstrap-v1")
    mse_pos = nll_pos = 0
    for _ in range(BOOTSTRAP_DRAWS):
        indices = [rng.randrange(n) for _ in range(n)]
        mse_pos += (sum(mse_gain[i] for i in indices) / n) > 0
        nll_pos += (sum(nll_gain[i] for i in indices) / n) > 0
    mp = mse_pos / BOOTSTRAP_DRAWS
    np = nll_pos / BOOTSTRAP_DRAWS
    return {"draws": BOOTSTRAP_DRAWS,
            "mse_gain_positive_probability": mp,
            "poisson_nll_gain_positive_probability": np,
            "minimum_positive_probability": BOOTSTRAP_MIN_POSITIVE_PROBABILITY,
            "passes": mp >= BOOTSTRAP_MIN_POSITIVE_PROBABILITY and np >= BOOTSTRAP_MIN_POSITIVE_PROBABILITY}


def build(feature_rows: list[dict[str, Any]] | None = None,
          label_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    features = _read_jsonl(FEATURE_FILE) if feature_rows is None else list(feature_rows)
    labels = _read_jsonl(LABEL_FILE) if label_rows is None else list(label_rows)
    games, source = native_games(features, labels)
    base = {
        "schema": SCHEMA,
        "role": "V14_NATIVE_RUN_MODEL_SHADOW_ONLY",
        "active_for_shadow": False,
        "affects_production": False,
        "market_probability_used": False,
        "feature_names": list(FEATURE_NAMES),
        "native_games": len(games),
        "minimum_native_games": MIN_NATIVE_GAMES,
        "source": source,
        "training_policy": {
            "source": "genuine FINAL pregame PIT feature snapshots + separately settled labels",
            "used_features": list(FEATURE_NAMES),
            "unused_by_design": ["market odds", "V13 probabilities", "weather", "bullpen detail", "Statcast", "V13 engineered run deltas"],
            "split": "chronological 60% train / 20% validation / 20% untouched holdout",
            "selection": "ridge strength selected on validation Poisson NLL; refit train+validation; untouched holdout scored once",
            "baseline": "train+validation home/away league run means only",
            "activation": f">={MIN_NATIVE_GAMES} games, >= {MIN_HOLDOUT_GAMES} untouched games, positive RMSE and Poisson-NLL gain, paired bootstrap >= {BOOTSTRAP_MIN_POSITIVE_PROBABILITY:.0%}",
        },
    }
    if len(games) < MIN_NATIVE_GAMES:
        base["status"] = "COLLECTING_NATIVE_PIT"
        base["games_needed"] = MIN_NATIVE_GAMES - len(games)
        return base

    n = len(games)
    train_end = int(n * 0.60)
    val_end = int(n * 0.80)
    train = games[:train_end]
    validation = games[train_end:val_end]
    holdout = games[val_end:]
    if len(holdout) < MIN_HOLDOUT_GAMES or not train or not validation:
        base["status"] = "COLLECTING_HOLDOUT_VOLUME"
        base["holdout_games"] = len(holdout)
        return base

    train_x, train_y = _flatten(train)
    candidates = []
    for ridge in RIDGE_GRID:
        model = _fit_poisson(train_x, train_y, ridge)
        errors = [_game_errors(model, game) for game in validation]
        metrics = _metrics(errors)
        candidates.append({"ridge": ridge, "model": model, "validation": metrics})
    candidates.sort(key=lambda c: (float(c["validation"]["poisson_nll"]), float(c["validation"]["rmse"]), float(c["ridge"])))
    chosen = candidates[0]

    fit_games = games[:val_end]
    fit_x, fit_y = _flatten(fit_games)
    model = _fit_poisson(fit_x, fit_y, float(chosen["ridge"]))
    baseline = _baseline_means(fit_games)
    candidate_errors = [_game_errors(model, game) for game in holdout]
    baseline_errors = [_game_errors(model, game, baseline=baseline) for game in holdout]
    candidate_metrics = _metrics(candidate_errors)
    baseline_metrics = _metrics(baseline_errors)
    rmse_gain = float(baseline_metrics["rmse"]) - float(candidate_metrics["rmse"])
    nll_gain = float(baseline_metrics["poisson_nll"]) - float(candidate_metrics["poisson_nll"])
    bootstrap = _bootstrap(candidate_errors, baseline_errors)
    passed = rmse_gain > 0 and nll_gain > 0 and bootstrap.get("passes") is True

    base.update({
        "status": "VALIDATED_NATIVE_SHADOW" if passed else "NATIVE_CANDIDATE_REJECTED",
        "active_for_shadow": bool(passed),
        "chronological_split": {"train_games": len(train), "validation_games": len(validation),
                                "fit_games": len(fit_games), "holdout_games": len(holdout)},
        "ridge_selection": [{"ridge": c["ridge"], "validation": c["validation"]} for c in candidates],
        "selected_ridge": chosen["ridge"],
        "model": model,
        "baseline": {"home_mu": baseline[0], "away_mu": baseline[1], "holdout": baseline_metrics},
        "holdout": candidate_metrics,
        "rmse_gain_vs_train_only_league_mean": rmse_gain,
        "poisson_nll_gain_vs_train_only_league_mean": nll_gain,
        "bootstrap": bootstrap,
        "activation_gate_passes": bool(passed),
    })
    return base


def predict_pair(feature_row: dict[str, Any], artifact: dict[str, Any]) -> tuple[float, float] | None:
    if artifact.get("schema") != SCHEMA or artifact.get("active_for_shadow") is not True:
        return None
    valid, _ = _feature_valid(feature_row)
    if not valid:
        return None
    home_x, away_x = _side_features(feature_row, True), _side_features(feature_row, False)
    if home_x is None or away_x is None:
        return None
    model = artifact.get("model") or {}
    try:
        return _predict(model, home_x), _predict(model, away_x)
    except Exception:
        return None


def save(artifact: dict[str, Any], path: Path = MODEL_FILE) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Train minimal V14 native PIT run model")
    parser.add_argument("--features", default=str(FEATURE_FILE))
    parser.add_argument("--labels", default=str(LABEL_FILE))
    parser.add_argument("--output", default=str(MODEL_FILE))
    args = parser.parse_args()
    artifact = build(_read_jsonl(Path(args.features)), _read_jsonl(Path(args.labels)))
    save(artifact, Path(args.output))
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
