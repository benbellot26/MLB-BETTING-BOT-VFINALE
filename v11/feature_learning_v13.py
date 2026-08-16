from __future__ import annotations

import math
from typing import Any

FEATURES = (
    "home_ops","away_ops","home_lineup_ops","away_lineup_ops",
    "home_team_era","away_team_era","home_starter_era","away_starter_era",
    "home_starter_whip","away_starter_whip","home_starter_k9","away_starter_k9",
    "home_starter_bb9","away_starter_bb9","home_starter_hr9","away_starter_hr9",
    "park_factor","temperature_c","wind_kph","humidity_pct",
    "home_bullpen_recent_era","away_bullpen_recent_era",
    "home_bullpen_recent_whip","away_bullpen_recent_whip",
)


def _num(x: Any, d: float | None = 0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def vector(features: dict[str,Any], means: dict[str,float] | None = None) -> list[float]:
    means = means or {}
    out = []
    for name in FEATURES:
        v = _num(features.get(name), None)
        out.append(_num(means.get(name),0.0) if v is None else float(v))
    return out


def fit_ridge(xs: list[list[float]], ys: list[float], ridge: float = 12.0) -> list[float]:
    """Small dependency-free ridge model used only after strict validation.

    V13 does not hard-code baseball feature weights as production truth. The
    structural engine remains a safe baseline; this learned residual layer is
    eligible only when an external validator proves improvement.
    """
    if not xs:
        return []
    p = len(xs[0])+1
    a = [[0.0]*p for _ in range(p)]
    b = [0.0]*p
    for x,y in zip(xs,ys):
        z = [1.0]+x
        for i in range(p):
            b[i] += z[i]*y
            for j in range(p):
                a[i][j] += z[i]*z[j]
    for i in range(1,p):
        a[i][i] += ridge
    # Gauss-Jordan with pivoting.
    m = [a[i]+[b[i]] for i in range(p)]
    for col in range(p):
        pivot = max(range(col,p), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            continue
        m[col],m[pivot] = m[pivot],m[col]
        div = m[col][col]
        m[col] = [v/div for v in m[col]]
        for r in range(p):
            if r == col:
                continue
            f = m[r][col]
            if abs(f) > 1e-15:
                m[r] = [u-f*v for u,v in zip(m[r],m[col])]
    return [m[i][-1] for i in range(p)]


def predict(coefs: list[float], x: list[float], cap: float = .65) -> float:
    if not coefs:
        return 0.0
    value = coefs[0]+sum(c*v for c,v in zip(coefs[1:],x))
    return max(-cap,min(cap,value))
