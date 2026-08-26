from __future__ import annotations

"""Prospective, fail-soft weather enrichment for native V14 shadow research.

The source is queried only at analysis time and never backfilled from observed
postgame weather.  It supplies the physical variables missing from the MLB feed
(humidity, surface pressure and numeric wind direction).  No outfield bearing is
invented, so wind-to-outfield effects remain diagnostic until a separately
authenticated venue-orientation artifact exists.
"""

from datetime import datetime, timezone
import math
from typing import Any, Callable

from .acquisition import http_json, parse_time

URL="https://api.open-meteo.com/v1/forecast"
ROLE="SHADOW_ONLY"
Getter=Callable[[str,dict[str,Any]],Any]


def _num(value:Any)->float|None:
    try:out=float(value)
    except Exception:return None
    return out if math.isfinite(out) else None


def _base(status:str,reason:str|None=None)->dict[str,Any]:
    out={"schema":"pulsar-v14-live-weather-shadow-v1","role":ROLE,"status":status,"auto_activation":False,"champion_impact":False,"market_probability_used_as_feature":False,"point_in_time":True}
    if reason:out["reason"]=reason
    return out


def fetch(latitude:float|None,longitude:float|None,*,game_date:str,analyzed_at:str,getter:Getter=http_json)->dict[str,Any]:
    if latitude is None or longitude is None:return _base("COLLECTING","venue coordinates unavailable")
    try:game=parse_time(game_date);analysis=parse_time(analyzed_at)
    except Exception:return _base("COLLECTING","invalid game/analysis timestamp")
    if analysis>=game:return _base("COLLECTING","weather snapshot is not strictly pregame")
    params={"latitude":float(latitude),"longitude":float(longitude),"hourly":"temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m","temperature_unit":"fahrenheit","wind_speed_unit":"mph","timezone":"UTC","forecast_days":15}
    try:payload=getter(URL,params) or {}
    except Exception as exc:return _base("UNAVAILABLE",f"Open-Meteo fetch failed: {type(exc).__name__}: {exc}")
    hourly=payload.get("hourly") or {};times=hourly.get("time") or []
    if not times:return _base("UNAVAILABLE","Open-Meteo hourly forecast unavailable")
    candidates=[]
    for i,value in enumerate(times):
        try:dt=datetime.fromisoformat(str(value).replace("Z","+00:00"));dt=dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:continue
        candidates.append((abs((dt-game).total_seconds()),dt,i))
    if not candidates:return _base("UNAVAILABLE","Open-Meteo forecast timestamps invalid")
    _,valid,i=min(candidates,key=lambda x:x[0])
    if abs((valid-game).total_seconds())>2*3600:return _base("UNAVAILABLE","no forecast hour close to first pitch")
    def at(name:str)->float|None:
        values=hourly.get(name) or []
        return _num(values[i]) if i<len(values) else None
    values={"temperature_f":at("temperature_2m"),"humidity_pct":at("relative_humidity_2m"),"pressure_hpa":at("surface_pressure"),"wind_mph":at("wind_speed_10m"),"wind_direction_deg":at("wind_direction_10m")}
    missing=[k for k,v in values.items() if v is None]
    if missing:return {**_base("COLLECTING","physical forecast variables incomplete"),"missing":missing,"forecast_valid_time":valid.isoformat()}
    return {**_base("READY_SHADOW"),**values,"latitude":float(latitude),"longitude":float(longitude),"forecast_valid_time":valid.isoformat(),"analyzed_at":analysis.isoformat(),"forecast_lead_hours":(game-analysis).total_seconds()/3600,"source":"Open-Meteo generic forecast API","source_contract":"forecast retrieved prospectively at analysis; not observed postgame weather","outfield_bearing_deg":None}


def merge_environment(mlb_environment:dict[str,Any]|None,weather:dict[str,Any]|None)->dict[str,Any]:
    out=dict(mlb_environment or {});w=weather if isinstance(weather,dict) else {}
    if w.get("status")=="READY_SHADOW":
        for key in ("temperature_f","humidity_pct","pressure_hpa","wind_mph","wind_direction_deg"):
            if w.get(key) is not None:out[key]=w[key]
        out["weather_shadow_source"]=w.get("source");out["weather_shadow_valid_time"]=w.get("forecast_valid_time");out["weather_shadow_point_in_time"]=True
    return out
