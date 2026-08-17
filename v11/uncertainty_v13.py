from __future__ import annotations

import math
from typing import Any


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def empirical_interval(p: float, *, calibration_n: int, phase_n: int | None = None,
                       market_n: int | None = None, reliability_gap: float | None = None,
                       sharp_dispersion: float | None = None, data_quality: float = 1.0,
                       z: float = 1.645) -> dict[str,float]:
    p = max(.001,min(.999,_num(p,.5)))
    pn = max(0,int(phase_n or 0)); mn = max(0,int(market_n or 0)); cn = max(0,int(calibration_n or 0))
    # Prefer same-phase evidence. Cross-phase evidence is allowed only as a
    # fallback and receives a conservatism penalty because EARLY/LATE/FINAL do
    # not have identical error distributions.
    if pn > 0:
        n = pn; evidence_scope = "phase"
        scope_penalty = 1.0
    elif cn > 0:
        n = cn; evidence_scope = "calibrator"
        scope_penalty = 1.15
    elif mn > 0:
        n = mn; evidence_scope = "market-cross-phase"
        scope_penalty = 1.25
    else:
        n = 1; evidence_scope = "none"
        scope_penalty = 1.0
    sampling = scope_penalty*math.sqrt(max(.01,p*(1-p))/max(1,n))
    calibration = abs(_num(reliability_gap,0.0))
    market = .25*max(0.0,_num(sharp_dispersion,0.0)) if sharp_dispersion is not None else 0.0
    dq_score = max(0.0,min(1.0,_num(data_quality,1.0)))
    # Missing/weak pregame inputs are epistemic uncertainty and must widen the
    # displayed interval even if historical calibration volume is large.
    dq = .065*max(0.0,1-dq_score)
    sigma = math.sqrt(sampling*sampling + calibration*calibration + market*market + dq*dq)
    # Avoid false precision while native V13 evidence is still limited.
    sigma = max(.018,min(.14,sigma))
    return {
        "sigma":sigma,
        "low":max(.001,p-z*sigma),
        "high":min(.999,p+z*sigma),
        "confidence_level":.90,
        "method":"phase-aware-empirical-reliability-plus-data-quality",
        "evidence_scope":evidence_scope,
        "effective_n":n,
        "phase_n":pn,
        "market_n":mn,
        "data_quality":dq_score,
    }
