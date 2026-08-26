from __future__ import annotations

"""Parsimonious team-run challenger trained only on strict PIT team history.

The goal is not to manufacture a sophisticated model.  Parameters are selected
on 2021-2024 only, evaluated on untouched 2025, then audited on frozen 2026.
No result from this module can auto-activate production V14.
"""

import math
from typing import Any, Iterable

LEAGUE_RPG = 4.45
PARAM_GRID = tuple(
    {
        "season_prior_games": prior,
        "recent14_weight": w14,
        "recent7_weight": w7,
        "offense_weight": ow,
        "home_advantage_runs": ha,
        "park_weight": pw,
    }
    for prior in (15.0, 30.0, 45.0, 60.0)
    for w14 in (0.0, 0.10, 0.20)
    for w7 in (0.0, 0.05, 0.10)
    if w14 + w7 <= 0.25
    for ow in (0.45, 0.50, 0.55)
    for ha in (0.08, 0.12, 0.16)
    for pw in (0.0, 0.5)
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _summary(feature: dict[str, Any], side: str, window: str) -> dict[str, Any]:
    return (((feature.get("features") or {}).get(f"{side}_team_form") or {}).get(window) or {})


def _shrink(rate: float, games: float, prior_mean: float, prior_games: float) -> float:
    n = max(0.0, float(games))
    p = max(0.0, float(prior_games))
    return (float(rate) * n + float(prior_mean) * p) / max(1e-9, n + p)


def _park_factor(feature: dict[str, Any]) -> float:
    park = ((feature.get("features") or {}).get("park_prior") or {})
    candidates = (park.get("run_factor"), park.get("ALL"), park.get("all"), park.get("factor"))
    for raw in candidates:
        if raw is None:
            continue
        value = _num(raw, 1.0)
        if 0.70 <= value <= 1.30:
            return value
        if 70.0 <= value <= 130.0:
            return value / 100.0
    return 1.0


def baseline_runs(feature: dict[str, Any]) -> tuple[float, float]:
    hs = _summary(feature, "home", "season_to_date")
    aws = _summary(feature, "away", "season_to_date")
    home_off = _num(hs.get("runs_for_pg"), LEAGUE_RPG)
    away_off = _num(aws.get("runs_for_pg"), LEAGUE_RPG)
    home_def = _num(hs.get("runs_against_pg"), LEAGUE_RPG)
    away_def = _num(aws.get("runs_against_pg"), LEAGUE_RPG)
    return max(0.5, 0.5 * (home_off + away_def) + 0.12), max(0.5, 0.5 * (away_off + home_def))


def _talent(feature: dict[str, Any], side: str, params: dict[str, float]) -> tuple[float, float]:
    season = _summary(feature, side, "season_to_date")
    n = _num(season.get("games"), 0.0)
    prior = _num(params.get("season_prior_games"), 30.0)
    season_off = _shrink(_num(season.get("runs_for_pg"), LEAGUE_RPG), n, LEAGUE_RPG, prior)
    season_def = _shrink(_num(season.get("runs_against_pg"), LEAGUE_RPG), n, LEAGUE_RPG, prior)
    out_off, out_def = season_off, season_def
    for window, weight_key, prior_games in (("last_14_games", "recent14_weight", 10.0), ("last_7_games", "recent7_weight", 6.0)):
        recent = _summary(feature, side, window)
        rn = _num(recent.get("games"), 0.0)
        if rn <= 0:
            continue
        recent_off = _shrink(_num(recent.get("runs_for_pg"), season_off), rn, season_off, prior_games)
        recent_def = _shrink(_num(recent.get("runs_against_pg"), season_def), rn, season_def, prior_games)
        weight = _num(params.get(weight_key), 0.0)
        out_off += weight * (recent_off - season_off)
        out_def += weight * (recent_def - season_def)
    return max(1.5, min(8.0, out_off)), max(1.5, min(8.0, out_def))


def candidate_runs(feature: dict[str, Any], params: dict[str, float]) -> tuple[float, float]:
    home_off, home_def = _talent(feature, "home", params)
    away_off, away_def = _talent(feature, "away", params)
    ow = _num(params.get("offense_weight"), 0.5)
    home = ow * home_off + (1.0 - ow) * away_def + _num(params.get("home_advantage_runs"), 0.12)
    away = ow * away_off + (1.0 - ow) * home_def
    park = _park_factor(feature)
    park_multiplier = 1.0 + _num(params.get("park_weight"), 0.0) * (park - 1.0)
    return max(0.5, min(10.0, home * park_multiplier)), max(0.5, min(10.0, away * park_multiplier))


def _score_errors(pairs: Iterable[tuple[dict[str, Any], dict[str, Any]]], predictor) -> dict[str, Any]:
    team_sq: list[float] = []
    team_abs: list[float] = []
    total_sq: list[float] = []
    total_abs: list[float] = []
    home_bias: list[float] = []
    away_bias: list[float] = []
    game_sq: dict[str, float] = {}
    game_total_abs: dict[str, float] = {}
    n = 0
    for feature, label in pairs:
        ph, pa = predictor(feature)
        hs, aws = _num(label.get("home_score")), _num(label.get("away_score"))
        gid = str(feature.get("game_pk") or "")
        he, ae = hs - ph, aws - pa
        team_sq.extend((he * he, ae * ae)); team_abs.extend((abs(he), abs(ae)))
        te = (hs + aws) - (ph + pa); total_sq.append(te * te); total_abs.append(abs(te))
        home_bias.append(ph - hs); away_bias.append(pa - aws)
        game_sq[gid] = (he * he + ae * ae) / 2.0
        game_total_abs[gid] = abs(te)
        n += 1
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "team_rmse": math.sqrt(sum(team_sq) / len(team_sq)),
        "team_mae": sum(team_abs) / len(team_abs),
        "total_rmse": math.sqrt(sum(total_sq) / n),
        "total_mae": sum(total_abs) / n,
        "home_bias": sum(home_bias) / n,
        "away_bias": sum(away_bias) / n,
        "_game_sq": game_sq,
        "_game_total_abs": game_total_abs,
    }


def _mean_ci(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95_lower": None, "ci95_upper": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"n": len(values), "mean": mean, "ci95_lower": None, "ci95_upper": None}
    var = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    se = math.sqrt(var / len(values))
    return {"n": len(values), "mean": mean, "ci95_lower": mean - 1.96 * se, "ci95_upper": mean + 1.96 * se}


def paired_gain(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    common = sorted(set(candidate.get("_game_sq") or {}) & set(baseline.get("_game_sq") or {}))
    mse = _mean_ci([baseline["_game_sq"][g] - candidate["_game_sq"][g] for g in common])
    total = _mean_ci([baseline["_game_total_abs"][g] - candidate["_game_total_abs"][g] for g in common])
    return {"team_mse_gain": mse, "total_mae_gain": total}


def _public(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in metrics.items() if not str(k).startswith("_")}


def tune(tuning_pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    if len(tuning_pairs) < 1000:
        return {"status": "COLLECTING", "n": len(tuning_pairs), "required": 1000}
    best = None
    for params in PARAM_GRID:
        metrics = _score_errors(tuning_pairs, lambda row, p=params: candidate_runs(row, p))
        objective = float(metrics["team_rmse"]) + 0.15 * float(metrics["total_mae"])
        key = (objective, abs(float(metrics["home_bias"])) + abs(float(metrics["away_bias"])), str(params))
        if best is None or key < best[0]:
            best = (key, dict(params), metrics)
    assert best is not None
    return {
        "status": "TUNED_RESEARCH_ONLY",
        "n": len(tuning_pairs),
        "grid_candidates": len(PARAM_GRID),
        "parameters": best[1],
        "metrics": _public(best[2]),
        "selection_objective": "team_rmse + 0.15 * total_mae; 2021-2024 only",
    }


def evaluate_split(pairs: list[tuple[dict[str, Any], dict[str, Any]]], params: dict[str, float]) -> dict[str, Any]:
    base = _score_errors(pairs, baseline_runs)
    cand = _score_errors(pairs, lambda row: candidate_runs(row, params))
    return {"baseline": _public(base), "candidate": _public(cand), "paired": paired_gain(cand, base)}


def historical_gate(validation: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    v = ((validation.get("paired") or {}).get("team_mse_gain") or {})
    f = ((frozen.get("paired") or {}).get("team_mse_gain") or {})
    vt = ((validation.get("paired") or {}).get("total_mae_gain") or {})
    ft = ((frozen.get("paired") or {}).get("total_mae_gain") or {})
    validation_pass = bool(v.get("ci95_lower") is not None and float(v["ci95_lower"]) > 0 and vt.get("ci95_lower") is not None and float(vt["ci95_lower"]) >= -0.05)
    frozen_nonreg = bool(f.get("mean") is not None and float(f["mean"]) >= 0 and f.get("ci95_lower") is not None and float(f["ci95_lower"]) >= -0.03 and ft.get("mean") is not None and float(ft["mean"]) >= -0.05)
    validated = validation_pass and frozen_nonreg
    return {
        "status": "HISTORICAL_VALIDATED" if validated else "REJECTED_HISTORICAL",
        "passes": validated,
        "validation_pass": validation_pass,
        "frozen_2026_nonregression": frozen_nonreg,
        "gate": "2025 paired team-MSE gain CI95 lower > 0; total-MAE CI95 >= -0.05; frozen 2026 point team-MSE gain >=0 with CI95 >= -0.03 and total-MAE point gain >= -0.05",
        "auto_activation": False,
        "native_live_confirmation_required": True,
    }
