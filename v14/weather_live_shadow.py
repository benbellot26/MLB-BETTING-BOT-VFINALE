from __future__ import annotations

"""Prospective, fail-soft weather enrichment for native V14.6 production.

Open-Meteo supplies the match forecast. MLB venue reference data supplies the
actual venue coordinates and field azimuth, and NASA POWER supplies the
venue/month climatological baseline. No value is imputed: unavailable reference
data stays neutral, and only strictly pregame evidence can enter V14.6.
"""

from datetime import datetime, timezone
import math
from typing import Any, Callable

from .acquisition import http_json, parse_time
from .venue_geometry import fetch as fetch_venue, fetch_nearest as fetch_nearest_venue
from .weather_climatology import fetch as fetch_climatology

URL="https://api.open-meteo.com/v1/forecast"
ROLE="PRODUCTION_ADVANCED_INPUT"
Getter=Callable[[str,dict[str,Any]],Any]


def _num(value:Any)->float|None:
    try:out=float(value)
    except Exception:return None
    return out if math.isfinite(out) else None


def _base(status:str,reason:str|None=None)->dict[str,Any]:
    out={"schema":"pulsar-v14-live-weather-shadow-v2","role":ROLE,"status":status,"auto_activation":False,"champion_impact":True,"activation_contract":"fixed by pulsar-v14-context-v4-all-stats; incomplete reference data is neutral","market_probability_used_as_feature":False,"point_in_time":True}
    if reason:out["reason"]=reason
    return out


def _reference_disabled(reason:str)->dict[str,Any]:
    return {"status":"COLLECTING","role":ROLE,"champion_impact":True,"reason":reason}


def fetch(latitude:float|None,longitude:float|None,*,game_date:str,analyzed_at:str,venue_id:Any|None=None,getter:Getter=http_json,reference_getter:Getter|None=None)->dict[str,Any]:
    try:game=parse_time(game_date);analysis=parse_time(analyzed_at)
    except Exception:return _base("COLLECTING","invalid game/analysis timestamp")
    if analysis>=game:return _base("COLLECTING","weather snapshot is not strictly pregame")

    # Native production resolves geometry before the forecast so temporary and
    # special-event venues use the actual ballpark coordinates. Injected test
    # getters remain network-isolated unless reference_getter is explicit.
    ref_getter=reference_getter
    if ref_getter is None and getter is http_json:ref_getter=http_json
    geometry=_reference_disabled("venue reference acquisition disabled for injected forecast getter")
    if ref_getter is not None:
        if venue_id not in (None,""):
            geometry=fetch_venue(venue_id,getter=ref_getter,retrieved_at=analysis.isoformat())
        elif latitude is not None and longitude is not None:
            geometry=fetch_nearest_venue(float(latitude),float(longitude),season=int(game.year),getter=ref_getter,retrieved_at=analysis.isoformat())
        else:
            geometry=_reference_disabled("venue id and fallback coordinates unavailable")

    forecast_lat=_num((geometry or {}).get("latitude")) if geometry.get("status")=="READY_SHADOW" else None
    forecast_lon=_num((geometry or {}).get("longitude")) if geometry.get("status")=="READY_SHADOW" else None
    if forecast_lat is None:forecast_lat=_num(latitude)
    if forecast_lon is None:forecast_lon=_num(longitude)
    if forecast_lat is None or forecast_lon is None:return {**_base("COLLECTING","venue coordinates unavailable"),"venue_geometry":geometry}

    params={"latitude":forecast_lat,"longitude":forecast_lon,"hourly":"temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m","temperature_unit":"fahrenheit","wind_speed_unit":"mph","timezone":"UTC","forecast_days":15}
    try:payload=getter(URL,params) or {}
    except Exception as exc:return {**_base("UNAVAILABLE",f"Open-Meteo fetch failed: {type(exc).__name__}: {exc}"),"venue_geometry":geometry}
    hourly=payload.get("hourly") or {};times=hourly.get("time") or []
    if not times:return {**_base("UNAVAILABLE","Open-Meteo hourly forecast unavailable"),"venue_geometry":geometry}
    candidates=[]
    for i,value in enumerate(times):
        try:dt=datetime.fromisoformat(str(value).replace("Z","+00:00"));dt=dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:continue
        candidates.append((abs((dt-game).total_seconds()),dt,i))
    if not candidates:return {**_base("UNAVAILABLE","Open-Meteo forecast timestamps invalid"),"venue_geometry":geometry}
    _,valid,i=min(candidates,key=lambda x:x[0])
    if abs((valid-game).total_seconds())>2*3600:return {**_base("UNAVAILABLE","no forecast hour close to first pitch"),"venue_geometry":geometry}
    def at(name:str)->float|None:
        values=hourly.get(name) or []
        return _num(values[i]) if i<len(values) else None
    values={"temperature_f":at("temperature_2m"),"humidity_pct":at("relative_humidity_2m"),"pressure_hpa":at("surface_pressure"),"wind_mph":at("wind_speed_10m"),"wind_direction_deg":at("wind_direction_10m")}
    missing=[k for k,v in values.items() if v is None]
    if missing:return {**_base("COLLECTING","physical forecast variables incomplete"),"missing":missing,"forecast_valid_time":valid.isoformat(),"venue_geometry":geometry}

    climatology=_reference_disabled("venue climatology unavailable until geometry is resolved")
    bearing=None;baseline_density=None;baseline_wind=None
    if geometry.get("status")=="READY_SHADOW" and geometry.get("outfield_bearing_deg") is not None and ref_getter is not None:
        bearing=float(geometry["outfield_bearing_deg"])
        climatology=fetch_climatology(forecast_lat,forecast_lon,month=int(game.month),outfield_bearing_deg=bearing,getter=ref_getter)
        if climatology.get("status")=="READY_SHADOW":
            baseline_density=_num(climatology.get("venue_baseline_density_kg_m3"));baseline_wind=_num(climatology.get("venue_baseline_wind_out_mph"))

    return {**_base("READY_SHADOW"),**values,"latitude":forecast_lat,"longitude":forecast_lon,"forecast_valid_time":valid.isoformat(),"analyzed_at":analysis.isoformat(),"forecast_lead_hours":(game-analysis).total_seconds()/3600,"source":"Open-Meteo generic forecast API","source_contract":"forecast retrieved prospectively at analysis; venue coordinates/azimuth from MLB reference data; not observed postgame weather","outfield_bearing_deg":bearing,"venue_baseline_density_kg_m3":baseline_density,"venue_baseline_wind_out_mph":baseline_wind,"venue_geometry":geometry,"weather_climatology":climatology}


def merge_environment(mlb_environment:dict[str,Any]|None,weather:dict[str,Any]|None)->dict[str,Any]:
    out=dict(mlb_environment or {});w=weather if isinstance(weather,dict) else {}
    if w.get("status")=="READY_SHADOW":
        for key in ("temperature_f","humidity_pct","pressure_hpa","wind_mph","wind_direction_deg","outfield_bearing_deg","venue_baseline_density_kg_m3","venue_baseline_wind_out_mph"):
            if w.get(key) is not None:out[key]=w[key]
        out["weather_shadow_source"]=w.get("source");out["weather_shadow_valid_time"]=w.get("forecast_valid_time");out["weather_shadow_point_in_time"]=True
        out["venue_geometry_shadow"]=w.get("venue_geometry") or {};out["weather_climatology_shadow"]=w.get("weather_climatology") or {}
    return out