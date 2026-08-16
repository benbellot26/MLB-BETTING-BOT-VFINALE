from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import calibration_baseball_v13 as calibration
from . import uncertainty_v13
from .probability_contract_v13 import option_contract_payload


@dataclass
class ProbabilityPipelineV13:
    calibration_model: dict[str,Any]

    @classmethod
    def from_artifact(cls):
        return cls(calibration.load_model())

    @staticmethod
    def baseball_raw(option: dict[str,Any]) -> float:
        if option.get("p_learned") is not None:
            return float(option["p_learned"])
        if option.get("p_structural") is not None:
            return float(option["p_structural"])
        raise ValueError("baseball-only probability unavailable")

    def calibrate(self, option: dict[str,Any], phase: str) -> tuple[float,str,int]:
        return calibration.calibrate(
            self.baseball_raw(option), str(option.get("market") or "ML"), phase, self.calibration_model
        )

    def transform_option(self, option: dict[str,Any], phase: str, data_quality: float = 1.0) -> dict[str,Any]:
        raw = self.baseball_raw(option)
        calibrated, source, n = self.calibrate(option, phase)
        market = option.get("p_market")
        market_weight = max(0.0,min(.35,float(option.get("sharp_weight") or 0.0)))
        posterior = None if market is None else (1-market_weight)*calibrated+market_weight*float(market)
        interval = uncertainty_v13.empirical_interval(
            calibrated,
            calibration_n=n,
            sharp_dispersion=option.get("sharp_dispersion"),
            data_quality=data_quality,
        )
        option.update(option_contract_payload(
            p_baseball_raw=raw,
            p_baseball_calibrated=calibrated,
            p_market=market,
            p_posterior=posterior,
            calibration_source=source,
            calibration_n=n,
            interval_low=interval["low"],
            interval_high=interval["high"],
        ))
        option["probability_uncertainty_v13"] = interval
        return option

    def transform_result(self, result: dict[str,Any]) -> dict[str,Any]:
        phase = str(result.get("phase") or "EARLY").upper()
        dq = float((result.get("data_quality") or {}).get("score") or 1.0)
        for option in result.get("options") or []:
            self.transform_option(option, phase, dq)
        return result
