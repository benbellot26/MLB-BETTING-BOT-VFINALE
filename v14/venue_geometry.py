from __future__ import annotations

"""Authoritative and sourced MLB venue geometry for V14 weather research.

The MLB Stats API is the primary source and exposes a venue
``location.azimuthAngle`` for almost every MLB venue. A very small set of
special/temporary 2026 venues omit that field. Those venues are covered by a
strict, venue-id keyed secondary reference registry whose orientation is
published explicitly as a cardinal direction. Cardinal references are stored
with their full ±22.5 degree uncertainty; they are never presented as survey-
grade bearings or allowed to alter the champion automatically.
"""

from datetime import datetime, timezone
import math
from typing import Any, Callable

from .acquisition import http_json

MLB_VENUE_URL = "https://statsapi.mlb.com/api/v1/venues/{venue_id}"
MLB_VENUES_URL = "https://statsapi.mlb.com/api/v1/venues"
ROLE = "SHADOW_ONLY"
Getter = Callable[[str, dict[str, Any]], Any]

# MLB 2026 scheduled venues for which Stats API currently omits azimuthAngle.
# These are explicit published cardinal orientations, not inferred from game
# outcomes, betting markets, or a hand-drawn map. Keeping them keyed by MLB
# venue id prevents a special-event park from inheriting a team's normal park.
SECONDARY_CARDINAL_ORIENTATION: dict[str, dict[str, Any]] = {
    "2735": {
        "venue_name": "Journey Bank Ballpark at Historic Bowman Field",
        "cardinal": "NE",
        "bearing_deg": 45.0,
        "source_url": "https://www.andrewclem.com/Baseball/BowmanField.html",
        "source_evidence": "Clem's Baseball stadium table lists CF orientation as NE.",
    },
    "5340": {
        "venue_name": "Estadio Alfredo Harp Helu",
        "cardinal": "SE",
        "bearing_deg": 135.0,
        "source_url": "https://www.eleconomista.com.mx/deportes/El-desafio-de-construir-un-parque-de-3000-millones-20190321-0108.html",
        "source_evidence": "Construction report states the stadium infrastructure orientation was changed to southeast under MLB/Populous supervision.",
        # Stats API currently omits coordinates for this venue. These are the
        # mapped coordinates of the baseball pitch itself (OSM way 828705073).
        "latitude": 19.40333,
        "longitude": -99.08510,
        "coordinate_source_url": "https://mapcarta.com/W828705073",
        "coordinate_source_evidence": "OpenStreetMap baseball pitch El Diamante de Fuego (way 828705073).",
    },
    "5355": {
        "venue_name": "Las Vegas Ballpark",
        "cardinal": "NE",
        "bearing_deg": 45.0,
        "source_url": "https://baseballparks.com/indepth/vegas/",
        "source_evidence": "BaseballParks.com ballpark profile explicitly lists 'Field points: Northeast'.",
    },
    "5445": {
        "venue_name": "Field of Dreams",
        "cardinal": "NE",
        "bearing_deg": 45.0,
        "source_url": "https://www.linkedin.com/posts/populous_today-wouldve-marked-the-first-time-two-activity-6699646312180142081-DuX9",
        "source_evidence": "Populous states the MLB field geometry has a northeast orientation.",
        "corroboration_url": "https://www.brightview.com/resources/press-release/brightview-returns-field-dreams-iconic-ballpark-enters-new-era",
        "corroboration_evidence": "BrightView's 2026 release states it built this playing field in 2019, has maintained it for every MLB game there, and the permanent venue retains that playing surface while adding permanent amenities.",
    },
}


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _base(status: str, venue_id: Any = None, reason: str | None = None) -> dict[str, Any]:
    out = {
        "schema": "pulsar-v14-venue-geometry-v2",
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


def _secondary_cardinal(venue_id: Any, common: dict[str, Any]) -> dict[str, Any] | None:
    ref = SECONDARY_CARDINAL_ORIENTATION.get(str(venue_id or ""))
    if not ref:
        return None
    bearing = _num(ref.get("bearing_deg"))
    if bearing is None or not 0.0 <= bearing < 360.0:
        return None
    latitude = common.get("latitude")
    longitude = common.get("longitude")
    if latitude is None:
        latitude = _num(ref.get("latitude"))
    if longitude is None:
        longitude = _num(ref.get("longitude"))
    out = {
        **_base("READY_SHADOW", venue_id),
        **common,
        "venue_name": common.get("venue_name") or ref.get("venue_name"),
        "latitude": latitude,
        "longitude": longitude,
        "outfield_bearing_deg": bearing,
        "bearing_cardinal": ref.get("cardinal"),
        "bearing_precision": "CARDINAL",
        "bearing_uncertainty_deg": 22.5,
        "source_tier": "SECONDARY_PUBLISHED_REFERENCE",
        "source": "published cardinal field-orientation reference",
        "source_url": ref.get("source_url"),
        "source_evidence": ref.get("source_evidence"),
        "no_imputation": True,
        "promotion_ready": False,
        "promotion_blocker": "cardinal bearing has ±22.5 degree directional uncertainty; shadow evidence only",
    }
    for key in ("corroboration_url", "corroboration_evidence", "coordinate_source_url", "coordinate_source_evidence"):
        if ref.get(key):
            out[key] = ref[key]
    return out


def parse_venue(venue: dict[str, Any] | None, venue_id: Any = None) -> dict[str, Any]:
    if not isinstance(venue, dict):
        secondary = _secondary_cardinal(venue_id, {"venue_name": None, "latitude": None, "longitude": None, "elevation_ft": None})
        return secondary or _base("UNAVAILABLE", venue_id, "MLB venue payload missing venue")
    location = venue.get("location") or {}
    coordinates = location.get("defaultCoordinates") or {}
    resolved_id = venue.get("id") or venue_id
    azimuth = _num(location.get("azimuthAngle"))
    common = {
        "venue_name": venue.get("name"),
        "latitude": _num(coordinates.get("latitude")),
        "longitude": _num(coordinates.get("longitude")),
        "elevation_ft": _num(location.get("elevation")),
        "source": "MLB Stats API venue.location",
    }
    if azimuth is None:
        secondary = _secondary_cardinal(resolved_id, common)
        if secondary:
            secondary["primary_source_status"] = "MLB venue location.azimuthAngle unavailable"
            return secondary
        return {**_base("COLLECTING", resolved_id, "MLB venue location.azimuthAngle unavailable"), **common}
    if not 0.0 <= azimuth < 360.0:
        return {**_base("UNAVAILABLE", resolved_id, "MLB venue azimuthAngle outside [0,360)"), **common, "raw_azimuth_angle": azimuth}
    return {
        **_base("READY_SHADOW", resolved_id),
        **common,
        "outfield_bearing_deg": azimuth,
        "bearing_precision": "MLB_REPORTED_DEGREES",
        "bearing_uncertainty_deg": None,
        "source_tier": "OFFICIAL_MLB",
        "source": "MLB Stats API venue.location.azimuthAngle",
        "source_semantics": "MLB field orientation azimuth in degrees; used as home-plate-to-outfield bearing",
        "no_imputation": True,
        "promotion_ready": True,
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
