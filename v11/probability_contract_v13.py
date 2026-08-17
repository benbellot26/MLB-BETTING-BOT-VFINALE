from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any

PREDICTIVE_CONTRACT_VERSION = "v13-predictive-contract-v2"
FEATURE_CONTRACT_VERSION = "v13-baseball-features-v1"
TARGET_CONTRACT_VERSION = "v13-market-targets-v1"
CALIBRATION_CONTRACT_VERSION = "v13-baseball-calibration-v2"
MODEL_GENERATION_FINGERPRINT = "v13.5.2-gen-structural-nb-independent-transfer-v2"


def _num(x: Any, default: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else default
    except Exception:
        return default


def clip_probability(p: Any) -> float:
    return max(0.001, min(0.999, _num(p, 0.5)))


@dataclass(frozen=True)
class PredictiveContract:
    feature_contract: str = FEATURE_CONTRACT_VERSION
    target_contract: str = TARGET_CONTRACT_VERSION
    probability_contract: str = PREDICTIVE_CONTRACT_VERSION
    calibration_contract: str = CALIBRATION_CONTRACT_VERSION
    model_generation: str = MODEL_GENERATION_FINGERPRINT

    def compatible_with(self, payload: dict[str, Any] | None) -> bool:
        payload = payload or {}
        return all(payload.get(k) == v for k, v in asdict(self).items())


CONTRACT = PredictiveContract()


def row_contract(row: dict[str, Any]) -> dict[str, str]:
    payload = row.get("predictive_contract") or {}
    if payload:
        return {k: str(payload.get(k) or "") for k in asdict(CONTRACT)}
    return {}


def row_is_predictively_compatible(row: dict[str, Any]) -> bool:
    return CONTRACT.compatible_with(row_contract(row))


def attach_contract(row: dict[str, Any]) -> dict[str, Any]:
    row["predictive_contract"] = asdict(CONTRACT)
    row["model_generation_fingerprint"] = MODEL_GENERATION_FINGERPRINT
    return row


def baseball_probability(option: dict[str, Any]) -> float:
    """Return the calibrated baseball-only probability."""
    if option.get("p_baseball_calibrated") is not None:
        return clip_probability(option["p_baseball_calibrated"])
    if option.get("p_baseball_raw") is not None:
        return clip_probability(option["p_baseball_raw"])
    raise ValueError("V13 option missing baseball-only probability")


def posterior_probability(option: dict[str, Any]) -> float | None:
    value = option.get("p_posterior")
    return clip_probability(value) if value is not None else None


def market_probability(option: dict[str, Any]) -> float | None:
    value = option.get("p_market")
    return clip_probability(value) if value is not None else None


def probability_gap(option: dict[str, Any]) -> float | None:
    market = market_probability(option)
    if market is None:
        return None
    return baseball_probability(option) - market


def assert_no_market_leakage(option: dict[str, Any]) -> None:
    source = str(option.get("baseball_probability_source") or "")
    if "sharp" in source.lower() or "market" in source.lower():
        raise ValueError("market-derived source cannot define V13 baseball probability")
    if option.get("p_baseball_raw") is None:
        raise ValueError("p_baseball_raw is required")
    if option.get("p_baseball_calibrated") is None:
        raise ValueError("p_baseball_calibrated is required")


def option_contract_payload(
    *,
    p_baseball_raw: float,
    p_baseball_calibrated: float,
    p_market: float | None,
    p_posterior: float | None,
    calibration_source: str,
    calibration_n: int = 0,
    interval_low: float | None = None,
    interval_high: float | None = None,
) -> dict[str, Any]:
    raw = clip_probability(p_baseball_raw)
    calibrated = clip_probability(p_baseball_calibrated)
    market = clip_probability(p_market) if p_market is not None else None
    posterior = clip_probability(p_posterior) if p_posterior is not None else None
    low = clip_probability(interval_low) if interval_low is not None else None
    high = clip_probability(interval_high) if interval_high is not None else None
    if low is not None and high is not None and low > high:
        low, high = high, low
    return {
        "p_baseball_raw": round(raw, 6),
        "p_baseball_calibrated": round(calibrated, 6),
        "p_market": round(market, 6) if market is not None else None,
        "p_posterior": round(posterior, 6) if posterior is not None else None,
        "model_market_gap": round(calibrated - market, 6) if market is not None else None,
        "baseball_probability_source": "baseball-only-score-distribution",
        "calibration_source_v13": str(calibration_source),
        "calibration_n_v13": int(max(0, calibration_n)),
        "probability_interval_low": round(low, 6) if low is not None else None,
        "probability_interval_high": round(high, 6) if high is not None else None,
    }
