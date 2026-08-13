#!/usr/bin/env python3
"""V11.1.2 data-quality patch for the baseball shadow layer.

Keeps V11.1.1 intact for auditability while fixing three issues found by the
first live coverage run: hitter season-stat keying, bullpen contamination, and
field-oriented wind when the MLB feed only exposes compass wind degrees.
"""
from __future__ import annotations

import math
import re

import bot as core
import v11_baseball_shadow as base

SHADOW_VERSION = "11.1.2-baseball-shadow-v3"

# Home-plate -> center-field azimuths. Unknown parks remain non-directional
# rather than receiving a guessed angle.
FIELD_AZIMUTH = {
    "Detroit Tigers": 150.0,
    "Miami Marlins": 128.0,
    "Chicago White Sox": 127.0,
    "Toronto Blue Jays": 345.0,
    "Washington Nationals": 28.0,
    "Minnesota Twins": 129.0,
    "Los Angeles Angels": 43.61,
    "Los Angeles Dodgers": 28.0,
}

_old_recent_context = base._recent_context
_old_bullpen = base._bullpen
_old_weather = base._weather
_old_self_test = base.self_test


def _bstat(entry):
    """MLB boxscores store season batting production under `hitting`."""
    season = entry.get("seasonStats") or {}
    return season.get("hitting") or season.get("batting") or {}


def _is_rotation_profile(info):
    st = info.get("season") or {}
    gp = core.num(st.get("gamesPlayed", st.get("gamesPitched", 0)), 0)
    gs = core.num(st.get("gamesStarted"), 0)
    saves = core.num(st.get("saves"), 0)
    holds = core.num(st.get("holds"), 0)
    if gs < 4 or saves + holds > 0:
        return False
    if gp <= 0:
        return True
    return gs / max(gp, 1) >= .30


def _is_position_player_pitching_noise(info):
    st = info.get("season") or {}
    ip = base._innings(st.get("inningsPitched"))
    seen = core.num(info.get("seen"), 0)
    return ip < 3.0 and seen <= 1


def _recent_context(team_ids, target):
    ctx = _old_recent_context(team_ids, target)
    for team_ctx in ctx.values():
        relievers = team_ctx.get("relievers") or {}
        removed_position = 0
        removed_rotation = 0
        for pid, info in list(relievers.items()):
            if _is_position_player_pitching_noise(info):
                relievers.pop(pid, None)
                removed_position += 1
            elif _is_rotation_profile(info):
                relievers.pop(pid, None)
                removed_rotation += 1
        team_ctx["bullpen_filter"] = {
            "removed_position_player_noise": removed_position,
            "removed_rotation_profiles": removed_rotation,
            "remaining_candidates": len(relievers),
        }
    return ctx


def _bullpen(team_ctx, starter):
    out = _old_bullpen(team_ctx, starter)
    out["source"] = "recent-final-games-filtered-v112"
    out["filter"] = dict(team_ctx.get("bullpen_filter") or {})
    return out


def _parse_core_weather(text):
    if not text:
        return None
    m = re.search(r"vent\s+([0-9]+(?:[.,][0-9]+)?)\s*km/h\s*\(([0-9]+(?:[.,][0-9]+)?)°\)", str(text), re.I)
    if not m:
        return None
    speed_kmh = float(m.group(1).replace(",", "."))
    wind_from = float(m.group(2).replace(",", ".")) % 360.0
    return speed_kmh / 1.609344, wind_from


def _weather(home, game_time, feed):
    original = _old_weather(home, game_time, feed)
    if original.get("directional"):
        return original

    azimuth = FIELD_AZIMUTH.get(home)
    parsed = _parse_core_weather(original.get("base_text"))
    if azimuth is None or parsed is None:
        original["orientation_available"] = azimuth is not None
        original["source"] = "Open-Meteo-orientation-unavailable-v112"
        return original

    speed_mph, wind_from = parsed
    wind_to = (wind_from + 180.0) % 360.0
    diff = math.radians((wind_to - azimuth + 180.0) % 360.0 - 180.0)
    component = speed_mph * math.cos(diff)
    crosswind = speed_mph * math.sin(diff)
    delta = core.clamp(.025 * component, -.55, .55)

    cond = str((feed.get("gameData", {}).get("weather") or {}).get("condition") or "").lower()
    if home in getattr(core, "ROOF", set()) and "roof open" not in cond:
        delta *= .35
        roof_factor = .35
    else:
        roof_factor = 1.0

    label = "OUT" if component > 2.5 else ("IN" if component < -2.5 else "CROSS")
    return {
        "available": True,
        "directional": True,
        "indoor": False,
        "run_delta": round(delta, 4),
        "wind_mph": round(speed_mph, 2),
        "wind_from_deg": round(wind_from, 1),
        "field_azimuth_deg": round(azimuth, 2),
        "out_component": round(component, 2),
        "crosswind_mph": round(crosswind, 2),
        "direction": label,
        "roof_factor": roof_factor,
        "source": "Open-Meteo+field-azimuth-v112",
        "base_text": original.get("base_text"),
    }


def install():
    base.SHADOW_VERSION = SHADOW_VERSION
    base._bstat = _bstat
    base._recent_context = _recent_context
    base._bullpen = _bullpen
    base._weather = _weather


def self_test():
    install()
    assert _bstat({"seasonStats": {"hitting": {"ops": .901}}})["ops"] == .901
    assert _is_position_player_pitching_noise({"season": {"inningsPitched": "1.0"}, "seen": 1})
    assert _is_rotation_profile({"season": {"gamesPlayed": 20, "gamesStarted": 12, "saves": 0, "holds": 0}})
    assert not _is_rotation_profile({"season": {"gamesPlayed": 50, "gamesStarted": 1, "saves": 20, "holds": 0}})
    speed, deg = _parse_core_weather("28°C • vent 10 km/h (219°) • HR 62%")
    assert 6.1 < speed < 6.3 and deg == 219.0
    _old_self_test()
    print("SELF-TEST V11.1.2 DATA QUALITY OK")


def main():
    install()
    base.main()


if __name__ == "__main__":
    main()
