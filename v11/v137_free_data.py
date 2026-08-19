from __future__ import annotations

import csv
import io
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from . import core
from . import predictive_v124 as v124

VERSION = "13.7-free-data-foundation-v1"
COHORT = "HISTORICAL_RECONSTRUCTED_FREE"
WEATHER_ARCHIVE_START = date(2024, 3, 14)
DEFAULT_WEATHER_PUBLICATION_LAG_HOURS = 6
STATCAST_MAX_CHUNK_DAYS = 7

WEATHER_HOURLY = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,surface_pressure,"
    "precipitation_probability,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
)


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = core.parse_dt(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def safe_ecmwf_run(as_of: Any, publication_lag_hours: int = DEFAULT_WEATHER_PUBLICATION_LAG_HOURS) -> datetime:
    """Latest 00/06/12/18 UTC ECMWF run that is safely public by ``as_of``.

    Open-Meteo documents that global model runs are typically distributed 4-6h
    after initialization. We use the conservative 6h edge so a reconstructed
    feature cannot accidentally use a run that was still computing at decision
    time.
    """
    dt = _utc(as_of) - timedelta(hours=max(0, int(publication_lag_hours)))
    cycle = (dt.hour // 6) * 6
    return dt.replace(hour=cycle, minute=0, second=0, microsecond=0)


def weather_run_is_point_in_time(run: Any, as_of: Any, publication_lag_hours: int = DEFAULT_WEATHER_PUBLICATION_LAG_HOURS) -> bool:
    return _utc(run) + timedelta(hours=max(0, int(publication_lag_hours))) <= _utc(as_of)


def _hourly_value(hourly: dict[str, Any], name: str, idx: int) -> Any:
    values = hourly.get(name) or []
    return values[idx] if idx < len(values) else None


def weather_from_single_run_payload(
    payload: dict[str, Any],
    game_time: Any,
    run: Any,
    as_of: Any,
    publication_lag_hours: int = DEFAULT_WEATHER_PUBLICATION_LAG_HOURS,
) -> dict[str, Any]:
    """Extract the game-hour forecast and carry explicit PIT provenance."""
    game_dt = _utc(game_time)
    run_dt = _utc(run)
    asof_dt = _utc(as_of)
    if not weather_run_is_point_in_time(run_dt, asof_dt, publication_lag_hours):
        return {
            "available": False,
            "point_in_time": False,
            "reason": "weather_run_not_public_by_as_of",
            "forecast_run": run_dt.isoformat(),
            "as_of": asof_dt.isoformat(),
        }
    hourly = (payload or {}).get("hourly") or {}
    raw_times = hourly.get("time") or []
    if not raw_times:
        return {"available": False, "point_in_time": True, "reason": "single_run_hourly_missing"}
    parsed: list[datetime] = []
    for value in raw_times:
        dt = datetime.fromisoformat(str(value))
        parsed.append(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc))
    idx = min(range(len(parsed)), key=lambda i: abs((parsed[i] - game_dt).total_seconds()))
    if abs((parsed[idx] - game_dt).total_seconds()) > 90 * 60:
        return {
            "available": False,
            "point_in_time": True,
            "reason": "single_run_does_not_cover_game_hour",
            "forecast_run": run_dt.isoformat(),
            "as_of": asof_dt.isoformat(),
        }
    return {
        "available": True,
        "point_in_time": True,
        "cohort": COHORT,
        "provider": "Open-Meteo Single Runs / ECMWF IFS",
        "forecast_run": run_dt.isoformat(),
        "assumed_publication_lag_hours": int(publication_lag_hours),
        "as_of": asof_dt.isoformat(),
        "valid_hour": parsed[idx].isoformat(),
        "temperature_c": _num(_hourly_value(hourly, "temperature_2m", idx)),
        "humidity_pct": _num(_hourly_value(hourly, "relative_humidity_2m", idx)),
        "dew_point_c": _num(_hourly_value(hourly, "dew_point_2m", idx)),
        "surface_pressure_hpa": _num(_hourly_value(hourly, "surface_pressure", idx)),
        "precip_probability": _num(_hourly_value(hourly, "precipitation_probability", idx)),
        "cloud_cover_pct": _num(_hourly_value(hourly, "cloud_cover", idx)),
        "wind_kph": _num(_hourly_value(hourly, "wind_speed_10m", idx)),
        "wind_direction_deg": _num(_hourly_value(hourly, "wind_direction_10m", idx)),
        "wind_gust_kph": _num(_hourly_value(hourly, "wind_gusts_10m", idx)),
    }


def historical_weather_for_game(
    game_time: Any,
    home_name: str,
    as_of: Any,
    fetch_json: Callable[..., dict[str, Any] | None] | None = None,
    publication_lag_hours: int = DEFAULT_WEATHER_PUBLICATION_LAG_HOURS,
) -> dict[str, Any]:
    """Retrieve an archived forecast that was conservatively available at ``as_of``."""
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
    params = {
        "latitude": coord[0],
        "longitude": coord[1],
        "timezone": "UTC",
        "hourly": WEATHER_HOURLY,
        "models": "ecmwf_ifs",
        "run": run.strftime("%Y-%m-%dT%H:%M"),
        "start_date": game_dt.date().isoformat(),
        "end_date": game_dt.date().isoformat(),
    }
    try:
        payload = fetch_json("https://single-runs-api.open-meteo.com/v1/forecast", params) or {}
        out = weather_from_single_run_payload(payload, game_dt, run, asof_dt, publication_lag_hours)
        out["request_model"] = "ecmwf_ifs"
        return out
    except Exception as exc:
        return {
            "available": False,
            "point_in_time": True,
            "reason": f"single_run_error:{type(exc).__name__}",
            "forecast_run": run.isoformat(),
            "as_of": asof_dt.isoformat(),
        }


def statcast_query_params(start_day: str, end_day: str, season: int | None = None) -> dict[str, Any]:
    """Bounded pitch-level request; caller must keep windows <= 7 calendar days."""
    s = date.fromisoformat(start_day)
    e = date.fromisoformat(end_day)
    if e < s:
        raise ValueError("statcast end_day before start_day")
    if (e - s).days + 1 > STATCAST_MAX_CHUNK_DAYS:
        raise ValueError("statcast query window exceeds seven days")
    season = int(season or e.year)
    return {
        "all": "true",
        "type": "details",
        "player_type": "pitcher",
        "game_date_gt": start_day,
        "game_date_lt": end_day,
        "hfGT": "R|",
        "hfSea": f"{season}|",
        "min_pas": 0,
        "min_pitches": 0,
        "min_results": 0,
    }


def fetch_statcast_rows(
    start_day: str,
    end_day: str,
    fetch_text: Callable[..., str] | None = None,
    season: int | None = None,
) -> list[dict[str, str]]:
    """Fetch a bounded free Statcast CSV window and return pitch rows."""
    fetch_text = fetch_text or v124._http_text
    params = statcast_query_params(start_day, end_day, season)
    text = fetch_text("https://baseballsavant.mlb.com/statcast_search/csv", params, timeout=45)
    rows = list(csv.DictReader(io.StringIO(text or "")))
    if rows and not {"game_date", "batter", "pitcher"}.issubset({str(k) for k in rows[0].keys()}):
        raise ValueError("unexpected Statcast CSV schema")
    return rows


def _event(row: dict[str, Any]) -> str:
    return str(row.get("events") or "").strip().lower()


def _pitch_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row.get(k) or "")
        for k in ("game_pk", "at_bat_number", "pitch_number", "batter", "pitcher", "game_date")
    )


def dedupe_statcast_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    out = []
    for row in rows:
        key = _pitch_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _empty_stat() -> dict[str, Any]:
    return {
        "pitches": 0,
        "pa": 0,
        "strikeouts": 0,
        "walks": 0,
        "xwoba_sum": 0.0,
        "xwoba_n": 0,
        "ev_sum": 0.0,
        "ev_n": 0,
        "hard_hit": 0,
        "barrels": 0,
        "velocity_sum": 0.0,
        "velocity_n": 0,
        "pitch_types": Counter(),
        "max_game_date": None,
    }


def _consume_common(stat: dict[str, Any], row: dict[str, Any]) -> None:
    stat["pitches"] += 1
    gd = str(row.get("game_date") or "")
    if gd and (not stat["max_game_date"] or gd > stat["max_game_date"]):
        stat["max_game_date"] = gd
    event = _event(row)
    if event:
        stat["pa"] += 1
        if event.startswith("strikeout"):
            stat["strikeouts"] += 1
        if event in {"walk", "intent_walk", "intentional_walk"}:
            stat["walks"] += 1
    xwoba = _num(row.get("estimated_woba_using_speedangle"))
    if xwoba is not None and 0.0 <= xwoba <= 1.0:
        stat["xwoba_sum"] += xwoba
        stat["xwoba_n"] += 1
    ev = _num(row.get("launch_speed"))
    if ev is not None and 20.0 <= ev <= 130.0:
        stat["ev_sum"] += ev
        stat["ev_n"] += 1
        if ev >= 95.0:
            stat["hard_hit"] += 1
        if str(row.get("launch_speed_angle") or "").strip() == "6":
            stat["barrels"] += 1


def _finalize_stat(stat: dict[str, Any], include_pitching: bool = False) -> dict[str, Any]:
    pa = int(stat["pa"])
    ev_n = int(stat["ev_n"])
    out = {
        "pitches": int(stat["pitches"]),
        "pa": pa,
        "k_rate": stat["strikeouts"] / pa if pa else None,
        "bb_rate": stat["walks"] / pa if pa else None,
        "k_minus_bb_rate": (stat["strikeouts"] - stat["walks"]) / pa if pa else None,
        "xwoba": stat["xwoba_sum"] / stat["xwoba_n"] if stat["xwoba_n"] else None,
        "xwoba_batted_balls": int(stat["xwoba_n"]),
        "avg_exit_velocity": stat["ev_sum"] / ev_n if ev_n else None,
        "hard_hit_rate": stat["hard_hit"] / ev_n if ev_n else None,
        "barrel_rate": stat["barrels"] / ev_n if ev_n else None,
        "batted_balls": ev_n,
        "max_game_date": stat["max_game_date"],
    }
    if include_pitching:
        mix = stat["pitch_types"]
        total = sum(mix.values())
        out["avg_release_speed"] = stat["velocity_sum"] / stat["velocity_n"] if stat["velocity_n"] else None
        out["velocity_pitches"] = int(stat["velocity_n"])
        out["pitch_mix"] = {k: v / total for k, v in sorted(mix.items())} if total else {}
    return out


def aggregate_statcast_priors(rows: list[dict[str, Any]], cutoff_day: str) -> dict[str, Any]:
    """Aggregate only pitches strictly before ``cutoff_day`` and key by MLB IDs.

    This intentionally has no name fallback. Stable MLB batter/pitcher IDs are
    part of Baseball Savant's CSV contract and are the only join keys exposed.
    """
    cutoff = date.fromisoformat(cutoff_day)
    hitters: dict[str, dict[str, Any]] = defaultdict(_empty_stat)
    pitchers: dict[str, dict[str, Any]] = defaultdict(_empty_stat)
    accepted = rejected_future = rejected_bad_date = 0
    for row in dedupe_statcast_rows(rows):
        try:
            gd = date.fromisoformat(str(row.get("game_date") or ""))
        except Exception:
            rejected_bad_date += 1
            continue
        if gd >= cutoff:
            rejected_future += 1
            continue
        batter = str(row.get("batter") or "").strip()
        pitcher = str(row.get("pitcher") or "").strip()
        if batter.isdigit():
            _consume_common(hitters[batter], row)
        if pitcher.isdigit():
            p = pitchers[pitcher]
            _consume_common(p, row)
            velo = _num(row.get("release_speed"))
            if velo is not None and 40.0 <= velo <= 110.0:
                p["velocity_sum"] += velo
                p["velocity_n"] += 1
            ptype = str(row.get("pitch_type") or "").strip()
            if ptype:
                p["pitch_types"][ptype] += 1
        accepted += 1
    return {
        "schema": "v13-7-statcast-id-priors-v1",
        "cohort": COHORT,
        "cutoff_day": cutoff_day,
        "point_in_time": True,
        "stable_id_only": True,
        "source": "Baseball Savant Statcast Search CSV",
        "hitters": {pid: _finalize_stat(s) for pid, s in sorted(hitters.items())},
        "pitchers": {pid: _finalize_stat(s, include_pitching=True) for pid, s in sorted(pitchers.items())},
        "diagnostics": {
            "accepted_pitch_rows": accepted,
            "rejected_at_or_after_cutoff": rejected_future,
            "rejected_bad_game_date": rejected_bad_date,
        },
    }


def reconstructed_feature_envelope(
    *,
    game_pk: Any,
    game_time: Any,
    as_of: Any,
    home: str,
    away: str,
    home_id: Any = None,
    away_id: Any = None,
    features: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Leakage-explicit research envelope; never counted as native evidence."""
    asof_dt, game_dt = _utc(as_of), _utc(game_time)
    if asof_dt >= game_dt:
        raise ValueError("historical reconstructed feature must be pregame")
    return {
        "schema": "v13-7-free-reconstructed-feature-v1",
        "cohort": COHORT,
        "native_live": False,
        "promotion_eligible": False,
        "game_pk": game_pk,
        "game_date": game_dt.isoformat(),
        "as_of": asof_dt.isoformat(),
        "home": home,
        "away": away,
        "home_id": home_id,
        "away_id": away_id,
        "features": features or {},
        "feature_provenance": provenance or {},
        "target_labels_embedded": False,
        "market_data_embedded": False,
        "claim": "research-only free-data reconstruction; cannot satisfy native-live promotion thresholds",
    }
