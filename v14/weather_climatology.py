from __future__ import annotations

"""Venue/month physical-weather baseline from NASA POWER climatology.

This is reference climatology, not a game result or market feature. It supplies
an independent venue/month baseline for V14's weather-physics challenger so
altitude/climate are not double counted as a same-day weather effect.
"""

import calendar
import math
from typing import Any, Callable

from .acquisition import http_json
from .environment_physics_challenger import air_density_kg_m3, wind_out_component_mph

URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
ROLE = "SHADOW_ONLY"
Getter = Callable[[str, dict[str, Any]], Any]
PARAMETERS = "T2M,RH2M,PS,WS10M,WD10M"


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out) or out <= -900:
        return None
    return out


def _month_key(month: int) -> str:
    if not 1 <= int(month) <= 12:
        raise ValueError("month must be in 1..12")
    return calendar.month_abbr[int(month)].upper()


def _parameter(payload: dict[str, Any], name: str, month: int) -> float | None:
    params = (((payload or {}).get("properties") or {}).get("parameter") or {})
    row = params.get(name) or {}
    return _num(row.get(_month_key(month)))


def _base(status: str, reason: str | None = None) -> dict[str, Any]:
    out = {
        "schema": "pulsar-v14-venue-weather-climatology-v1",
        "role": ROLE,
        "status": status,
        "auto_activation": False,
        "champion_impact": False,
        "market_probability_used_as_feature": False,
        "reference_data": True,
    }
    if reason:
        out["reason"] = reason
    return out


def fetch(latitude: float, longitude: float, *, month: int, outfield_bearing_deg: float, getter: Getter = http_json) -> dict[str, Any]:
    try:
        lat = float(latitude); lon = float(longitude); bearing = float(outfield_bearing_deg)
    except Exception:
        return _base("COLLECTING", "invalid venue geometry")
    if not all(map(math.isfinite, (lat, lon, bearing))) or not 0 <= bearing < 360:
        return _base("COLLECTING", "invalid venue geometry")
    try:
        key = _month_key(month)
    except Exception as exc:
        return _base("COLLECTING", str(exc))
    params = {
        "parameters": PARAMETERS,
        "community": "SB",
        "longitude": lon,
        "latitude": lat,
        "format": "JSON",
    }
    try:
        payload = getter(URL, params) or {}
    except Exception as exc:
        return _base("UNAVAILABLE", f"NASA POWER climatology fetch failed: {type(exc).__name__}: {exc}")

    temp_c = _parameter(payload, "T2M", month)
    humidity = _parameter(payload, "RH2M", month)
    pressure_raw = _parameter(payload, "PS", month)
    wind_ms = _parameter(payload, "WS10M", month)
    wind_from = _parameter(payload, "WD10M", month)
    missing = [name for name, value in (("T2M", temp_c), ("RH2M", humidity), ("PS", pressure_raw), ("WS10M", wind_ms), ("WD10M", wind_from)) if value is None]
    if missing:
        return {**_base("COLLECTING", "NASA POWER climatology variables incomplete"), "missing": missing, "month": key}

    # POWER surface pressure is commonly returned in kPa; accept hPa-shaped
    # payloads too and normalize by magnitude rather than silently assuming.
    pressure_hpa = float(pressure_raw) * 10.0 if float(pressure_raw) < 200.0 else float(pressure_raw)
    if not 700.0 <= pressure_hpa <= 1100.0 or not 0.0 <= float(humidity) <= 100.0 or not -80.0 <= float(temp_c) <= 60.0:
        return _base("UNAVAILABLE", "NASA POWER climatology values outside physical bounds")
    temp_f = float(temp_c) * 9.0 / 5.0 + 32.0
    wind_mph = max(0.0, float(wind_ms)) * 2.2369362920544
    density = air_density_kg_m3(temp_f, float(humidity), pressure_hpa)
    wind_out = wind_out_component_mph(wind_mph, float(wind_from), bearing)
    return {
        **_base("READY_SHADOW"),
        "month": key,
        "latitude": lat,
        "longitude": lon,
        "outfield_bearing_deg": bearing,
        "temperature_c": float(temp_c),
        "humidity_pct": float(humidity),
        "surface_pressure_hpa": pressure_hpa,
        "wind_speed_mph": wind_mph,
        "wind_direction_deg": float(wind_from),
        "venue_baseline_density_kg_m3": density,
        "venue_baseline_wind_out_mph": wind_out,
        "source": "NASA POWER climatology API",
        "source_parameters": PARAMETERS,
        "source_contract": "monthly reference climatology; no game outcomes or market probabilities",
        "no_imputation": True,
    }
