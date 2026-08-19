from __future__ import annotations

import urllib.error
from datetime import date, timedelta
from typing import Any, Callable

from . import core
from .v137_free_data import (
    DEFAULT_WEATHER_PUBLICATION_LAG_HOURS,
    WEATHER_ARCHIVE_START,
    WEATHER_HOURLY,
    _utc,
    safe_ecmwf_run,
    weather_from_single_run_payload,
)

SINGLE_RUN_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
SECONDARY_MODEL_ARCHIVE_START = date(2026, 4, 2)
PRIMARY_MODEL = "ecmwf_ifs"
SECONDARY_MODEL = "ecmwf_ifs025"

# Keep a reduced request profile for provider-schema regressions. All variables
# here are directly documented by Open-Meteo's ECMWF endpoint. Missing humidity
# remains neutral downstream rather than being invented.
REDUCED_WEATHER_HOURLY = (
    "temperature_2m,dew_point_2m,surface_pressure,precipitation,cloud_cover,"
    "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
)


def _models_for_run(run_date: date) -> list[str]:
    models = [PRIMARY_MODEL]
    if run_date >= SECONDARY_MODEL_ARCHIVE_START:
        models.append(SECONDARY_MODEL)
    return models


def _attempt(
    *,
    fetch_json: Callable[..., dict[str, Any] | None],
    coord: tuple[float, float],
    game_dt: Any,
    asof_dt: Any,
    run: Any,
    model: str,
    hourly: str,
    publication_lag_hours: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    params = {
        "latitude": coord[0],
        "longitude": coord[1],
        "timezone": "UTC",
        "hourly": hourly,
        "models": model,
        "run": run.strftime("%Y-%m-%dT%H:%M"),
        "start_date": game_dt.date().isoformat(),
        "end_date": game_dt.date().isoformat(),
    }
    profile = "full" if hourly == WEATHER_HOURLY else "reduced"
    diagnostic: dict[str, Any] = {"model": model, "profile": profile}
    try:
        payload = fetch_json(SINGLE_RUN_URL, params) or {}
        out = weather_from_single_run_payload(
            payload,
            game_dt,
            run,
            asof_dt,
            publication_lag_hours,
        )
        diagnostic["result"] = str(out.get("reason") or "available")
        if out.get("available"):
            out["request_model"] = model
            out["request_profile"] = profile
            return out, diagnostic
        return None, diagnostic
    except urllib.error.HTTPError as exc:
        diagnostic["result"] = f"HTTP_{int(exc.code)}"
        return None, diagnostic
    except Exception as exc:
        diagnostic["result"] = f"{type(exc).__name__}"
        return None, diagnostic


def historical_weather_for_game(
    game_time: Any,
    home_name: str,
    as_of: Any,
    fetch_json: Callable[..., dict[str, Any] | None] | None = None,
    publication_lag_hours: int = DEFAULT_WEATHER_PUBLICATION_LAG_HOURS,
) -> dict[str, Any]:
    """Retrieve a leakage-safe archived forecast with fail-closed fallbacks.

    The run initialisation time is fixed before any provider retry. Fallbacks may
    change the ECMWF resolution or request a smaller documented variable set,
    but never move to a newer run and therefore never improve the information
    set beyond what was available at ``as_of``.
    """
    fetch_json = fetch_json or core.http_json
    game_dt, asof_dt = _utc(game_time), _utc(as_of)
    if asof_dt >= game_dt:
        return {"available": False, "point_in_time": False, "reason": "analysis_not_pregame"}

    coord = core.COORD.get(home_name)
    if not coord:
        return {"available": False, "point_in_time": True, "reason": "park_coordinates_missing"}

    run = safe_ecmwf_run(asof_dt, publication_lag_hours)
    if run.date() < WEATHER_ARCHIVE_START:
        return {
            "available": False,
            "point_in_time": True,
            "reason": "ecmwf_single_run_archive_not_available",
            "archive_available_from": WEATHER_ARCHIVE_START.isoformat(),
        }

    attempts: list[dict[str, Any]] = []
    for model in _models_for_run(run.date()):
        for hourly in (WEATHER_HOURLY, REDUCED_WEATHER_HOURLY):
            out, diagnostic = _attempt(
                fetch_json=fetch_json,
                coord=coord,
                game_dt=game_dt,
                asof_dt=asof_dt,
                run=run,
                model=model,
                hourly=hourly,
                publication_lag_hours=publication_lag_hours,
            )
            attempts.append(diagnostic)
            if out is not None:
                out["provider_attempts"] = attempts
                out["fallback_used"] = len(attempts) > 1
                return out

    return {
        "available": False,
        "point_in_time": True,
        "reason": "single_run_all_provider_attempts_failed",
        "forecast_run": run.isoformat(),
        "as_of": asof_dt.isoformat(),
        "provider_attempts": attempts,
        "fallback_used": len(attempts) > 1,
    }
