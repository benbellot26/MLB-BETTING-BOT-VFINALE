from __future__ import annotations

"""Physics-oriented park/weather diagnostics for Pulsar V14.

The champion keeps its bounded legacy weather residual. This module provides a
research-only representation based on moist-air density and the wind component
along the home-plate-to-outfield bearing when those PIT inputs are available.
It intentionally refuses to invent missing humidity, pressure, direction or park
orientation.
"""

import math
from typing import Any

ROLE = "CHALLENGER_ONLY"
STANDARD_DENSITY_KG_M3 = 1.225


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def air_density_kg_m3(temperature_f: float, humidity_pct: float, pressure_hpa: float) -> float:
    """Approximate moist-air density using ideal-gas dry-air/water-vapor terms."""
    temp_c = (float(temperature_f) - 32.0) * 5.0 / 9.0
    temp_k = temp_c + 273.15
    if temp_k <= 0:
        raise ValueError("invalid absolute temperature")
    rh = _clip(float(humidity_pct), 0.0, 100.0) / 100.0
    pressure_pa = float(pressure_hpa) * 100.0
    if pressure_pa <= 0:
        raise ValueError("pressure must be positive")
    saturation_hpa = 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))
    vapor_pa = rh * saturation_hpa * 100.0
    dry_pa = max(0.0, pressure_pa - vapor_pa)
    return dry_pa / (287.05 * temp_k) + vapor_pa / (461.495 * temp_k)


def wind_out_component_mph(
    wind_speed_mph: float,
    wind_from_deg: float,
    outfield_bearing_deg: float,
) -> float:
    """Positive means wind blowing from home plate toward the outfield."""
    speed = max(0.0, float(wind_speed_mph))
    # Meteorological direction is where wind comes FROM; motion points +180°.
    wind_to = (float(wind_from_deg) + 180.0) % 360.0
    angle = math.radians(wind_to - float(outfield_bearing_deg))
    return speed * math.cos(angle)


def evaluate(environment: dict[str, Any] | None) -> dict[str, Any]:
    data = environment if isinstance(environment, dict) else {}
    roof = str(data.get("roof") or "").lower()
    if any(token in roof for token in ("closed", "dome", "roofed")):
        return {
            "schema": "pulsar-v14-environment-physics-challenger-v1",
            "role": ROLE,
            "status": "READY_SHADOW",
            "auto_activation": False,
            "indoor": True,
            "density_ratio": 1.0,
            "wind_out_component_mph": 0.0,
            "flight_environment_index": 0.0,
            "reason": "closed roof neutralized",
        }

    temp = _num(data.get("temperature_f"))
    humidity = _num(data.get("humidity_pct"))
    pressure = _num(data.get("pressure_hpa"))
    wind_speed = _num(data.get("wind_mph"))
    wind_from = _num(data.get("wind_direction_deg"))
    bearing = _num(data.get("outfield_bearing_deg"))

    missing = [
        name
        for name, value in (
            ("temperature_f", temp),
            ("humidity_pct", humidity),
            ("pressure_hpa", pressure),
            ("wind_mph", wind_speed),
            ("wind_direction_deg", wind_from),
            ("outfield_bearing_deg", bearing),
        )
        if value is None
    ]
    if missing:
        return {
            "schema": "pulsar-v14-environment-physics-challenger-v1",
            "role": ROLE,
            "status": "COLLECTING",
            "auto_activation": False,
            "missing": missing,
            "reason": "physical weather inputs incomplete; no values imputed",
        }

    density = air_density_kg_m3(temp, humidity, pressure)
    density_ratio = density / STANDARD_DENSITY_KG_M3
    wind_out = wind_out_component_mph(wind_speed, wind_from, bearing)
    # Dimensionless diagnostic only. Lower density and outward wind are more
    # carry-friendly. It is NOT a run multiplier until validated OOS.
    flight_index = _clip((1.0 - density_ratio) * 5.0 + wind_out / 40.0, -1.0, 1.0)
    return {
        "schema": "pulsar-v14-environment-physics-challenger-v1",
        "role": ROLE,
        "status": "READY_SHADOW",
        "auto_activation": False,
        "indoor": False,
        "air_density_kg_m3": density,
        "density_ratio": density_ratio,
        "wind_out_component_mph": wind_out,
        "flight_environment_index": flight_index,
        "market_probability_used_as_feature": False,
    }
