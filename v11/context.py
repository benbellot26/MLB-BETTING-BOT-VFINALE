from __future__ import annotations

from datetime import datetime, timedelta, timezone
from . import core

_WEATHER_CACHE = {}
_BP_CACHE = {}


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def weather_for_game(game, home_name):
    coord = core.COORD.get(home_name)
    if not coord:
        return {"available": False, "reason": "park_coordinates_missing"}
    try:
        game_dt = core.parse_dt(game.get("gameDate"))
    except Exception:
        return {"available": False, "reason": "game_time_missing"}
    key = (home_name, game_dt.strftime("%Y-%m-%dT%H"))
    if key in _WEATHER_CACHE:
        return _WEATHER_CACHE[key]
    params = {
        "latitude": coord[0], "longitude": coord[1], "timezone": "UTC",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,wind_speed_10m,wind_direction_10m",
        "start_date": game_dt.date().isoformat(), "end_date": game_dt.date().isoformat(),
    }
    try:
        d = core.http_json("https://api.open-meteo.com/v1/forecast", params) or {}
        h = d.get("hourly") or {}
        times = h.get("time") or []
        if not times:
            raise ValueError("no hourly weather")
        target = game_dt.replace(minute=0, second=0, microsecond=0)
        parsed = [datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc) if datetime.fromisoformat(str(t)).tzinfo is None else datetime.fromisoformat(str(t)).astimezone(timezone.utc) for t in times]
        i = min(range(len(parsed)), key=lambda j: abs((parsed[j]-target).total_seconds()))
        out = {
            "available": True,
            "temperature_c": _num((h.get("temperature_2m") or [None])[i], None),
            "humidity_pct": _num((h.get("relative_humidity_2m") or [None])[i], None),
            "precip_probability": _num((h.get("precipitation_probability") or [None])[i], None),
            "wind_kph": _num((h.get("wind_speed_10m") or [None])[i], None),
            "wind_direction_deg": _num((h.get("wind_direction_10m") or [None])[i], None),
            "observed_hour": times[i],
        }
    except Exception as e:
        out = {"available": False, "reason": f"weather_error:{type(e).__name__}"}
    _WEATHER_CACHE[key] = out
    return out


def bullpen_state(team_id, target_date):
    """Aggregate recent reliever workload over the previous three days.

    This is intentionally availability-focused. Reliever talent is represented by
    season ERA/WHIP of the pitchers actually used, with league-average fallbacks.
    """
    key = (str(team_id), str(target_date))
    if key in _BP_CACHE:
        return _BP_CACHE[key]
    try:
        from datetime import date
        d0 = date.fromisoformat(str(target_date))
    except Exception:
        return {"coverage": 0.0, "reason": "bad_date"}
    pitcher_usage = {}
    games_seen = 0
    for back in (1, 2, 3):
        day = (d0 - timedelta(days=back)).isoformat()
        try:
            games = core.mlb_schedule(day, team_id=team_id, hydrate="linescore")
        except Exception:
            continue
        finals = [g for g in games if str((g.get("status") or {}).get("abstractGameState") or "").lower() == "final"]
        for g in finals:
            games_seen += 1
            try:
                box = core.mlb(f"v1/game/{g.get('gamePk')}/boxscore") or {}
            except Exception:
                continue
            team = None
            for side in ("home", "away"):
                t = (box.get("teams") or {}).get(side) or {}
                if str((t.get("team") or {}).get("id") or "") == str(team_id):
                    team = t
                    break
            if not team:
                continue
            ids = list(team.get("pitchers") or [])
            relievers = ids[1:] if len(ids) > 1 else []
            players = team.get("players") or {}
            for pid in relievers:
                p = players.get(f"ID{pid}") or {}
                st = ((p.get("stats") or {}).get("pitching") or {})
                pitches = int(_num(st.get("pitchesThrown")))
                entry = pitcher_usage.setdefault(str(pid), {"id": pid, "name": (p.get("person") or {}).get("fullName"), "pitches_3d": 0, "days_used": 0})
                entry["pitches_3d"] += pitches
                entry["days_used"] += 1
    weighted_era = []
    weighted_whip = []
    for p in pitcher_usage.values():
        st = core.player_stats(p["id"], "pitching")
        if st:
            weighted_era.append(_num(st.get("era"), 4.35))
            weighted_whip.append(_num(st.get("whip"), 1.32))
    unavailable = sum(p["pitches_3d"] >= 45 or p["days_used"] >= 3 for p in pitcher_usage.values())
    taxed = sum(p["pitches_3d"] >= 25 or p["days_used"] >= 2 for p in pitcher_usage.values())
    out = {
        "coverage": min(1.0, games_seen / 3.0),
        "games_seen": games_seen,
        "relievers_seen": len(pitcher_usage),
        "taxed_relievers": taxed,
        "likely_unavailable_relievers": unavailable,
        "recent_reliever_era": sum(weighted_era)/len(weighted_era) if weighted_era else None,
        "recent_reliever_whip": sum(weighted_whip)/len(weighted_whip) if weighted_whip else None,
        "relievers": list(pitcher_usage.values()),
    }
    _BP_CACHE[key] = out
    return out
