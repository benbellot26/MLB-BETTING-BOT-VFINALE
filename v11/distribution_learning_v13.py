from __future__ import annotations

import math
from typing import Any


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def estimate_negative_binomial_dispersion(rows: list[dict[str,Any]], default: float = 7.5) -> float:
    numer = denom = 0.0
    for row in rows:
        for mu_key,score_key in (("projected_home_runs","home_score"),("projected_away_runs","away_score")):
            if row.get(mu_key) is None or row.get(score_key) is None:
                continue
            mu = max(.1,_num(row.get(mu_key)))
            y = _num(row.get(score_key))
            numer += mu*mu
            denom += max(0.0,(y-mu)**2-mu)
    if denom <= 1e-9:
        return default
    return max(2.0,min(30.0,numer/denom))


def estimate_shared_environment_sigma(rows: list[dict[str,Any]], default: float = .08) -> float:
    numer = denom = 0.0
    for row in rows:
        hmu,amu = row.get("projected_home_runs"),row.get("projected_away_runs")
        if hmu is None or amu is None or row.get("home_score") is None or row.get("away_score") is None:
            continue
        hmu,amu = max(.1,_num(hmu)),max(.1,_num(amu))
        eh = _num(row.get("home_score"))-hmu
        ea = _num(row.get("away_score"))-amu
        numer += eh*ea
        denom += max(.1,hmu*amu)
    if denom <= 0:
        return default
    return max(0.0,min(.25,math.sqrt(max(0.0,numer/denom))))


def distribution_candidate(rows: list[dict[str,Any]], default_dispersion: float = 7.5,
                           default_environment_sigma: float = .08) -> dict[str,Any]:
    return {
        "dispersion":estimate_negative_binomial_dispersion(rows,default_dispersion),
        "environment_sigma":estimate_shared_environment_sigma(rows,default_environment_sigma),
        "activation":"candidate-only; requires V13 strict outer-holdout gate",
    }
