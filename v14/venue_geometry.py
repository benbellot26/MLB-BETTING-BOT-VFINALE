from __future__ import annotations

"""Authoritative MLB venue geometry for V14 weather research.

The MLB Stats API exposes a venue ``location.azimuthAngle`` field.  V14 uses
that value as the home-plate-to-outfield bearing required to resolve wind into
an outfield component.  Geometry is reference data only: it never changes the
champion directly and failures remain fail-soft/explicitly unavailable.
"""

from datetime import datetime, timezone
import math
from typing import Any, Callable

from .acquisition import http_json

MLB_VENUE_URL = "https://statsapi.mlb.com/api/v1/venues/{venue_id}"
ROLE = "SHADOW_ONLY"
Getter = Callable[[str, dict[str, Any]], Any]


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _base(status: str, venue_id: Any, reason: str | None = None) -> dict[str, Any]:
    out = {
        "schema": "pulsar-v14-venue-geometry-v1",
        "role": ROLE,
        "status": status,
        "auto_activation": False,
        "champion_impact": False,
        "market_probability_used_as_feature": False,
        "reference_data": True,
        "venue_id": str(venue_id or ""),
    }
    if reason:
        out["reason"] = reason
    return out


def parse(payload: dict[str, Any] | None, venue_id: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    venues = data.get("venues") or []
    venue = venues[0] if venues and isinstance(venues[0], dict) else data.get("venue")
    if not isinstance(venue, dict):
        return _base("UNAVAILABLE", venue_id, "MLB venue payload missing venue")

    location = venue.get("location") or {}
    coordinates = location.get("defaultCoordinates") or {}
    azimuth = _num(location.get("azimuthAngle"))
    if azimuth is None:
        return {
            **_base("COLLECTING", venue_id, "MLB venue location.azimuthAngle unavailable"),
            "venue_name": venue.get("name"),
            "source": "MLB Stats API venue.location",
        }
    if not 0.0 <= azimuth < 360.0:
        return {
            **_base("UNAVAILABLE", venue_id, "MLB venue azimuthAngle outside [0,360)"),
            "venue_name": venue.get("name"),
            "raw_azimuth_angle": azimuth,
            "source": "MLB Stats API venue.location",
        }

    latitude = _num(coordinates.get("latitude"))
    longitude = _num(coordinates.get("longitude"))
    elevation_ft = _num(location.get("elevation"))
    return {
        **_base("READY_SHADOW", venue.get("id") or venue_id),
        "venue_name": venue.get("name"),
        "outfield_bearing_deg": azimuth,
        "latitude": latitude,
        "longitude": longitude,
        "elevation_ft": elevation_ft,
        "source": "MLB Stats API venue.location.azimuthAngle",
        "source_semantics": "MLB field orientation azimuth in degrees; used as home-plate-to-outfield bearing",
        "no_imputation": True,
    }


def fetch(venue_id: Any, *, getter: Getter = http_json, retrieved_at: str | None = None) -> dict[str, Any]:
    if venue_id in (None, ""):
        return _base("COLLECTING", venue_id, "venue id unavailable")
    url = MLB_VENUE_URL.format(venue_id=venue_id)
    try:
        payload = getter(url, {"hydrate": "location"}) or {}
    except Exception as exc:
        return _base("UNAVAILABLE", venue_id, f"MLB venue fetch failed: {type(exc).__name__}: {exc}")
    out = parse(payload, venue_id)
    out["retrieved_at"] = retrieved_at or datetime.now(timezone.utc).isoformat()
    out["request"] = {"url": url, "hydrate": "location"}
    return out
