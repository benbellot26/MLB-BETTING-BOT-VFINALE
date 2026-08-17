from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        market_name = str(option.get("market") or "ML")
        calibrated, source, n = self.calibrate(option, phase)
        evidence = calibration.evidence_counts(self.calibration_model, market_name, phase)
        # Reliability bins are fitted in raw-probability space. Query them with
        # the raw probability even after a Platt/Beta calibrator becomes active;
        # otherwise a transformed probability could be matched to the wrong bin.
        empirical_sigma, reliability_source = calibration.reliability_sigma(
            self.calibration_model, market_name, phase, raw
        )
        market = option.get("p_market")
        market_weight = max(0.0,min(.35,float(option.get("sharp_weight") or 0.0)))
        posterior = None if market is None else (1-market_weight)*calibrated+market_weight*float(market)
        interval = uncertainty_v13.empirical_interval(
            calibrated,
            calibration_n=n,
            phase_n=evidence["phase_n"],
            market_n=evidence["market_n"],
            empirical_sigma=empirical_sigma,
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
        option["calibration_phase_n_v13"] = evidence["phase_n"]
        option["calibration_market_n_v13"] = evidence["market_n"]
        option["probability_uncertainty_v13"] = interval
        option["reliability_source_v13"] = reliability_source
        return option

    def transform_result(self, result: dict[str,Any]) -> dict[str,Any]:
        phase = str(result.get("phase") or "EARLY").upper()
        dq = float((result.get("data_quality") or {}).get("model_input_score") or (result.get("data_quality") or {}).get("score") or 1.0)
        for option in result.get("options") or []:
            self.transform_option(option, phase, dq)
        return result
