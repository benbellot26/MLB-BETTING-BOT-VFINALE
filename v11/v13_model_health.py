from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import calibration_baseball_v13 as calibration
from . import v13_daily_tracking as tracking
from . import v13_rich_native_train as rich_native
from . import v137_free_data_health as free_data_health
from . import v138_model_health_bridge as v138_health
from . import v139_engineering_closure as v139_closure
from .probability_contract_v13 import MODEL_GENERATION_FINGERPRINT

OUT = Path("data/v13_model_health.json")
SCHEMA = "v13-model-health-v4"


def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _probability_drift(states: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        state
        for state in states
        if state.get("settled_result") in {"WIN", "LOSS"} and state.get("p_model") is not None
    ]
    rows.sort(key=lambda state: str(state.get("observation_at") or state.get("observed_at") or ""))
    out: dict[str, Any] = {}
    for market in ("ML", "RUNLINE", "TOTAL"):
        values = [
            _num(state.get("p_model"), .5)
            for state in rows
            if str(state.get("market") or "").upper() == market
        ]
        recent = values[-50:]
        prior = values[-100:-50]
        out[market] = {
            "observations": len(values),
            "recent_n": len(recent),
            "prior_n": len(prior),
            "recent_mean_probability": sum(recent) / len(recent) if recent else None,
            "prior_mean_probability": sum(prior) / len(prior) if prior else None,
            "mean_probability_shift": (
                sum(recent) / len(recent) - sum(prior) / len(prior)
                if recent and prior
                else None
            ),
        }
    return out


def build() -> dict[str, Any]:
    cal = calibration.load_model()
    rich = _load("data/v13_rich_native_candidate.json") or rich_native.build()
    diag = _load("data/v13_probability_diagnostics.json")
    coverage = _load("data/v13_coverage_report.json")
    posterior = _load("data/v13_posterior_policy.json")
    free_data = free_data_health.build()
    closure_health = v138_health.build()
    engineering = v139_closure.build()
    states = list(tracking.fold().values())

    calibrators = cal.get("calibrators") or {}
    calibration_status = {
        key: {
            "active": bool(value.get("active")),
            "method": value.get("method"),
            "n": int(value.get("n") or 0),
            "status": value.get("status"),
            "strict_required_n": value.get("strict_required_n"),
        }
        for key, value in calibrators.items()
        if key == "GLOBAL" or key.startswith("MARKET:") or key.startswith("PHASE:FINAL:")
    }

    alerts: list[str] = []
    if int(rich.get("native_games") or 0) == 0:
        alerts.append("rich_native_games_zero")
    if coverage and not coverage.get("complete_future_coverage", True):
        alerts.append("daily_future_coverage_incomplete")
    if int(engineering.get("engineering_open") or 0):
        alerts.append(f"v139_engineering_open:{int(engineering['engineering_open'])}")
    if free_data.get("status") == "DEGRADED":
        alerts.append("free_provider_health_degraded")

    for market, metrics in (diag.get("by_market") or {}).items():
        if int(metrics.get("n") or 0) >= 30 and _num(metrics.get("brier_gain_vs_market"), 0) < 0:
            alerts.append(f"{market.lower()}_brier_worse_than_market")
        if (
            int(metrics.get("n") or 0) >= 30
            and metrics.get("gap_residual_slope") is not None
            and _num(metrics.get("gap_residual_slope")) <= 0
        ):
            alerts.append(f"{market.lower()}_model_market_gap_not_informative")

    for alert in free_data.get("alerts") or []:
        alerts.append(f"free_data:{alert}")
    for alert in closure_health.get("alerts") or []:
        alerts.append(f"v138:{alert}")

    return {
        "schema": SCHEMA,
        "model_generation": MODEL_GENERATION_FINGERPRINT,
        "engineering_closure": {
            "schema": engineering.get("schema"),
            "total_points": engineering.get("total_points"),
            "engineering_closed": engineering.get("engineering_closed"),
            "engineering_open": engineering.get("engineering_open"),
            "all_engineering_closed": engineering.get("all_engineering_closed"),
        },
        "calibration": calibration_status,
        "rich_native": {
            "status": rich.get("status"),
            "native_games": rich.get("native_games"),
            "minimum_games": rich.get("minimum_games"),
            "feature_coverage": rich.get("native_feature_coverage"),
            "rejection_reasons": rich.get("native_rejection_reasons"),
            "active_for_production": bool(rich.get("active_for_production")),
        },
        "posterior": {
            "historical_observations": posterior.get("historical_observations"),
            "live_observations": posterior.get("live_observations"),
            "primary_probability_affected": posterior.get("primary_probability_affected"),
        },
        "proper_scoring_vs_market": diag.get("by_market") or {},
        "daily_coverage": {
            "complete_future_coverage": coverage.get("complete_future_coverage"),
            "status_counts": coverage.get("status_counts"),
            "future_coverage_rate": coverage.get("future_coverage_rate"),
        },
        "probability_drift": _probability_drift(states),
        "free_data_foundation": free_data,
        "free_provider_status": free_data.get("status"),
        "free_provider_metrics": free_data.get("provider_metrics") or {},
        "v138_audit_research": closure_health,
        "alerts": sorted(set(alerts)),
        "claim": "monitoring artifact only; alerts indicate evidence to investigate, not automatic model retuning",
    }


def main() -> None:
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
