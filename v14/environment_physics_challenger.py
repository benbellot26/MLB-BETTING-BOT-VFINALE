from __future__ import annotations

"""Physics-oriented venue-relative weather diagnostics for Pulsar V14.

Absolute altitude/climate belongs in the park factor.  Daily weather therefore
becomes promotion-ready only when compared with a venue/month baseline, avoiding
double-counting Coors-like structural effects.
"""

import math
from typing import Any

ROLE="CHALLENGER_ONLY"
STANDARD_DENSITY_KG_M3=1.225


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _clip(value:float,low:float,high:float)->float: return max(low,min(high,float(value)))


def air_density_kg_m3(temperature_f:float,humidity_pct:float,pressure_hpa:float)->float:
    temp_c=(float(temperature_f)-32)*5/9; temp_k=temp_c+273.15
    if temp_k<=0: raise ValueError("invalid absolute temperature")
    rh=_clip(float(humidity_pct),0,100)/100; pressure_pa=float(pressure_hpa)*100
    if pressure_pa<=0: raise ValueError("pressure must be positive")
    saturation_hpa=6.112*math.exp((17.67*temp_c)/(temp_c+243.5)); vapor_pa=rh*saturation_hpa*100; dry_pa=max(0.0,pressure_pa-vapor_pa)
    return dry_pa/(287.05*temp_k)+vapor_pa/(461.495*temp_k)


def wind_out_component_mph(wind_speed_mph:float,wind_from_deg:float,outfield_bearing_deg:float)->float:
    wind_to=(float(wind_from_deg)+180)%360; return max(0.0,float(wind_speed_mph))*math.cos(math.radians(wind_to-float(outfield_bearing_deg)))


def evaluate(environment:dict[str,Any]|None)->dict[str,Any]:
    data=environment if isinstance(environment,dict) else {}; roof=str(data.get("roof") or "").lower()
    if any(token in roof for token in ("closed","dome","roofed")):
        return {"schema":"pulsar-v14-environment-physics-challenger-v2","role":ROLE,"status":"READY_SHADOW","auto_activation":False,"indoor":True,"density_ratio":1.0,"density_anomaly_ratio":0.0,"wind_out_component_mph":0.0,"wind_out_anomaly_mph":0.0,"flight_environment_index":0.0,"promotion_ready":True,"reason":"closed/indoor roof neutralized"}
    temp=_num(data.get("temperature_f")); humidity=_num(data.get("humidity_pct")); pressure=_num(data.get("pressure_hpa")); wind_speed=_num(data.get("wind_mph")); wind_from=_num(data.get("wind_direction_deg")); bearing=_num(data.get("outfield_bearing_deg"))
    missing=[name for name,value in (("temperature_f",temp),("humidity_pct",humidity),("pressure_hpa",pressure),("wind_mph",wind_speed),("wind_direction_deg",wind_from),("outfield_bearing_deg",bearing)) if value is None]
    if missing: return {"schema":"pulsar-v14-environment-physics-challenger-v2","role":ROLE,"status":"COLLECTING","auto_activation":False,"promotion_ready":False,"missing":missing,"reason":"physical weather inputs incomplete; no values imputed"}
    density=air_density_kg_m3(float(temp),float(humidity),float(pressure)); wind_out=wind_out_component_mph(float(wind_speed),float(wind_from),float(bearing))
    baseline_density=_num(data.get("venue_baseline_density_kg_m3")); baseline_wind=_num(data.get("venue_baseline_wind_out_mph"))
    baseline_ready=baseline_density is not None and baseline_density>0 and baseline_wind is not None
    reference_density=float(baseline_density) if baseline_ready else STANDARD_DENSITY_KG_M3; reference_wind=float(baseline_wind) if baseline_ready else 0.0
    density_anomaly=(density-reference_density)/reference_density; wind_anomaly=wind_out-reference_wind
    # Lower-than-normal density and more outward-than-normal wind are carry friendly.
    index=_clip(-density_anomaly*5.0+wind_anomaly/40.0,-1.0,1.0)
    return {"schema":"pulsar-v14-environment-physics-challenger-v2","role":ROLE,"status":"READY_SHADOW" if baseline_ready else "READY_DIAGNOSTIC","auto_activation":False,"promotion_ready":baseline_ready,"indoor":False,"air_density_kg_m3":density,"density_ratio":density/STANDARD_DENSITY_KG_M3,"venue_baseline_density_kg_m3":baseline_density,"density_anomaly_ratio":density_anomaly,"wind_out_component_mph":wind_out,"venue_baseline_wind_out_mph":baseline_wind,"wind_out_anomaly_mph":wind_anomaly,"flight_environment_index":index,"baseline_mode":"VENUE_MONTH" if baseline_ready else "STANDARD_ATMOSPHERE_DIAGNOSTIC_ONLY","market_probability_used_as_feature":False}
