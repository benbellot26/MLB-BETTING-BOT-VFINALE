from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract
from . import v13_run_mean_prior as historical_source

MODEL_FILE = Path("data/v13_distribution_prior.json")
EXACT_FILE = Path("data/v13_historical_backfill.jsonl")
SCHEMA = "v13-distribution-prior-v2"
BASELINE_DISPERSION = 7.5
ENVIRONMENT_SIGMA = 0.08
MIN_HISTORICAL_GAMES = 10_000
MIN_WALK_FORWARD_FOLDS = 4
MIN_WALK_FORWARD_NLL_GAIN = 0.002
MIN_EXACT_FINAL = 60
EXACT_BOOTSTRAP_DRAWS = 1200
DISPERSION_GRID = tuple(x / 20.0 for x in range(30, 201))  # 1.50 .. 10.00 by 0.05


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _nb_nll(mu: float, y: int, dispersion: float) -> float:
    r = max(0.5, _num(dispersion, BASELINE_DISPERSION))
    mu = max(0.01, _num(mu, 0.01))
    y = max(0, int(y))
    p = r / (r + mu)
    return -(math.lgamma(y + r) - math.lgamma(r) - math.lgamma(y + 1) + r * math.log(p) + y * math.log1p(-p))


def _season(row: dict[str, Any]) -> int:
    try:
        return int(row.get("season") or str(row.get("game_date") or "")[:4])
    except Exception:
        return 0


def _mean_nll(rows: list[dict[str, Any]], dispersion: float, *, use_persisted_baseline: bool = False) -> float | None:
    losses: list[float] = []
    for row in rows:
        for side in ("home", "away"):
            mu_key = f"validation_baseline_{side}_runs" if use_persisted_baseline else f"{side}_mu"
            mu = _num(row.get(mu_key), 0.0)
            score = row.get(f"{side}_score")
            if mu <= 0 or score is None:
                continue
            losses.append(_nb_nll(mu, int(score), dispersion))
    return sum(losses) / len(losses) if losses else None


def _fit_dispersion(rows: list[dict[str, Any]]) -> tuple[float, float | None]:
    scored = []
    for dispersion in DISPERSION_GRID:
        nll = _mean_nll(rows, dispersion)
        if nll is not None:
            scored.append((nll, dispersion))
    if not scored:
        return BASELINE_DISPERSION, None
    nll, dispersion = min(scored)
    return dispersion, nll


def _historical_rows(exclude_game_ids: set[str] | None = None) -> tuple[list[dict[str, Any]], int, str]:
    rows, source_games = historical_source._historical_rows(exclude_game_ids or set())
    return rows, source_games, historical_source._dataset_content_sha256()


def _walk_forward(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seasons = sorted({s for s in (_season(r) for r in rows) if s > 0})
    folds: list[dict[str, Any]] = []
    for idx in range(1, len(seasons)):
        test_season = seasons[idx]
        train_seasons = seasons[:idx]
        train = [r for r in rows if _season(r) in train_seasons]
        test = [r for r in rows if _season(r) == test_season]
        dispersion, train_nll = _fit_dispersion(train)
        baseline_nll = _mean_nll(test, BASELINE_DISPERSION)
        candidate_nll = _mean_nll(test, dispersion)
        gain = baseline_nll - candidate_nll if baseline_nll is not None and candidate_nll is not None else None
        passes = bool(
            len(test) >= 500
            and gain is not None
            and gain > MIN_WALK_FORWARD_NLL_GAIN
            and 1.5 <= dispersion <= 10.0
        )
        folds.append({
            "train_seasons": train_seasons,
            "test_season": test_season,
            "train_games": len(train),
            "test_games": len(test),
            "fitted_dispersion": dispersion,
            "train_nb_nll": train_nll,
            "baseline_dispersion": BASELINE_DISPERSION,
            "baseline_nb_nll": baseline_nll,
            "candidate_nb_nll": candidate_nll,
            "nll_gain": gain,
            "passes": passes,
        })
    passed = [f for f in folds if f.get("passes")]
    stable = bool(
        len(folds) >= MIN_WALK_FORWARD_FOLDS
        and len(passed) == len(folds)
        and folds[-1].get("passes")
    )
    return {
        "policy": "expanding-season walk-forward: fit dispersion only on seasons strictly earlier than each untouched test season",
        "seasons": seasons,
        "folds": folds,
        "folds_total": len(folds),
        "folds_passed": len(passed),
        "minimum_passing_folds": MIN_WALK_FORWARD_FOLDS,
        "minimum_nll_gain_per_fold": MIN_WALK_FORWARD_NLL_GAIN,
        "stable": stable,
    }


def _exact_rows(path: Path = EXACT_FILE) -> list[dict[str, Any]]:
    """Current-generation FINAL rows whose distribution baseline was frozen before this candidate."""
    if not path.exists():
        return []
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
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
        if row.get("validation_baseline_model_generation") != contract.MODEL_GENERATION_FINGERPRINT:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        if row.get("validation_baseline_home_runs") is None or row.get("validation_baseline_away_runs") is None:
            continue
        if row.get("validation_baseline_dispersion") is None:
            continue
        key = str(row.get("game_pk") or "")
        rank = str(row.get("analyzed_at") or "")
        if key and (key not in best or rank > best[key][0]):
            best[key] = (rank, row)
    return [x[1] for x in sorted(best.values(), key=lambda x: str(x[1].get("game_date") or ""))]


def _transfer_eval(rows: list[dict[str, Any]], candidate_dispersion: float) -> dict[str, Any]:
    base_losses: list[float] = []
    candidate_losses: list[float] = []
    per_game_gain: list[float] = []
    for row in rows:
        baseline_dispersion = _num(row.get("validation_baseline_dispersion"), 0.0)
        if baseline_dispersion <= 0:
            continue
        game_base = game_candidate = 0.0
        used = 0
        for side in ("home", "away"):
            mu = _num(row.get(f"validation_baseline_{side}_runs"), 0.0)
            score = row.get(f"{side}_score")
            if mu <= 0 or score is None:
                continue
            b = _nb_nll(mu, int(score), baseline_dispersion)
            c = _nb_nll(mu, int(score), candidate_dispersion)
            base_losses.append(b)
            candidate_losses.append(c)
            game_base += b
            game_candidate += c
            used += 1
        if used:
            per_game_gain.append((game_base - game_candidate) / used)
    n = len(base_losses)
    baseline = sum(base_losses) / n if n else None
    candidate = sum(candidate_losses) / n if n else None
    return {
        "games": len(per_game_gain),
        "team_observations": n,
        "baseline_nb_nll": baseline,
        "candidate_nb_nll": candidate,
        "nll_gain": baseline - candidate if baseline is not None and candidate is not None else None,
        "baseline_source": "persisted pre-distribution-candidate dispersion",
        "per_game_nll_gains": per_game_gain,
    }


def _bootstrap_transfer(per_game_gains: list[float]) -> dict[str, Any]:
    if len(per_game_gains) < 10:
        return {"draws": 0, "nll_gain_positive_probability": None, "passes": False}
    rng = random.Random(13111)
    gains = []
    for _ in range(EXACT_BOOTSTRAP_DRAWS):
        sample = [rng.choice(per_game_gains) for _ in per_game_gains]
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
        rows, source_games, dataset_sha = _historical_rows(exact_ids)
    else:
        source_games = len(historical_rows)
        rows = [r for r in historical_rows if str(r.get("game_pk") or "") not in exact_ids]
        dataset_sha = "TEST_INJECTED"
    rows = sorted(rows, key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or "")))

    walk_forward = _walk_forward(rows)
    historical_ok = bool(
        len(rows) >= MIN_HISTORICAL_GAMES
        and walk_forward.get("stable")
    )
    dispersion, full_history_nll = _fit_dispersion(rows)

    transfer = _transfer_eval(exact, dispersion)
    per_game_gains = list(transfer.pop("per_game_nll_gains", []))
    bootstrap = _bootstrap_transfer(per_game_gains)
    ready = len(exact) >= MIN_EXACT_FINAL
    transfer_passes = bool(
        ready
        and transfer.get("nll_gain") is not None
        and float(transfer["nll_gain"]) > 0
        and bootstrap.get("passes")
    )
    status = "PASS_FINAL_ONLY" if transfer_passes else "FAIL_FINAL_ONLY" if ready else "COLLECTING_FINAL_ONLY"
    active = bool(historical_ok and transfer_passes)

    folds = walk_forward.get("folds") or []
    last = folds[-1] if folds else {}
    previous = folds[-2] if len(folds) >= 2 else {}
    return {
        "schema": SCHEMA,
        "active": active,
        "historical_candidate_active": historical_ok,
        "phase_scope": "FINAL",
        "variant": "dispersion_only_2021_2026_walk_forward",
        "dispersion": dispersion,
        "environment_sigma": ENVIRONMENT_SIGMA,
        "baseline_dispersion": BASELINE_DISPERSION,
        "market_data_used": False,
        "historical_odds_used": False,
        "calibration_effect": "none",
        "source": "2021-2026 leakage-separated free reconstructed team history",
        "source_games": source_games,
        "historical_games": len(rows),
        "warm_games": len(rows),
        "historical_seasons": walk_forward.get("seasons"),
        "dataset_content_sha256": dataset_sha,
        "excluded_exact_transfer_game_ids": sorted(exact_ids),
        "walk_forward": walk_forward,
        "full_history_nb_nll": full_history_nll,
        # Compatibility diagnostics retained for older reports; activation uses the full walk-forward object.
        "validation_games": int(previous.get("test_games") or 0),
        "validation_nll_gain": previous.get("nll_gain"),
        "test_games": int(last.get("test_games") or 0),
        "test_nll_gain": last.get("nll_gain"),
        "exact_replay_games": len(exact),
        "exact_replay_nll_gain": transfer.get("nll_gain"),
        "model_generation": contract.MODEL_GENERATION_FINGERPRINT,
        "exact_final_games": len(exact),
        "exact_transfer_required_games": MIN_EXACT_FINAL,
        "exact_transfer_status": status,
        "current_generation_transfer": transfer,
        "exact_transfer_bootstrap": bootstrap,
        "activation_rule": "every expanding-season 2022-2026 walk-forward fold must improve untouched-season NB NLL by >0.002; then >=60 current-generation genuine FINAL V13 games excluded from historical fitting must show positive NLL gain with >=90% bootstrap probability",
        "selection_rule": "fit the single NB dispersion on strictly prior seasons; no market feature or target-season outcome is available during fitting",
        "transfer_caveat": "Reconstructed history establishes a distribution candidate only; production activation still requires independent current-generation FINAL transfer.",
        "evidence_boundary": "Applies only to score-distribution dispersion in FINAL phase. Historical evidence cannot masquerade as native V13 evidence.",
        "generation_gate": True,
        "independent_pre_candidate_baseline_required": True,
        "safety": {
            "historical_odds_used": False,
            "market_probability_used": False,
            "reconstructed_history_is_native_evidence": False,
            "exact_transfer_required_for_activation": True,
            "exact_transfer_generation_locked": True,
            "exact_transfer_games_excluded_from_historical_fit": True,
            "environment_sigma_learned_from_reconstructed_history": False,
        },
    }


def rebuild_transfer(path: Path = MODEL_FILE, exact_path: Path = EXACT_FILE) -> dict[str, Any]:
    # exact_path is retained for compatibility with existing callers/tests.
    exact = _exact_rows(exact_path)
    data = build(exact_rows=exact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return data


def load(path: Path = MODEL_FILE) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema": SCHEMA, "active": False, "status": "ABSENT_OR_INVALID", "error": type(exc).__name__}
    if data.get("schema") != SCHEMA:
        data["active"] = False
        data["status"] = "INCOMPATIBLE_HISTORICAL_TRANSFER_SCHEMA"
        return data
    historical_ok = bool(data.get("historical_candidate_active") and (data.get("walk_forward") or {}).get("stable"))
    generation_ok = data.get("model_generation") == contract.MODEL_GENERATION_FINGERPRINT
    required = max(MIN_EXACT_FINAL, int(data.get("exact_transfer_required_games") or MIN_EXACT_FINAL))
    transfer_ok = bool(
        int(data.get("exact_final_games") or 0) >= required
        and data.get("exact_transfer_status") == "PASS_FINAL_ONLY"
        and (data.get("exact_transfer_bootstrap") or {}).get("passes") is True
        and (data.get("safety") or {}).get("exact_transfer_games_excluded_from_historical_fit") is True
    )
    if not historical_ok:
        data["active"] = False
        data["status"] = "HISTORICAL_EVIDENCE_GATE_FAIL"
        return data
    if not generation_ok:
        data["active"] = False
        data["status"] = "CURRENT_GENERATION_TRANSFER_REQUIRED"
        return data
    if not transfer_ok:
        data["active"] = False
        data["status"] = "CURRENT_GENERATION_TRANSFER_COLLECTING"
        return data
    if data.get("active") is not True:
        data["status"] = "CURRENT_GENERATION_TRANSFER_NOT_ACTIVE"
        return data
    data["status"] = "ACTIVE_VALIDATED_CURRENT_GENERATION_FINAL_ONLY"
    return data


def apply(dispersion: float, env_sigma: float, phase: str, path: Path = MODEL_FILE) -> tuple[float, float, dict[str, Any]]:
    model = load(path)
    if str(phase or "").upper() != "FINAL" or not model.get("active"):
        return dispersion, env_sigma, {
            "active": False,
            "source": "none",
            "status": model.get("status"),
            "historical_candidate_active": bool(model.get("historical_candidate_active")),
            "historical_games": model.get("historical_games"),
            "walk_forward_folds": (model.get("walk_forward") or {}).get("folds_total"),
            "walk_forward_passed": (model.get("walk_forward") or {}).get("folds_passed"),
            "model_generation": model.get("model_generation"),
            "expected_model_generation": contract.MODEL_GENERATION_FINGERPRINT,
            "exact_transfer_games": model.get("exact_final_games"),
            "exact_transfer_required_games": model.get("exact_transfer_required_games", MIN_EXACT_FINAL),
        }
    return float(model["dispersion"]), float(model["environment_sigma"]), {
        "active": True,
        "source": "v13-validated-2021-2026-historical-distribution",
        "variant": model.get("variant"),
        "historical_games": model.get("historical_games"),
        "historical_seasons": model.get("historical_seasons"),
        "dispersion": model.get("dispersion"),
        "walk_forward": model.get("walk_forward"),
        "current_generation_nll_gain": (model.get("current_generation_transfer") or {}).get("nll_gain"),
        "model_generation": model.get("model_generation"),
        "exact_transfer_games": model.get("exact_final_games"),
        "exact_transfer_status": model.get("exact_transfer_status"),
        "exact_transfer_bootstrap": model.get("exact_transfer_bootstrap"),
    }


def main() -> None:
    report = rebuild_transfer()
    print(json.dumps({
        "schema": report.get("schema"),
        "active": report.get("active"),
        "historical_candidate_active": report.get("historical_candidate_active"),
        "historical_games": report.get("historical_games"),
        "historical_seasons": report.get("historical_seasons"),
        "dispersion": report.get("dispersion"),
        "walk_forward_folds": (report.get("walk_forward") or {}).get("folds_total"),
        "walk_forward_passed": (report.get("walk_forward") or {}).get("folds_passed"),
        "exact_final_games": report.get("exact_final_games"),
        "exact_transfer_status": report.get("exact_transfer_status"),
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
