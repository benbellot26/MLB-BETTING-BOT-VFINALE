from __future__ import annotations

import math
import os
import re

from . import core

WEATHER_VERSION = "v12.4-weather-v2"

_GAME_WEATHER_CACHE = {}
_VENUE_CACHE = {}

_ACTUAL_ROOF_OPEN = {"roofopen"}
_ACTUAL_ROOF_CLOSED = {
    "roofclosednopanel", "roofclosedpanelopen", "roofclosedpanelclosed",
}
_RETRACTABLE_WORDS = {"retractable", "retractableroof", "retractabledome"}
_DOME_WORDS = {"dome", "fixedroof", "closed"}
_OPEN_AIR_WORDS = {"open", "openair", "noroof", "outdoor"}


def _num(x, d=None):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _norm(value):
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))


def _game_pk(result):
    return (result.get("game") or {}).get("gamePk") or result.get("game_pk")


def _venue_id(result):
    return (((result.get("game") or {}).get("venue") or {}).get("id"))


def _first_schedule_game(payload):
    for block in (payload or {}).get("dates") or []:
        games = block.get("games") or []
        if games:
            return games[0]
    return {}


def _deep_actual_roof_state(obj):
    """Find only actual roof-state enums, never infer state from venue roof type."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            nk = _norm(key)
            if isinstance(value, str) and nk in {"roof", "roofstate", "roofstatus", "currentroof", "rooftype"}:
                nv = _norm(value)
                if nv in _ACTUAL_ROOF_OPEN:
                    return "OPEN"
                if nv in _ACTUAL_ROOF_CLOSED:
                    return "CLOSED"
            found = _deep_actual_roof_state(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _deep_actual_roof_state(value)
            if found:
                return found
    return None


def _venue_metadata(result):
    venue_id = _venue_id(result)
    if not venue_id:
        return {"available": False, "reason": "venue_id_missing"}
    key = str(venue_id)
    if key in _VENUE_CACHE:
        return _VENUE_CACHE[key]
    try:
        payload = core.mlb("v1/venues", {"venueIds": venue_id, "season": core.SEASON}) or {}
        venues = payload.get("venues") or []
        venue = venues[0] if venues else {}
        location = venue.get("location") or {}
        field = venue.get("fieldInfo") or {}
        out = {
            "available": bool(venue),
            "venue_id": venue_id,
            "venue_name": venue.get("name"),
            "azimuth_deg": _num(location.get("azimuthAngle"), None),
            "elevation_ft": _num(location.get("elevation"), None),
            "roof_type": field.get("roofType"),
            "turf_type": field.get("turfType"),
        }
    except Exception as exc:
        out = {"available": False, "venue_id": venue_id, "reason": f"venue_error:{type(exc).__name__}"}
    _VENUE_CACHE[key] = out
    return out


def _mlb_game_weather(result):
    gid = _game_pk(result)
    if not gid:
        return {"available": False, "reason": "game_pk_missing"}
    key = str(gid)
    if key in _GAME_WEATHER_CACHE:
        return _GAME_WEATHER_CACHE[key]
    game = result.get("game") or {}
    if isinstance(game.get("weather"), dict):
        out = {"available": True, "weather": game.get("weather") or {}, "roof_state": _deep_actual_roof_state(game),
               "source": "game_payload"}
        _GAME_WEATHER_CACHE[key] = out
        return out
    try:
        payload = core.mlb("v1/schedule", {
            "sportId": 1, "gamePk": gid, "hydrate": "weather,venue",
        }) or {}
        hydrated = _first_schedule_game(payload)
        weather = hydrated.get("weather") or {}
        out = {
            "available": bool(weather), "weather": weather,
            "roof_state": _deep_actual_roof_state(hydrated),
            "source": "mlb_schedule_hydrate",
        }
    except Exception as exc:
        out = {"available": False, "reason": f"mlb_weather_error:{type(exc).__name__}"}
    _GAME_WEATHER_CACHE[key] = out
    return out


def _roof_policy(result, venue, mlb_weather):
    home = str((result.get("ctx") or {}).get("home") or "")
    home_norm = _norm(home)
    open_override = {_norm(x) for x in os.getenv("V124_ROOF_OPEN_TEAMS", "").split(",") if x.strip()}
    closed_override = {_norm(x) for x in os.getenv("V124_ROOF_CLOSED_TEAMS", "").split(",") if x.strip()}
    if home_norm in open_override:
        return {"state": "OPEN", "source": "env_override", "weather_applies": True}
    if home_norm in closed_override:
        return {"state": "CLOSED", "source": "env_override", "weather_applies": False}

    actual = str((mlb_weather or {}).get("roof_state") or "").upper()
    if actual == "OPEN":
        return {"state": "OPEN", "source": "mlb_game", "weather_applies": True}
    if actual == "CLOSED":
        return {"state": "CLOSED", "source": "mlb_game", "weather_applies": False}

    roof_type = _norm((venue or {}).get("roof_type"))
    if roof_type in _OPEN_AIR_WORDS:
        return {"state": "NO_ROOF", "source": "mlb_venue", "weather_applies": True}
    if roof_type in _DOME_WORDS:
        return {"state": "CLOSED", "source": "mlb_venue", "weather_applies": False}
    if roof_type in _RETRACTABLE_WORDS:
        return {"state": "UNKNOWN_RETRACTABLE", "source": "mlb_venue", "weather_applies": False}

    # Backward-compatible safety if the venue endpoint omits roof metadata.
    try:
        from . import predictive_v124 as v124
        if home in getattr(v124, "_RETRACTABLE_OR_COVERED", set()):
            return {"state": "UNKNOWN_RETRACTABLE", "source": "team_safety_list", "weather_applies": False}
    except Exception:
        pass
    return {"state": "OPEN_AIR_ASSUMED", "source": "no_roof_metadata", "weather_applies": True}


def _parse_mlb_relative_wind(weather):
    text = str((weather or {}).get("wind") or "").strip()
    if not text:
        return None
    low = text.lower()
    if "calm" in low or low in {"none", "n/a"}:
        return {"out_kph": 0.0, "cross_kph": 0.0, "speed_kph": 0.0,
                "label": text, "source": "mlb_relative"}
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*mph", low)
    if not m:
        return None
    speed_kph = float(m.group(1))*1.609344
    if "out to cf" in low or "out to center" in low:
        out, cross = speed_kph, 0.0
    elif "in from cf" in low or "in from center" in low:
        out, cross = -speed_kph, 0.0
    elif "out to lf" in low or "out to rf" in low:
        out, cross = .72*speed_kph, .69*speed_kph
    elif "in from lf" in low or "in from rf" in low:
        out, cross = -.72*speed_kph, .69*speed_kph
    elif "l to r" in low or "left to right" in low:
        out, cross = 0.0, speed_kph
    elif "r to l" in low or "right to left" in low:
        out, cross = 0.0, -speed_kph
    else:
        return None
    return {"out_kph": out, "cross_kph": cross, "speed_kph": speed_kph,
            "label": text, "source": "mlb_relative"}


def _project_wind_by_bearing(wind_kph, direction_from_deg, field_azimuth_deg):
    speed = max(0.0, _num(wind_kph, 0.0) or 0.0)
    from_deg = _num(direction_from_deg, None)
    az = _num(field_azimuth_deg, None)
    if from_deg is None or az is None:
        return None
    # Meteorological wind direction is where wind comes FROM. Convert to travel direction.
    to_deg = (from_deg+180.0) % 360.0
    diff = math.radians(((to_deg-az+180.0) % 360.0)-180.0)
    return {
        "out_kph": speed*math.cos(diff),
        "cross_kph": speed*math.sin(diff),
        "speed_kph": speed,
        "direction_from_deg": from_deg,
        "direction_to_deg": to_deg,
        "field_azimuth_deg": az,
        "source": "openmeteo_x_mlb_venue_azimuth",
    }


def _air_density_kg_m3(temp_c, humidity_pct, pressure_hpa):
    temp = _num(temp_c, None)
    rh = _num(humidity_pct, None)
    pressure = _num(pressure_hpa, None)
    if temp is None or rh is None:
        return None
    if pressure is None:
        pressure = 1013.25
    rh = _clamp(rh, 0.0, 100.0)
    t_k = temp+273.15
    if t_k <= 0:
        return None
    # Tetens saturation vapor pressure, then moist-air density.
    sat_hpa = 6.112*math.exp((17.67*temp)/(temp+243.5))
    vapor_hpa = rh/100.0*sat_hpa
    dry_hpa = max(1.0, pressure-vapor_hpa)
    return (dry_hpa*100.0)/(287.05*t_k)+(vapor_hpa*100.0)/(461.495*t_k)


def _weather_module(result, active=True):
    from . import predictive_v124 as v124
    out = v124._module_base("weather_park", active)
    if not active:
        return out
    features = result.get("features") or {}
    weather = features.get("weather") or {}
    home = str((result.get("ctx") or {}).get("home") or "")
    park = _num(features.get("park_factor"), core.PARK.get(home, 1.0)) or 1.0
    if not weather.get("available"):
        out.update({"status": "UNAVAILABLE", "details": {"reason": weather.get("reason"), "version": WEATHER_VERSION}})
        return out

    venue = _venue_metadata(result)
    mlb_weather = _mlb_game_weather(result)
    roof = _roof_policy(result, venue, mlb_weather)
    details = {
        "version": WEATHER_VERSION,
        "home": home,
        "park_factor": park,
        "venue": venue,
        "roof": roof,
        "openmeteo": {
            "temperature_c": weather.get("temperature_c"),
            "humidity_pct": weather.get("humidity_pct"),
            "surface_pressure_hpa": weather.get("surface_pressure_hpa"),
            "precip_probability": weather.get("precip_probability"),
            "wind_kph": weather.get("wind_kph"),
            "wind_gust_kph": weather.get("wind_gust_kph"),
            "wind_direction_deg": weather.get("wind_direction_deg"),
            "dew_point_c": weather.get("dew_point_c"),
            "cloud_cover_pct": weather.get("cloud_cover_pct"),
        },
        "mlb_game_weather": (mlb_weather or {}).get("weather"),
    }
    if not roof.get("weather_applies"):
        out.update({"status": "ROOF_NEUTRAL" if roof.get("state") != "UNKNOWN_RETRACTABLE" else "ROOF_UNKNOWN_NEUTRAL",
                    "coverage": 1.0, "details": details})
        return out

    relative = _parse_mlb_relative_wind((mlb_weather or {}).get("weather") or {})
    if relative is None:
        relative = _project_wind_by_bearing(
            weather.get("wind_kph"), weather.get("wind_direction_deg"), venue.get("azimuth_deg"),
        )
    if relative is None:
        relative = {"out_kph": 0.0, "cross_kph": 0.0,
                    "speed_kph": max(0.0, _num(weather.get("wind_kph"), 0.0) or 0.0),
                    "source": "direction_unavailable_neutral"}

    gust = max(0.0, _num(weather.get("wind_gust_kph"), 0.0) or 0.0)
    speed = max(0.0, _num(relative.get("speed_kph"), 0.0) or 0.0)
    gust_multiplier = 1.0
    if gust > speed and speed > 0:
        gust_multiplier = min(1.20, 1.0+.15*(gust-speed)/max(10.0, speed))
    out_wind = (_num(relative.get("out_kph"), 0.0) or 0.0)*gust_multiplier
    cross_wind = (_num(relative.get("cross_kph"), 0.0) or 0.0)*gust_multiplier

    temp = _num(weather.get("temperature_c"), 20.0)
    humidity = _num(weather.get("humidity_pct"), 55.0)
    pressure = _num(weather.get("surface_pressure_hpa"), 1013.25)
    density = _air_density_kg_m3(temp, humidity, pressure)
    baseline_density = _air_density_kg_m3(20.0, 55.0, 1013.25)
    density_delta = 0.0 if density is None else (baseline_density-density)/baseline_density

    # Existing park factor already affects the baseline runs. Here it only scales
    # weather sensitivity, preventing double-counting the park itself.
    park_sensitivity = _clamp(1.0+1.6*(park-1.0), .82, 1.22)
    density_signal = _clamp(density_delta*.38, -.025, .030)*park_sensitivity
    wind_signal = _clamp(out_wind*.00095, -.035, .035)*park_sensitivity
    cross_signal = -min(.004, abs(cross_wind)*.00010)
    total_signal = _clamp(density_signal+wind_signal+cross_signal, -.055, .060)
    factor = v124._factor(1.0+total_signal, .945, 1.06)

    direction_coverage = 1.0 if relative.get("source") != "direction_unavailable_neutral" else .65
    atmosphere_coverage = 1.0 if weather.get("surface_pressure_hpa") is not None else .85
    coverage = min(direction_coverage, atmosphere_coverage)
    details.update({
        "air_density_kg_m3": density,
        "baseline_air_density_kg_m3": baseline_density,
        "air_density_delta": density_delta,
        "park_sensitivity": park_sensitivity,
        "wind": {**relative, "gust_kph": gust, "gust_multiplier": gust_multiplier,
                 "effective_out_kph": out_wind, "effective_cross_kph": cross_wind},
        "density_signal": density_signal,
        "wind_signal": wind_signal,
        "crosswind_signal": cross_signal,
        "total_weather_signal": total_signal,
        "factor": factor,
        "direction_policy": "MLB field-relative wind preferred; MLB venue azimuth + meteorological wind-vector fallback",
    })
    out.update({"home_factor": factor, "away_factor": factor, "coverage": coverage,
                "status": "ACTIVE", "details": details})
    return out


def install():
    from . import predictive_v124 as v124
    v124.weather_park_module = _weather_module
    original_report = v124.implementation_report

    def implementation_report(modules=None):
        report = original_report(modules)
        report["6_weather_park_interaction"] = {
            "status": "ADDED",
            "runtime": ((modules or {}).get("weather_park") or {}).get("status"),
            "note": "air density + field-relative wind + MLB venue azimuth fallback + roof-state safety; no fabricated field bearing",
        }
        return report

    v124.implementation_report = implementation_report
    v124.WEATHER_IMPLEMENTATION_VERSION = WEATHER_VERSION
    return True
