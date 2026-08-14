from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import historical_bootstrap as legacy

SCHEMA = "v12-3-historical-bootstrap-v2"
VERSION = "historical-bootstrap-v2"
BASELINE_SCHEMA = "v12.3-structural-v1"
ALGORITHM_VERSION = "v12.3-bootstrap-validation-only-gates-v2"
DATA_FILE = Path(os.getenv("V123_HISTORICAL_BOOTSTRAP_DATA_FILE", "data/mlb_backtest_2026.jsonl"))
MODEL_FILE = Path(os.getenv("V123_HISTORICAL_BOOTSTRAP_MODEL_FILE", "data/v12_3_historical_bootstrap_model.json"))
MAX_PRIOR_RUN_ADJ = float(os.getenv("V123_MAX_HISTORICAL_RUN_ADJ", "0.50") or .50)
MIN_CORRECTION_RMSE_GAIN = float(os.getenv("V123_MIN_HISTORICAL_RMSE_GAIN", "0.005") or .005)
MIN_DISPERSION_NLL_GAIN = float(os.getenv("V123_MIN_HISTORICAL_DISPERSION_NLL_GAIN", "0.001") or .001)
MIN_ENV_NLL_GAIN = float(os.getenv("V123_MIN_HISTORICAL_ENV_NLL_GAIN", "0.0005") or .0005)


def _num(x, default=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else default
    except Exception:
        return default


def _sha(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def algorithm_fingerprint():
    return _sha({
        "algorithm": ALGORITHM_VERSION,
        "baseline_schema": BASELINE_SCHEMA,
        "max_prior_run_adj": MAX_PRIOR_RUN_ADJ,
        "min_correction_rmse_gain": MIN_CORRECTION_RMSE_GAIN,
        "min_dispersion_nll_gain": MIN_DISPERSION_NLL_GAIN,
        "min_environment_nll_gain": MIN_ENV_NLL_GAIN,
        "test_used_for_activation": False,
    })


def config_fingerprint():
    return _sha({
        "engine_version": getattr(config, "VERSION", None),
        "schema": getattr(config, "SCHEMA_VERSION", None),
        "feature_schema": getattr(config, "FEATURE_SCHEMA_VERSION", None),
        "run_dispersion": config.RUN_DISPERSION,
        "run_environment_sigma": config.RUN_ENV_SIGMA,
        "max_learned_run_adj": config.MAX_LEARNED_RUN_ADJ,
    })


def source_fingerprint(path=DATA_FILE):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _native_baseline(row):
    block = row.get("v12_3") or row.get("v123") or {}
    h = block.get("home_struct")
    a = block.get("away_struct")
    schema = block.get("baseline_schema") or row.get("baseline_schema")
    if schema != BASELINE_SCHEMA or h is None or a is None:
        return None, None
    h, a = _num(h, None), _num(a, None)
    if h is None or a is None or h <= 0 or a <= 0:
        return None, None
    return h, a


def load_source_rows(path=DATA_FILE):
    rows, seen = [], set()
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            gid = row.get("game_pk")
            if gid is None or row.get("game_date") is None or gid in seen:
                continue
            seen.add(gid)
            rows.append(row)
    rows.sort(key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or "")))
    return rows


def _native_rows(rows):
    out = []
    for row in rows:
        h, a = _native_baseline(row)
        if h is None or a is None or row.get("home_score") is None or row.get("away_score") is None:
            continue
        clone = dict(row)
        clone["v10"] = {"home_struct": h, "away_struct": a}
        out.append(clone)
    return out


def _distribution_components(train, validation, test, correction, correction_active):
    active_correction = correction if correction_active else None
    cand_d = legacy._estimate_dispersion(train, active_correction)
    d_eval = {}
    for name, rows in (("validation", validation), ("test", test)):
        base = legacy._run_nll(rows, config.RUN_DISPERSION, active_correction)
        cand = legacy._run_nll(rows, cand_d, active_correction)
        d_eval[name] = {"base_nll": base, "candidate_nll": cand,
                        "nll_gain": (base-cand) if base is not None and cand is not None else None}
    d_gain = _num((d_eval.get("validation") or {}).get("nll_gain"), -999.0)
    d_active = d_gain >= MIN_DISPERSION_NLL_GAIN
    dispersion = {"active": d_active, "value": cand_d if d_active else config.RUN_DISPERSION,
                  "candidate_value": cand_d, "baseline_value": config.RUN_DISPERSION,
                  "evaluation": d_eval, "activation_basis": "validation_only"}

    d_for_env = dispersion["value"] if d_active else config.RUN_DISPERSION
    cand_s = legacy._estimate_environment_sigma(train, active_correction)
    e_eval = {}
    for name, rows in (("validation", validation), ("test", test)):
        base = legacy._joint_nll(rows, d_for_env, config.RUN_ENV_SIGMA, active_correction)
        cand = legacy._joint_nll(rows, d_for_env, cand_s, active_correction)
        e_eval[name] = {"base_nll": base, "candidate_nll": cand,
                        "nll_gain": (base-cand) if base is not None and cand is not None else None}
    e_gain = _num((e_eval.get("validation") or {}).get("nll_gain"), -999.0)
    e_active = e_gain >= MIN_ENV_NLL_GAIN
    environment = {"active": e_active, "sigma": cand_s if e_active else config.RUN_ENV_SIGMA,
                   "candidate_sigma": cand_s, "baseline_sigma": config.RUN_ENV_SIGMA,
                   "evaluation": e_eval, "activation_basis": "validation_only"}
    return dispersion, environment


def build_model(rows, source_path=None, min_games=900, fingerprint=None):
    source_rows = list(rows)
    native = _native_rows(source_rows)
    meta_common = {
        "source": "V12.3 baseline-safe historical bootstrap",
        "source_path": str(source_path) if source_path else None,
        "source_fingerprint": fingerprint,
        "source_games": len(source_rows),
        "native_baseline_games": len(native),
        "baseline_schema": BASELINE_SCHEMA,
        "algorithm_fingerprint": algorithm_fingerprint(),
        "config_fingerprint": config_fingerprint(),
        "test_is_frozen": True,
        "test_used_for_activation": False,
        "historical_odds_used": False,
        "historical_clv_used": False,
        "betting_profitability_claim": False,
    }
    if len(native) < min_games:
        status = "INCOMPATIBLE_BASELINE" if len(source_rows) >= min_games and not native else "COLLECTING"
        return {
            "schema": SCHEMA, "version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
            "active": False, "eligible_for_final_prior": False, "status": status, "phase_scope": ["FINAL"],
            "run_correction": {"active": False},
            "dispersion": {"active": False, "value": config.RUN_DISPERSION},
            "environment": {"active": False, "sigma": config.RUN_ENV_SIGMA},
            "metadata": {**meta_common, "required_native_games": min_games},
            "evidence_boundary": (
                "The legacy 1,801-game V10 structural dataset remains diagnostic only. V12.3 refuses to transfer "
                "run/distribution priors unless rows explicitly carry the V12.3 structural baseline."
            ),
        }

    train, validation, test = legacy.chronological_split(native)
    correction = legacy.fit_run_correction(train)
    val_eval = legacy._correction_eval(validation, correction)
    test_eval = legacy._correction_eval(test, correction)
    walk = legacy._walk_forward_gate(train)
    correction_pass = (
        val_eval["team_rmse_gain"] >= MIN_CORRECTION_RMSE_GAIN
        and val_eval["total_rmse_gain"] >= -0.02
        and bool(walk.get("passes"))
    )
    correction.update({"active": correction_pass, "passes": correction_pass,
                       "max_abs_run_adjustment": MAX_PRIOR_RUN_ADJ,
                       "validation": val_eval, "test": test_eval, "walk_forward": walk,
                       "activation_basis": "validation_plus_walk_forward; frozen_test_report_only"})
    dispersion, environment = _distribution_components(train, validation, test, correction, correction_pass)
    active = bool(correction_pass or dispersion.get("active") or environment.get("active"))
    dates = [str(r.get("game_date") or "") for r in native]
    return {
        "schema": SCHEMA, "version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
        "active": active, "eligible_for_final_prior": active, "status": "PASS" if active else "FAIL",
        "phase_scope": ["FINAL"], "run_correction": correction, "dispersion": dispersion,
        "environment": environment,
        "metadata": {**meta_common, "games": len(native), "date_start": min(dates), "date_end": max(dates),
                     "split": {"train": len(train), "validation": len(validation), "test": len(test)}},
        "evidence_boundary": (
            "V12.3-native baseball bootstrap only. Activation uses validation plus expanding walk-forward; "
            "the frozen test is reporting-only and is never a deployment gate. No betting-profitability claim is made."
        ),
    }


def build_from_file(path=DATA_FILE, min_games=900):
    path = Path(path)
    return build_model(load_source_rows(path), source_path=path, min_games=min_games, fingerprint=source_fingerprint(path))


def write_model(model, path=MODEL_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return model


def load_model(path=MODEL_FILE):
    path = Path(path)
    if not path.exists():
        return {"schema": SCHEMA, "version": VERSION, "active": False, "eligible_for_final_prior": False, "status": "ABSENT"}
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema": SCHEMA, "version": VERSION, "active": False, "eligible_for_final_prior": False,
                "status": "INVALID", "error": type(exc).__name__}
    if model.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "version": VERSION, "active": False, "eligible_for_final_prior": False,
                "status": "INCOMPATIBLE", "error": "schema_mismatch"}
    return model


def ensure_artifact(data_path=DATA_FILE, model_path=MODEL_FILE):
    data_path, model_path = Path(data_path), Path(model_path)
    source_fp = source_fingerprint(data_path)
    current = load_model(model_path)
    meta = current.get("metadata") or {}
    valid = (
        current.get("schema") == SCHEMA
        and meta.get("source_fingerprint") == source_fp
        and meta.get("baseline_schema") == BASELINE_SCHEMA
        and meta.get("algorithm_fingerprint") == algorithm_fingerprint()
        and meta.get("config_fingerprint") == config_fingerprint()
    )
    if valid:
        return current
    return write_model(build_model(load_source_rows(data_path), source_path=data_path, fingerprint=source_fp), model_path)


def apply_final_run_prior(home_mu, away_mu, model=None, phase="FINAL"):
    model = load_model() if model is None else model
    if str(phase or "").upper() != "FINAL" or not model.get("eligible_for_final_prior"):
        return home_mu, away_mu, {"active": False, "source": "none", "home_delta": 0.0, "away_delta": 0.0}
    correction = model.get("run_correction") or {}
    if not correction.get("active"):
        return home_mu, away_mu, {"active": False, "source": "none", "home_delta": 0.0, "away_delta": 0.0}
    hd = legacy._side_delta(_num(home_mu), correction.get("home") or {})
    ad = legacy._side_delta(_num(away_mu), correction.get("away") or {})
    hd, ad = max(-MAX_PRIOR_RUN_ADJ, min(MAX_PRIOR_RUN_ADJ, hd)), max(-MAX_PRIOR_RUN_ADJ, min(MAX_PRIOR_RUN_ADJ, ad))
    return max(1.4, _num(home_mu)+hd), max(1.4, _num(away_mu)+ad), {
        "active": True, "source": "v12.3-native-historical-bootstrap", "home_delta": hd, "away_delta": ad,
        "schema": SCHEMA,
    }


def distribution_defaults(model=None):
    model = load_model() if model is None else model
    if not model.get("eligible_for_final_prior"):
        return config.RUN_DISPERSION, config.RUN_ENV_SIGMA
    d = model.get("dispersion") or {}
    e = model.get("environment") or {}
    dispersion = _num(d.get("value"), config.RUN_DISPERSION) if d.get("active") else config.RUN_DISPERSION
    sigma = _num(e.get("sigma"), config.RUN_ENV_SIGMA) if e.get("active") else config.RUN_ENV_SIGMA
    return dispersion, sigma


def main():
    parser = argparse.ArgumentParser(description="V12.3 baseline-safe historical bootstrap")
    parser.add_argument("--data", default=str(DATA_FILE))
    parser.add_argument("--output", default=str(MODEL_FILE))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    model = build_from_file(args.data)
    if not args.dry_run:
        write_model(model, args.output)
    print(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
