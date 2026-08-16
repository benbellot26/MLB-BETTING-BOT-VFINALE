from __future__ import annotations

import math
from typing import Any


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def empirical_interval(p: float, *, calibration_n: int, reliability_gap: float | None = None,
                       sharp_dispersion: float | None = None, data_quality: float = 1.0,
                       z: float = 1.645) -> dict[str,float]:
    p = max(.001,min(.999,_num(p,.5)))
    n = max(1,int(calibration_n or 0))
    binomial = math.sqrt(max(.01,p*(1-p))/n)
    calibration = abs(_num(reliability_gap,0.0))
    market = .25*max(0.0,_num(sharp_dispersion,0.0)) if sharp_dispersion is not None else 0.0
    dq = .04*max(0.0,1-_num(data_quality,1.0))
    sigma = math.sqrt(binomial*binomial + calibration*calibration + market*market + dq*dq)
    # Never claim implausibly tiny epistemic uncertainty on MLB probabilities.
    sigma = max(.018,min(.14,sigma))
    return {
        "sigma":sigma,
        "low":max(.001,p-z*sigma),
        "high":min(.999,p+z*sigma),
        "confidence_level":.90,
        "method":"empirical-reliability-plus-data-quality",
    }
