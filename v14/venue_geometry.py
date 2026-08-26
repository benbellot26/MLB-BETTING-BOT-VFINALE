from __future__ import annotations

"""Authoritative MLB venue geometry for V14 weather research.

The MLB Stats API exposes a venue ``location.azimuthAngle`` field. V14 uses
that value as the home-plate-to-outfield bearing required to resolve wind into
an outfield component. Geometry is reference data only: it never changes the
champion directly and failures remain fail-soft/explicitly unavailable.
"""

from datetime import datetime, timezone
import math
from typing import Any, Callable

from .acquisition import http_json

MLB_VENUE_URL = "https://statsapi.mlb.com/api/v1/venues/{venue_id}"
MLB_VENUES_URL = "https://statsapi.mlb.com/api/v1/venues"
ROLE = "SHADOW_ONLY"
Getter = Callable[[str, dict[str, Any]], Any]


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _base(status: str, venue_id: Any = None, reason: str | None = None) -> dict[str, Any]:
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


def _venue_from_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    data = payload if isinstance(payload, dict) else {}
    venues = data.get("venues") or []
    if venues and isinstance(venues[0], dict):
        return venues[0]
    venue = data.get("venue")
    return venue if isinstance(venue, dict) else None


def parse_venue(venue: dict[str, Any] | None, venue_id: Any = None) -> dict[str, Any]:
    if not isinstance(venue, dict):
        return _base("UNAVAILABLE", venue_id, "MLB venue payload missing venue")
    location = venue.get("location") or {}
    coordinates = location.get("defaultCoordinates") or {}
    azimuth = _num(location.get("azimuthAngle"))
    common = {
        "venue_name": venue.get("name"),
        "latitude": _num(coordinates.get("latitude")),
        "longitude": _num(coordinates.get("longitude")),
        "elevation_ft": _num(location.get("elevation")),
        "source": "MLB Stats API venue.location",
    }
    if azimuth is None:
        return {**_base("COLLECTING", venue.get("id") or venue_id, "MLB venue location.azimuthAngle unavailable"), **common}
    if not 0.0 <= azimuth < 360.0:
        return {**_base("UNAVAILABLE", venue.get("id") or venue_id, "MLB venue azimuthAngle outside [0,360)"), **common, "raw_azimuth_angle": azimuth}
    return {
        **_base("READY_SHADOW", venue.get("id") or venue_id),
        **common,
        "outfield_bearing_deg": azimuth,
        "source": "MLB Stats API venue.location.azimuthAngle",
        "source_semantics": "MLB field orientation azimuth in degrees; used as home-plate-to-outfield bearing",
        "no_imputation": True,
    }


def parse(payload: dict[str, Any] | None, venue_id: Any) -> dict[str, Any]:
    return parse_venue(_venue_from_payload(payload), venue_id)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a1, o1, a2, o2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((a2-a1)/2)**2 + math.cos(a1)*math.cos(a2)*math.sin((o2-o1)/2)**2
    return 12742.0 * math.asin(min(1.0, math.sqrt(h)))


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


def fetch_nearest(latitude: float, longitude: float, *, season: int, getter: Getter = http_json, max_distance_km: float = 15.0, retrieved_at: str | None = None) -> dict[str, Any]:
    """Resolve the actual current MLB venue nearest a known game coordinate.

    Geometry is keyed to the place, not the team name, so temporary homes do
    not silently inherit the bearing of an obsolete stadium.
    """
    lat = _num(latitude); lon = _num(longitude)
    if lat is None or lon is None:
        return _base("COLLECTING", reason="venue coordinates unavailable")
    params = {"sportIds": 1, "season": int(season), "hydrate": "location"}
    try:
        payload = getter(MLB_VENUES_URL, params) or {}
    except Exception as exc:
        return _base("UNAVAILABLE", reason=f"MLB venue catalogue fetch failed: {type(exc).__name__}: {exc}")
    candidates = []
    for venue in payload.get("venues") or []:
        row = parse_venue(venue)
        rlat = _num(row.get("latitude")); rlon = _num(row.get("longitude"))
        if rlat is None or rlon is None:
            continue
        candidates.append((_distance_km(lat, lon, rlat, rlon), row))
    if not candidates:
        return _base("UNAVAILABLE", reason="MLB venue catalogue contains no geocoded venues")
    distance, out = min(candidates, key=lambda item: item[0])
    if distance > float(max_distance_km):
        return {**_base("UNAVAILABLE", reason="nearest MLB venue is outside coordinate tolerance"), "nearest_distance_km": distance}
    out = dict(out)
    out["nearest_distance_km"] = distance
    out["retrieved_at"] = retrieved_at or datetime.now(timezone.utc).isoformat()
    out["request"] = {"url": MLB_VENUES_URL, **params}
    out["resolution_method"] = "nearest current-season MLB venue to game-weather coordinates"
    return out
