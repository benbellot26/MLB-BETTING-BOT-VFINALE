from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = "v12-historical-bootstrap-v1"
SOURCE = "mlb-backtest-2026-final-phase"
DATA_FILE = Path(os.getenv("V12_HISTORICAL_BOOTSTRAP_DATA_FILE", "data/mlb_backtest_2026.jsonl"))
MODEL_FILE = Path(os.getenv("V12_HISTORICAL_BOOTSTRAP_MODEL_FILE", "data/v12_historical_bootstrap_model.json"))
TRAIN_FRACTION = 2.0 / 3.0
VALIDATION_FRACTION = 1.0 / 6.0
MAX_PRIOR_RUN_ADJ = float(os.getenv("V12_MAX_HISTORICAL_RUN_ADJ", "0.50") or .50)
MIN_CORRECTION_RMSE_GAIN = float(os.getenv("V12_MIN_HISTORICAL_RMSE_GAIN", "0.005") or .005)
MIN_DISPERSION_NLL_GAIN = float(os.getenv("V12_MIN_HISTORICAL_DISPERSION_NLL_GAIN", "0.001") or .001)
MIN_ENV_NLL_GAIN = float(os.getenv("V12_MIN_HISTORICAL_ENV_NLL_GAIN", "0.0005") or .0005)
MIN_WALK_FORWARD_WINDOWS = 3
MIN_WALK_FORWARD_PASS_RATE = .67


def _num(x, default=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else default
    except Exception:
        return default


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _source_fingerprint(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _baseline(row):
    v10 = row.get("v10") or {}
    h = v10.get("home_struct")
    a = v10.get("away_struct")
    if h is None or a is None:
        return None, None
    return _num(h), _num(a)


def _valid_row(row):
    h, a = _baseline(row)
    return bool(
        row.get("game_pk") is not None
        and row.get("game_date")
        and row.get("home_score") is not None
        and row.get("away_score") is not None
        and h is not None
        and a is not None
        and h > 0
        and a > 0
    )


def load_rows(path=DATA_FILE):
    path = Path(path)
    rows = []
    seen = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if not _valid_row(row):
                continue
            gid = str(row.get("game_pk"))
            if gid in seen:
                continue
            seen.add(gid)
            rows.append(row)
    rows.sort(key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or "")))
    return rows


def chronological_split(rows, train_fraction=TRAIN_FRACTION, validation_fraction=VALIDATION_FRACTION):
    rows = list(rows)
    n = len(rows)
    if n < 3:
        return rows, [], []
    n_train = max(1, int(n * train_fraction))
    n_validation = max(1, int(n * validation_fraction))
    if n_train + n_validation >= n:
        n_validation = max(1, n - n_train - 1)
    train = rows[:n_train]
    validation = rows[n_train:n_train + n_validation]
    test = rows[n_train + n_validation:]
    return train, validation, test


def _fit_side(rows, side):
    xs, ys = [], []
    for row in rows:
        h, a = _baseline(row)
        mu = h if side == "home" else a
        score = _num(row.get("home_score" if side == "home" else "away_score"))
        xs.append(mu)
        ys.append(score - mu)
    if not xs:
        return {"mean_mu": 0.0, "intercept": 0.0, "slope": 0.0, "n": 0}
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    ridge = max(1.0, .02 * var)
    slope = cov / (var + ridge)
    intercept = my
    return {"mean_mu": mx, "intercept": intercept, "slope": slope, "n": len(xs)}


def fit_run_correction(rows):
    return {"home": _fit_side(rows, "home"), "away": _fit_side(rows, "away")}


def _side_delta(mu, side_model):
    raw = _num(side_model.get("intercept")) + _num(side_model.get("slope")) * (mu - _num(side_model.get("mean_mu"), mu))
    return _clip(raw, -MAX_PRIOR_RUN_ADJ, MAX_PRIOR_RUN_ADJ)


def corrected_runs(row, correction=None):
    h, a = _baseline(row)
    if h is None or a is None:
        return h, a
    if not correction:
        return h, a
    hd = _side_delta(h, correction.get("home") or {})
    ad = _side_delta(a, correction.get("away") or {})
    return max(1.4, h + hd), max(1.4, a + ad)


def apply_final_run_prior(home_mu, away_mu, model=None, phase="FINAL"):
    model = load_model() if model is None else model
    correction = model.get("run_correction") or {}
    if str(phase or "").upper() != "FINAL" or not model.get("active") or not correction.get("active"):
        return home_mu, away_mu, {"active": False, "source": "none", "home_delta": 0.0, "away_delta": 0.0}
    hd = _side_delta(_num(home_mu), correction.get("home") or {})
    ad = _side_delta(_num(away_mu), correction.get("away") or {})
    return max(1.4, _num(home_mu) + hd), max(1.4, _num(away_mu) + ad), {
        "active": True,
        "source": "historical-bootstrap",
        "home_delta": hd,
        "away_delta": ad,
        "schema": model.get("schema"),
    }


def _run_metrics(rows, correction=None):
    team_sq = []
    team_abs = []
    total_sq = []
    total_abs = []
    for row in rows:
        h, a = corrected_runs(row, correction)
        hs, aws = _num(row.get("home_score")), _num(row.get("away_score"))
        for mu, y in ((h, hs), (a, aws)):
            team_sq.append((y - mu) ** 2)
            team_abs.append(abs(y - mu))
        total_sq.append(((hs + aws) - (h + a)) ** 2)
        total_abs.append(abs((hs + aws) - (h + a)))
    n = max(1, len(team_sq))
    ng = max(1, len(total_sq))
    return {
        "games": len(rows),
        "team_rmse": math.sqrt(sum(team_sq) / n),
        "team_mae": sum(team_abs) / n,
        "total_rmse": math.sqrt(sum(total_sq) / ng),
        "total_mae": sum(total_abs) / ng,
    }


def _correction_eval(rows, correction):
    base = _run_metrics(rows)
    candidate = _run_metrics(rows, correction)
    return {
        "base": base,
        "candidate": candidate,
        "team_rmse_gain": base["team_rmse"] - candidate["team_rmse"],
        "total_rmse_gain": base["total_rmse"] - candidate["total_rmse"],
    }


def _walk_forward_gate(train_rows):
    rows = list(train_rows)
    if len(rows) < 360:
        return {"status": "COLLECTING", "passes": False, "pass_rate": 0.0, "windows": []}
    block = max(60, min(150, len(rows) // 6))
    min_train = max(240, len(rows) // 3)
    endpoints = list(range(min_train, len(rows) - block + 1, block))[-4:]
    windows = []
    for end in endpoints:
        fit = fit_run_correction(rows[:end])
        ev = _correction_eval(rows[end:end + block], fit)
        passed = ev["team_rmse_gain"] > 0 and ev["total_rmse_gain"] >= -.03
        windows.append({"train_games": end, "future_games": len(rows[end:end + block]), "passes": passed, **ev})
    rate = sum(bool(w.get("passes")) for w in windows) / len(windows) if windows else 0.0
    passes = len(windows) >= MIN_WALK_FORWARD_WINDOWS and rate >= MIN_WALK_FORWARD_PASS_RATE
    return {"status": "PASS" if passes else "FAIL", "passes": passes, "pass_rate": rate, "windows": windows}


def _nb_logpmf(mu, y, dispersion):
    r = max(.5, _num(dispersion, config.RUN_DISPERSION))
    mu = max(.01, _num(mu))
    y = max(0, int(_num(y)))
    p = r / (r + mu)
    return math.lgamma(y + r) - math.lgamma(r) - math.lgamma(y + 1) + r * math.log(p) + y * math.log1p(-p)


def _estimate_dispersion(rows, correction=None):
    numer = 0.0
    denom = 0.0
    for row in rows:
        h, a = corrected_runs(row, correction)
        for mu, score in ((h, row.get("home_score")), (a, row.get("away_score"))):
            y = _num(score)
            numer += mu * mu
            denom += max(0.0, (y - mu) ** 2 - mu)
    if denom <= 1e-9:
        return config.RUN_DISPERSION
    return _clip(numer / denom, 2.0, 30.0)


def _run_nll(rows, dispersion, correction=None):
    values = []
    for row in rows:
        h, a = corrected_runs(row, correction)
        values.append(-_nb_logpmf(h, row.get("home_score"), dispersion))
        values.append(-_nb_logpmf(a, row.get("away_score"), dispersion))
    return sum(values) / len(values) if values else None


def _env_nodes(sigma):
    sigma = _clip(_num(sigma, config.RUN_ENV_SIGMA), 0.0, .30)
    if sigma <= 1e-12:
        return [(1.0, 1.0)]
    d = math.sqrt(3.0) * sigma
    return [(max(.45, 1 - d), 1 / 6), (1.0, 2 / 3), (1 + d, 1 / 6)]


def _estimate_environment_sigma(rows, correction=None):
    numer = 0.0
    denom = 0.0
    for row in rows:
        h, a = corrected_runs(row, correction)
        eh = _num(row.get("home_score")) - h
        ea = _num(row.get("away_score")) - a
        numer += eh * ea
        denom += max(.1, h * a)
    return _clip(math.sqrt(max(0.0, numer / max(1e-9, denom))), 0.0, .25)


def _joint_nll(rows, dispersion, sigma, correction=None):
    vals = []
    for row in rows:
        h, a = corrected_runs(row, correction)
        hs, aws = int(_num(row.get("home_score"))), int(_num(row.get("away_score")))
        prob = 0.0
        for factor, weight in _env_nodes(sigma):
            prob += weight * math.exp(_nb_logpmf(h * factor, hs, dispersion) + _nb_logpmf(a * factor, aws, dispersion))
        vals.append(-math.log(max(1e-15, prob)))
    return sum(vals) / len(vals) if vals else None


def _distribution_components(train, validation, test, correction, correction_active):
    active_correction = correction if correction_active else None
    candidate_dispersion = _estimate_dispersion(train, active_correction)
    dispersion_eval = {}
    dispersion_pass = True
    for name, rows in (("validation", validation), ("test", test)):
        base = _run_nll(rows, config.RUN_DISPERSION, active_correction)
        cand = _run_nll(rows, candidate_dispersion, active_correction)
        gain = (base - cand) if base is not None and cand is not None else -999.0
        dispersion_eval[name] = {"base_nll": base, "candidate_nll": cand, "nll_gain": gain}
        dispersion_pass = dispersion_pass and gain >= MIN_DISPERSION_NLL_GAIN
    dispersion = {
        "active": dispersion_pass,
        "value": candidate_dispersion if dispersion_pass else config.RUN_DISPERSION,
        "candidate_value": candidate_dispersion,
        "baseline_value": config.RUN_DISPERSION,
        "evaluation": dispersion_eval,
    }
    d_for_env = dispersion["value"] if dispersion["active"] else config.RUN_DISPERSION
    candidate_sigma = _estimate_environment_sigma(train, active_correction)
    env_eval = {}
    env_pass = True
    for name, rows in (("validation", validation), ("test", test)):
        base = _joint_nll(rows, d_for_env, config.RUN_ENV_SIGMA, active_correction)
        cand = _joint_nll(rows, d_for_env, candidate_sigma, active_correction)
        gain = (base - cand) if base is not None and cand is not None else -999.0
        env_eval[name] = {"base_nll": base, "candidate_nll": cand, "nll_gain": gain}
        env_pass = env_pass and gain >= MIN_ENV_NLL_GAIN
    environment = {
        "active": env_pass,
        "sigma": candidate_sigma if env_pass else config.RUN_ENV_SIGMA,
        "candidate_sigma": candidate_sigma,
        "baseline_sigma": config.RUN_ENV_SIGMA,
        "evaluation": env_eval,
    }
    return dispersion, environment


def build_model(rows, source_path=None, min_games=900, fingerprint=None):
    rows = list(rows)
    train, validation, test = chronological_split(rows)
    if len(rows) < min_games or not validation or not test:
        return {
            "schema": SCHEMA,
            "version": "historical-bootstrap-v1",
            "active": False,
            "eligible_for_final_prior": False,
            "status": "COLLECTING",
            "metadata": {"games": len(rows), "required_games": min_games},
        }

    correction = fit_run_correction(train)
    validation_eval = _correction_eval(validation, correction)
    test_eval = _correction_eval(test, correction)
    walk_forward = _walk_forward_gate(train)
    correction_pass = (
        validation_eval["team_rmse_gain"] >= MIN_CORRECTION_RMSE_GAIN
        and test_eval["team_rmse_gain"] >= MIN_CORRECTION_RMSE_GAIN
        and validation_eval["total_rmse_gain"] >= -.02
        and test_eval["total_rmse_gain"] >= -.02
        and walk_forward.get("passes", False)
    )
    correction.update({
        "active": correction_pass,
        "max_abs_run_adjustment": MAX_PRIOR_RUN_ADJ,
        "validation": validation_eval,
        "test": test_eval,
        "walk_forward": walk_forward,
        "passes": correction_pass,
    })

    dispersion, environment = _distribution_components(train, validation, test, correction, correction_pass)
    active = bool(correction_pass or dispersion.get("active") or environment.get("active"))
    dates = [str(r.get("game_date") or "") for r in rows]
    return {
        "schema": SCHEMA,
        "version": "historical-bootstrap-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active": active,
        "eligible_for_final_prior": active,
        "status": "PASS" if active else "FAIL",
        "phase_scope": ["FINAL"],
        "run_correction": correction,
        "dispersion": dispersion,
        "environment": environment,
        "metadata": {
            "source": SOURCE,
            "source_path": str(source_path) if source_path else None,
            "source_fingerprint": fingerprint,
            "games": len(rows),
            "date_start": min(dates) if dates else None,
            "date_end": max(dates) if dates else None,
            "split": {"train": len(train), "validation": len(validation), "test": len(test)},
            "test_is_frozen": True,
            "lineups": "actual FINAL lineup identities with prior-only player stats",
            "historical_odds_used": False,
            "historical_weather_used": False,
            "historical_statcast_used": False,
            "historical_clv_used": False,
            "betting_profitability_claim": False,
        },
        "evidence_boundary": (
            "Historical baseball bootstrap only. It may seed FINAL-phase run/distribution priors when its component gates pass; "
            "it is not evidence of betting profitability, market edge or CLV."
        ),
    }


def build_from_file(path=DATA_FILE, min_games=900):
    path = Path(path)
    return build_model(load_rows(path), source_path=path, min_games=min_games, fingerprint=_source_fingerprint(path))


def write_model(model, path=MODEL_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return model


def load_model(path=MODEL_FILE):
    path = Path(path)
    if not path.exists():
        return {"schema": SCHEMA, "version": "historical-bootstrap-absent", "active": False, "status": "ABSENT"}
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema": SCHEMA, "version": "historical-bootstrap-invalid", "active": False, "status": "INVALID", "error": type(exc).__name__}
    if model.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "version": model.get("version", "historical-bootstrap-incompatible"), "active": False, "status": "INCOMPATIBLE"}
    return model


def ensure_artifact(data_path=DATA_FILE, model_path=MODEL_FILE):
    data_path, model_path = Path(data_path), Path(model_path)
    fingerprint = _source_fingerprint(data_path)
    current = load_model(model_path)
    if current.get("metadata", {}).get("source_fingerprint") == fingerprint and current.get("schema") == SCHEMA:
        return current
    return write_model(build_model(load_rows(data_path), source_path=data_path, fingerprint=fingerprint), model_path)


def distribution_defaults(model=None):
    model = load_model() if model is None else model
    dispersion = model.get("dispersion") or {}
    environment = model.get("environment") or {}
    d = _num(dispersion.get("value"), config.RUN_DISPERSION) if model.get("active") and dispersion.get("active") else config.RUN_DISPERSION
    s = _num(environment.get("sigma"), config.RUN_ENV_SIGMA) if model.get("active") and environment.get("active") else config.RUN_ENV_SIGMA
    return d, s


def main():
    parser = argparse.ArgumentParser(description="Historical FINAL-phase bootstrap from the leakage-safe 2026 backtest")
    parser.add_argument("--data", default=str(DATA_FILE))
    parser.add_argument("--output", default=str(MODEL_FILE))
    parser.add_argument("--dry-run", action="store_true", help="build and validate without writing the artifact")
    args = parser.parse_args()
    model = build_from_file(args.data)
    if not args.dry_run:
        write_model(model, args.output)
    print(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
