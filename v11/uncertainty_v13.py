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
                       empirical_sigma: float | None = None,
                       sharp_dispersion: float | None = None, data_quality: float = 1.0,
                       z: float = 1.645) -> dict[str,float | int | str | bool | None]:
    p = max(.001,min(.999,_num(p,.5)))
    pn = max(0,int(phase_n or 0)); mn = max(0,int(market_n or 0)); cn = max(0,int(calibration_n or 0))
    if pn > 0:
        n = pn; evidence_scope = "phase"; scope_penalty = 1.0
    elif cn > 0:
        n = cn; evidence_scope = "calibrator"; scope_penalty = 1.15
    elif mn > 0:
        n = mn; evidence_scope = "market-cross-phase"; scope_penalty = 1.25
    else:
        n = 1; evidence_scope = "none"; scope_penalty = 1.0

    sampling = scope_penalty*math.sqrt(max(.01,p*(1-p))/max(1,n))
    calibration = abs(_num(reliability_gap,0.0))
    empirical = max(0.0,_num(empirical_sigma,0.0))
    dq_score = max(0.0,min(1.0,_num(data_quality,1.0)))
    dq = .065*max(0.0,1-dq_score)

    # This is an engineering uncertainty band, not a frequentist confidence
    # interval with empirically demonstrated 90% coverage. The z=1.645 scaling
    # remains a nominal width convention only until coverage is validated.
    epistemic_floor = max(calibration, empirical)
    sigma = math.sqrt(sampling*sampling + epistemic_floor*epistemic_floor + dq*dq)
    sigma = max(.018,min(.14,sigma))
    market_disagreement = max(0.0,_num(sharp_dispersion,0.0)) if sharp_dispersion is not None else 0.0
    return {
        "sigma":sigma,
        "low":max(.001,p-z*sigma),
        "high":min(.999,p+z*sigma),
        "confidence_level":.90,  # backward-compatible nominal width metadata
        "nominal_level":.90,
        "coverage_validated":False,
        "user_facing_type":"model_uncertainty_band",
        "method":"phase-aware-empirical-reliability-plus-data-quality-v3",
        "evidence_scope":evidence_scope,
        "effective_n":n,
        "phase_n":pn,
        "market_n":mn,
        "data_quality":dq_score,
        "empirical_reliability_sigma": empirical if empirical > 0 else None,
        "market_disagreement_sigma": market_disagreement,
        "market_disagreement_affects_baseball_interval": False,
    }
