from __future__ import annotations

"""DST-aware timezone evidence for Pulsar V14 operational research.

The champion still consumes the legacy longitude approximation for parity. This
module supplies exact IANA-zone offsets as a shadow covariate so a future OOS
challenger can replace the approximation only if it proves useful.
"""

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

ROLE = "CHALLENGER_ONLY"

TEAM_TIMEZONE = {
    "Arizona Diamondbacks": "America/Phoenix",
    "Athletics": "America/Los_Angeles",
    "Atlanta Braves": "America/New_York",
    "Baltimore Orioles": "America/New_York",
    "Boston Red Sox": "America/New_York",
    "Chicago White Sox": "America/Chicago",
    "Chicago Cubs": "America/Chicago",
    "Cincinnati Reds": "America/New_York",
    "Cleveland Guardians": "America/New_York",
    "Colorado Rockies": "America/Denver",
    "Detroit Tigers": "America/New_York",
    "Houston Astros": "America/Chicago",
    "Kansas City Royals": "America/Chicago",
    "Los Angeles Angels": "America/Los_Angeles",
    "Los Angeles Dodgers": "America/Los_Angeles",
    "Miami Marlins": "America/New_York",
    "Milwaukee Brewers": "America/Chicago",
    "Minnesota Twins": "America/Chicago",
    "New York Mets": "America/New_York",
    "New York Yankees": "America/New_York",
    "Philadelphia Phillies": "America/New_York",
    "Pittsburgh Pirates": "America/New_York",
    "San Diego Padres": "America/Los_Angeles",
    "San Francisco Giants": "America/Los_Angeles",
    "Seattle Mariners": "America/Los_Angeles",
    "St. Louis Cardinals": "America/Chicago",
    "Tampa Bay Rays": "America/New_York",
    "Texas Rangers": "America/Chicago",
    "Toronto Blue Jays": "America/Toronto",
    "Washington Nationals": "America/New_York",
}


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_offset_hours(team: str, at: Any) -> float | None:
    zone_name = TEAM_TIMEZONE.get(str(team))
    if not zone_name:
        return None
    local = _utc(at).astimezone(ZoneInfo(zone_name))
    offset = local.utcoffset()
    return offset.total_seconds() / 3600.0 if offset is not None else None


def timezone_shift_hours(previous_home_team: str | None, current_home_team: str | None, at: Any) -> dict[str, Any]:
    previous = utc_offset_hours(str(previous_home_team or ""), at)
    current = utc_offset_hours(str(current_home_team or ""), at)
    if previous is None or current is None:
        return {
            "schema": "pulsar-v14-timezone-challenger-v1",
            "role": ROLE,
            "status": "COLLECTING",
            "auto_activation": False,
            "shift_hours": None,
            "reason": "IANA timezone mapping unavailable",
        }
    return {
        "schema": "pulsar-v14-timezone-challenger-v1",
        "role": ROLE,
        "status": "READY_SHADOW",
        "auto_activation": False,
        "previous_utc_offset_hours": previous,
        "current_utc_offset_hours": current,
        "shift_hours": current - previous,
        "dst_aware": True,
        "market_probability_used_as_feature": False,
    }
