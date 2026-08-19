from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract
from . import v138_research_models as research_models
from .v138_audit_features import park_factor

EXACT = Path("data/v13_historical_backfill.jsonl")
OUT = Path("data/v13_run_mean_prior.json")
DATA_DIR = Path("data/v137")
SCHEMA = "v13-run-mean-prior-v2"
DISPERSION = 2.835691107635618
MAX_ADJ = 0.15
MIN_WARM = 10
MIN_WF_FOLDS = 3
MIN_WF_TEST_GAMES = 500
MIN_EXACT_FINAL = 60
EXACT_BOOTSTRAP_DRAWS = 1200
RIDGES = (10.0, 25.0, 50.0, 100.0, 200.0, 400.0, 800.0)


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _season(row: dict[str, Any]) -> int:
    try:
        return int(row.get("season") or str(row.get("game_date") or "")[:4])
    except Exception:
        return 0


def _dataset_content_sha256(base: Path = DATA_DIR) -> str:
    h = hashlib.sha256()
    paths = sorted(base.glob("team_features_*.jsonl.gz")) + sorted(base.glob("team_labels_*.jsonl.gz"))
    for path in paths:
        h.update(path.name.encode("utf-8"))
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest() if paths else ""


def _historical_rows(exclude_game_ids: set[str] | None = None) -> tuple[list[dict[str, Any]], int]:
    exclude = {str(x) for x in (exclude_game_ids or set())}
    features, labels = research_models.load_free_dataset(DATA_DIR)
    by_label = {str(x.get("game_pk")): x for x in labels if x.get("home_score") is not None and x.get("away_score") is not None}
    source_games = 0
    out: list[dict[str, Any]] = []
    for row in features:
        gid = str(row.get("game_pk") or "")
        label = by_label.get(gid)
        if not gid or label is None:
            continue
        source_games += 1
        if gid in exclude:
            continue
        f = row.get("features") or {}
        home_form = (f.get("home_team_form") or {}).get("season_to_date") or {}
        away_form = (f.get("away_team_form") or {}).get("season_to_date") or {}
        if min(int(home_form.get("games") or 0), int(away_form.get("games") or 0)) < MIN_WARM:
            continue
        home_mu, away_mu = research_models.naive_runs(row)
        pf = _num(park_factor(f.get("park_prior") or {}).get("run_factor"), 1.0)
        pf = max(0.75, min(1.25, pf))
        out.append({
            "game_pk": gid,
            "game_date": row.get("game_date") or row.get("as_of"),
            "season": _season(row),
            "phase": "FINAL_RECONSTRUCTED_FREE",
            "home_mu": max(0.2, home_mu * pf),
            "away_mu": max(0.2, away_mu * pf),
            "home_score": int(_num(label.get("home_score"))),
            "away_score": int(_num(label.get("away_score"))),
            "cohort": row.get("cohort"),
            "point_in_time": bool(row.get("point_in_time")),
        })
    return sorted(out, key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or ""))), source_games


def _exact_rows() -> list[dict[str, Any]]:
    """Only current-generation FINAL replays with an independent pre-prior V13 baseline count."""
    if not EXACT.exists():
        return []
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    with EXACT.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if str(row.get("phase") or "").upper() != "FINAL":
                continue
            if not contract.row_is_predictively_compatible(row):
                continue
            if row.get("home_score") is None or row.get("away_score") is None:
                continue
            hmu = row.get("validation_baseline_home_runs")
            amu = row.get("validation_baseline_away_runs")
            dispersion = row.get("validation_baseline_dispersion")
            if hmu is None or amu is None or dispersion is None:
                continue
            if row.get("validation_baseline_model_generation") != contract.MODEL_GENERATION_FINGERPRINT:
                continue
            gid = str(row.get("game_pk") or "")
            rank = str(row.get("analyzed_at") or "")
            if gid and (gid not in best or rank > best[gid][0]):
                best[gid] = (rank, row)
    out = []
    for _, row in best.values():
        out.append({
            "game_pk": row.get("game_pk"),
            "game_date": row.get("game_date"),
            "season": _season(row),
            "phase": "FINAL",
            "home_mu": _num(row.get("validation_baseline_home_runs")),
            "away_mu": _num(row.get("validation_baseline_away_runs")),
            "dispersion": _num(row.get("validation_baseline_dispersion"), DISPERSION),
            "home_score": int(_num(row.get("home_score"))),
            "away_score": int(_num(row.get("away_score"))),
        })
    return sorted(out, key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or "")))


def _solve3(a: list[list[float]], b: list[float]) -> list[float]:
    m = [list(a[i]) + [b[i]] for i in range(3)]
    for c in range(3):
        pivot = max(range(c, 3), key=lambda r: abs(m[r][c]))
        m[c], m[pivot] = m[pivot], m[c]
        if abs(m[c][c]) < 1e-12:
            continue
        d = m[c][c]
        m[c] = [x / d for x in m[c]]
        for r in range(3):
            if r == c:
                continue
            factor = m[r][c]
            m[r] = [x - factor * y for x, y in zip(m[r], m[c])]
    return [m[i][3] for i in range(3)]


def _fit(rows: list[dict[str, Any]], ridge: float, affine: bool = True) -> dict[str, Any]:
    ata = [[0.0] * 3 for _ in range(3)]
    aty = [0.0] * 3
    for row in rows:
        for side in ("home", "away"):
            mu = max(0.1, _num(row[f"{side}_mu"]))
            y = _num(row[f"{side}_score"])
            x = [1.0 if side == "home" else 0.0, 1.0 if side == "away" else 0.0, mu if affine else 0.0]
            target = y - mu
            for i in range(3):
                aty[i] += x[i] * target
                for j in range(3):
                    ata[i][j] += x[i] * x[j]
    for i in range(3):
        ata[i][i] += ridge
    coeff = _solve3(ata, aty)
    if not affine:
        coeff[2] = 0.0
    return {
        "home_bias": coeff[0],
        "away_bias": coeff[1],
        "slope_delta": coeff[2],
        "ridge": ridge,
        "formula": "mu + side_bias + slope_delta*mu",
        "max_adjustment": MAX_ADJ,
    }


def apply(mu: float, side: str, model: dict[str, Any]) -> float:
    bias = _num(model.get(f"{side}_bias"))
    slope_delta = _num(model.get("slope_delta"))
    cap = min(MAX_ADJ, max(0.0, _num(model.get("max_adjustment"), MAX_ADJ)))
    adjustment = max(-cap, min(cap, bias + slope_delta * mu))
    return max(1.4, mu + adjustment)


def _nb_nll(mu: float, y: float, dispersion: float = DISPERSION) -> float:
    r = max(0.5, _num(dispersion, DISPERSION))
    mu = max(0.01, mu)
    y = max(0, int(y))
    p = r / (r + mu)
    return -(math.lgamma(y + r) - math.lgamma(r) - math.lgamma(y + 1) + r * math.log(p) + y * math.log1p(-p))


def _metrics(rows: list[dict[str, Any]], model: dict[str, Any] | None = None) -> dict[str, Any]:
    ae: list[float] = []
    se: list[float] = []
    nl: list[float] = []
    for row in rows:
        dispersion = _num(row.get("dispersion"), DISPERSION)
        for side in ("home", "away"):
            base = max(0.1, _num(row[f"{side}_mu"]))
            mu = apply(base, side, model) if model else base
            y = _num(row[f"{side}_score"])
            ae.append(abs(mu - y))
            se.append((mu - y) ** 2)
            nl.append(_nb_nll(mu, y, dispersion))
    n = len(ae)
    return {
        "team_observations": n,
        "mae": sum(ae) / n if n else None,
        "rmse": math.sqrt(sum(se) / n) if n else None,
        "nb_nll": sum(nl) / n if n else None,
    }


def _gain(rows: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    baseline = _metrics(rows)
    candidate = _metrics(rows, model)
    return {
        "games": len(rows),
        "baseline": baseline,
        "candidate": candidate,
        "mae_gain": baseline["mae"] - candidate["mae"] if baseline["mae"] is not None else None,
        "rmse_gain": baseline["rmse"] - candidate["rmse"] if baseline["rmse"] is not None else None,
        "nll_gain": baseline["nb_nll"] - candidate["nb_nll"] if baseline["nb_nll"] is not None else None,
    }


def _passes(evaluation: dict[str, Any], min_games: int) -> bool:
    return bool(
        evaluation.get("games", 0) >= min_games
        and evaluation.get("rmse_gain") is not None
        and evaluation.get("nll_gain") is not None
        and evaluation.get("mae_gain") is not None
        and evaluation["rmse_gain"] > 0
        and evaluation["nll_gain"] > 0
        and evaluation["mae_gain"] >= -0.01
    )


def _select_variant(train: list[dict[str, Any]], validation: list[dict[str, Any]]) -> dict[str, Any] | None:
    variants = []
    for affine in (False, True):
        name = "side_bias" if not affine else "side_bias_shared_slope"
        for ridge in RIDGES:
            model = _fit(train, ridge, affine)
            evaluation = _gain(validation, model)
            if _passes(evaluation, min(MIN_WF_TEST_GAMES, max(50, len(validation) // 2))):
                variants.append((evaluation["nll_gain"], evaluation["rmse_gain"], name, ridge, model, evaluation))
    if not variants:
        return None
    variants.sort(reverse=True, key=lambda z: (z[0], z[1]))
    best = variants[0]
    simple = [z for z in variants if z[2] == "side_bias" and z[0] >= best[0] - 0.0005]
    chosen = max(simple, key=lambda z: (z[0], z[1])) if simple else best
    return {
        "variant": chosen[2],
        "ridge": chosen[3],
        "model": chosen[4],
        "validation": chosen[5],
    }


def _walk_forward(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seasons = sorted({int(r.get("season") or 0) for r in rows if int(r.get("season") or 0) > 0})
    folds = []
    for idx in range(2, len(seasons)):
        validation_season = seasons[idx - 1]
        test_season = seasons[idx]
        train_seasons = seasons[: idx - 1]
        train = [r for r in rows if int(r.get("season") or 0) in train_seasons]
        validation = [r for r in rows if int(r.get("season") or 0) == validation_season]
        test = [r for r in rows if int(r.get("season") or 0) == test_season]
        selected = _select_variant(train, validation)
        if selected is None:
            folds.append({
                "train_seasons": train_seasons,
                "validation_season": validation_season,
                "test_season": test_season,
                "train_games": len(train),
                "validation_games": len(validation),
                "test_games": len(test),
                "passes": False,
                "reason": "NO_VALIDATION_PASSING_VARIANT",
            })
            continue
        final_model = _fit(train + validation, float(selected["ridge"]), selected["variant"] != "side_bias")
        test_eval = _gain(test, final_model)
        folds.append({
            "train_seasons": train_seasons,
            "validation_season": validation_season,
            "test_season": test_season,
            "train_games": len(train),
            "validation_games": len(validation),
            "test_games": len(test),
            "selected_variant": selected["variant"],
            "selected_ridge": selected["ridge"],
            "validation": selected["validation"],
            "test": test_eval,
            "passes": _passes(test_eval, MIN_WF_TEST_GAMES),
        })
    passed = [f for f in folds if f.get("passes")]
    stable = bool(len(folds) >= MIN_WF_FOLDS and len(passed) == len(folds) and folds[-1].get("passes"))
    return {
        "policy": "nested expanding-season walk-forward: choose hyperparameters on season t-1 using only seasons <t-1, refit through t-1, score untouched season t",
        "seasons": seasons,
        "folds": folds,
        "folds_total": len(folds),
        "folds_passed": len(passed),
        "minimum_passing_folds": MIN_WF_FOLDS,
        "stable": stable,
    }


def _exact_bootstrap(rows: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    if len(rows) < 10:
        return {"draws": 0, "nll_gain_positive_probability": None, "passes": False}
    per_game = []
    for row in rows:
        base = cand = 0.0
        dispersion = _num(row.get("dispersion"), DISPERSION)
        for side in ("home", "away"):
            mu = max(0.1, _num(row[f"{side}_mu"]))
            y = _num(row[f"{side}_score"])
            base += _nb_nll(mu, y, dispersion)
            cand += _nb_nll(apply(mu, side, model), y, dispersion)
        per_game.append(base - cand)
    rng = random.Random(13110)
    gains = []
    for _ in range(EXACT_BOOTSTRAP_DRAWS):
        sample = [rng.choice(per_game) for _ in per_game]
        gains.append(sum(sample) / len(sample))
    positive_probability = sum(g > 0 for g in gains) / len(gains)
    return {
        "draws": len(gains),
        "nll_gain_positive_probability": positive_probability,
        "passes": positive_probability >= 0.90,
    }


def build(
    historical_rows: list[dict[str, Any]] | None = None,
    exact_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    exact = _exact_rows() if exact_rows is None else list(exact_rows)
    exact_ids = {str(r.get("game_pk") or "") for r in exact}
    if historical_rows is None:
        rows, source_games = _historical_rows(exact_ids)
        dataset_sha = _dataset_content_sha256()
    else:
        source_games = len(historical_rows)
        rows = [r for r in historical_rows if str(r.get("game_pk") or "") not in exact_ids]
        dataset_sha = "TEST_INJECTED"
    rows = sorted(rows, key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or "")))
    walk_forward = _walk_forward(rows)
    historical_passes = bool(walk_forward.get("stable"))

    successful_folds = [f for f in walk_forward.get("folds") or [] if f.get("passes")]
    if not successful_folds:
        return {
            "schema": SCHEMA,
            "active": False,
            "historical_candidate_active": False,
            "reason": "NO_STABLE_WALK_FORWARD_CANDIDATE",
            "model_generation": contract.MODEL_GENERATION_FINGERPRINT,
            "source_games": source_games,
            "historical_games": len(rows),
            "dataset_content_sha256": dataset_sha,
            "walk_forward": walk_forward,
            "exact_final_games": len(exact),
            "exact_transfer_required_games": MIN_EXACT_FINAL,
        }

    latest = successful_folds[-1]
    variant = str(latest.get("selected_variant") or "side_bias")
    ridge = float(latest.get("selected_ridge") or 100.0)
    final_model = _fit(rows, ridge, variant != "side_bias")

    exact_ready = len(exact) >= MIN_EXACT_FINAL
    exact_eval = _gain(exact, final_model) if exact else {
        "games": 0,
        "baseline": {},
        "candidate": {},
        "mae_gain": None,
        "rmse_gain": None,
        "nll_gain": None,
    }
    exact_bootstrap = _exact_bootstrap(exact, final_model) if exact else {
        "draws": 0,
        "nll_gain_positive_probability": None,
        "passes": False,
    }
    exact_passes = bool(exact_ready and _passes(exact_eval, MIN_EXACT_FINAL) and exact_bootstrap.get("passes"))
    exact_status = "PASS_FINAL_ONLY" if exact_passes else "FAIL_FINAL_ONLY" if exact_ready else "COLLECTING_FINAL_ONLY"
    active = bool(historical_passes and exact_passes)

    return {
        "schema": SCHEMA,
        "active": active,
        "historical_candidate_active": historical_passes,
        "phase_scope": "FINAL",
        "source": "2021-2026 leakage-separated free reconstructed team history",
        "source_games": source_games,
        "historical_games": len(rows),
        "historical_seasons": walk_forward.get("seasons"),
        "dataset_content_sha256": dataset_sha,
        "excluded_exact_transfer_game_ids": sorted(exact_ids),
        "model_generation": contract.MODEL_GENERATION_FINGERPRINT,
        "selected_variant": variant,
        "model": final_model,
        "walk_forward": walk_forward,
        "exact_games": len(exact),
        "exact_final_games": len(exact),
        "exact_phase_counts": {"FINAL": len(exact)},
        "exact_transfer": exact_eval,
        "exact_transfer_bootstrap": exact_bootstrap,
        "exact_transfer_status": exact_status,
        "exact_transfer_required_games": MIN_EXACT_FINAL,
        "activation_rule": "all nested season walk-forward folds must pass, then >=60 current-generation genuine FINAL V13 transfer games excluded from historical fitting must improve RMSE and NB-NLL with MAE regression <=0.01 and >=90% bootstrap probability of positive NLL gain",
        "transfer_caveat": "Reconstructed history may propose a small run-mean correction, but it cannot alter V13 until independent current-generation FINAL transfer proves that the correction improves the pre-candidate V13 baseline.",
        "safety": {
            "historical_odds_used": False,
            "market_probability_used": False,
            "reconstructed_history_is_native_evidence": False,
            "exact_transfer_required_for_activation": True,
            "exact_transfer_generation_locked": True,
            "exact_transfer_games_excluded_from_historical_fit": True,
            "independent_pre_candidate_baseline_required": True,
            "runtime_adjustment_cap_runs": MAX_ADJ,
            "applies_only_when_native_residual_and_legacy_run_bootstrap_are_inactive": True,
        },
    }


def main() -> None:
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "schema": report.get("schema"),
        "active": report.get("active"),
        "historical_candidate_active": report.get("historical_candidate_active"),
        "historical_games": report.get("historical_games"),
        "historical_seasons": report.get("historical_seasons"),
        "walk_forward_folds": (report.get("walk_forward") or {}).get("folds_total"),
        "walk_forward_passed": (report.get("walk_forward") or {}).get("folds_passed"),
        "exact_final_games": report.get("exact_final_games"),
        "exact_transfer_status": report.get("exact_transfer_status"),
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
