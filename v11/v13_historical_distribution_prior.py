from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean

from . import config

SOURCE = Path("data/mlb_backtest_2026.jsonl")
OUT = Path("data/v13_historical_distribution_prior.json")

DISP_GRID = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.5, 9.0, 12.0, 16.0, 24.0]
ENV_GRID = [0.0, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.22]
MIN_WARM = 5
MIN_VALIDATION_GAIN = 0.001
MIN_TEST_GAIN = 0.001


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _read():
    rows = []
    with SOURCE.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            v10 = r.get("v10") or {}
            h, a = v10.get("home_mu"), v10.get("away_mu")
            if h is None or a is None or r.get("home_score") is None or r.get("away_score") is None:
                continue
            if min(int(r.get("pregame_games_home") or 0), int(r.get("pregame_games_away") or 0)) < MIN_WARM:
                continue
            rows.append({
                "game_pk": r.get("game_pk"),
                "game_date": r.get("game_date"),
                "home_mu": max(.1, _num(h)),
                "away_mu": max(.1, _num(a)),
                "home_score": int(_num(r.get("home_score"))),
                "away_score": int(_num(r.get("away_score"))),
            })
    rows.sort(key=lambda x: (str(x.get("game_date") or ""), str(x.get("game_pk") or "")))
    return rows


def _nb_logpmf(mu, y, dispersion):
    r = max(.5, float(dispersion))
    mu = max(.01, float(mu))
    y = max(0, int(y))
    p = r / (r + mu)
    return math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p)


def _env_nodes(sigma):
    sigma = max(0.0, min(.30, float(sigma)))
    if sigma <= 1e-12:
        return [(1.0, 1.0)]
    d = math.sqrt(3.0)*sigma
    return [(max(.45, 1-d), 1/6), (1.0, 2/3), (1+d, 1/6)]


def _joint_nll(rows, dispersion, sigma):
    vals = []
    for r in rows:
        prob = 0.0
        for factor, weight in _env_nodes(sigma):
            prob += weight * math.exp(
                _nb_logpmf(r["home_mu"]*factor, r["home_score"], dispersion)
                + _nb_logpmf(r["away_mu"]*factor, r["away_score"], dispersion)
            )
        vals.append(-math.log(max(1e-15, prob)))
    return mean(vals) if vals else None


def _split(rows):
    n = len(rows)
    a = int(n * .60)
    b = int(n * .80)
    return rows[:a], rows[a:b], rows[b:]


def _fit(train):
    best = None
    for d in DISP_GRID:
        for s in ENV_GRID:
            nll = _joint_nll(train, d, s)
            item = (nll, d, s)
            if best is None or item < best:
                best = item
    return {"dispersion": best[1], "environment_sigma": best[2], "train_nll": best[0]}


def _eval(rows, candidate):
    base = _joint_nll(rows, config.RUN_DISPERSION, config.RUN_ENV_SIGMA)
    cand = _joint_nll(rows, candidate["dispersion"], candidate["environment_sigma"])
    return {"games": len(rows), "baseline_nll": base, "candidate_nll": cand, "nll_gain": base-cand}


def _walk_forward(rows):
    windows = []
    min_train = max(600, len(rows)//3)
    block = max(150, len(rows)//6)
    for end in range(min_train, len(rows)-block+1, block):
        fit = _fit(rows[:end])
        ev = _eval(rows[end:end+block], fit)
        windows.append({"train_games": end, "candidate": fit, "future": ev, "passes": ev["nll_gain"] > 0})
    rate = sum(1 for w in windows if w["passes"]) / len(windows) if windows else 0.0
    return {"windows": windows, "pass_rate": rate, "passes": len(windows) >= 3 and rate >= .67}


def build():
    rows = _read()
    train, validation, test = _split(rows)
    candidate = _fit(train)
    val = _eval(validation, candidate)
    tst = _eval(test, candidate)
    wf = _walk_forward(rows[:int(len(rows)*.80)])
    eligible = (
        len(rows) >= 1200
        and val["nll_gain"] >= MIN_VALIDATION_GAIN
        and tst["nll_gain"] >= MIN_TEST_GAIN
        and wf["passes"]
    )
    return {
        "schema": "v13-historical-distribution-prior-v1",
        "source": str(SOURCE),
        "source_contract": {
            "point_in_time_baseball_features": True,
            "historical_odds_used": False,
            "market_probability_used": False,
            "current_game_stats_used_in_features": False,
            "phase": "FINAL_INFORMATION_RECONSTRUCTION",
        },
        "warm_games": len(rows),
        "split": {"train": len(train), "validation": len(validation), "test": len(test)},
        "baseline": {"dispersion": config.RUN_DISPERSION, "environment_sigma": config.RUN_ENV_SIGMA},
        "candidate": candidate,
        "validation": val,
        "test": tst,
        "walk_forward": wf,
        "eligible_as_distribution_prior": bool(eligible),
        "eligible_for_probability_calibration": False,
        "eligible_for_market_edge_training": False,
        "activation_policy": "distribution parameters only; live V13 point-in-time evidence may supersede this prior",
    }


def main():
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
