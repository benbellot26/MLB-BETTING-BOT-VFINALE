from __future__ import annotations

"""Historical weather backfill using only forecasts public before game analysis.

The implementation deliberately reuses the audited V137 ECMWF single-run
selector.  Each row carries forecast-run/as-of provenance; unavailable archive
periods remain missing rather than being filled with observed postgame weather.
This module is research-only and outside the native-production import boundary.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from v11.v137_free_data import historical_weather_for_game

ROLE="RESEARCH_ONLY"
FetchJson=Callable[...,dict[str,Any]|None]


def _dt(value:Any)->datetime:
    out=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def build_row(feature:dict[str,Any],*,fetch_json:FetchJson|None=None)->dict[str,Any]:
    game_pk=str(feature.get("game_pk") or "");game_time=feature.get("game_date");as_of=feature.get("as_of");home=str(feature.get("home") or "")
    if not game_pk or not game_time or not as_of or not home:raise ValueError("historical feature missing game identity/time/home")
    if not (_dt(as_of)<_dt(game_time)):raise ValueError("weather backfill feature is not strictly pregame")
    weather=historical_weather_for_game(game_time,home,as_of,fetch_json=fetch_json)
    if weather.get("point_in_time") is not True:raise ValueError(f"weather provenance not point-in-time for {game_pk}")
    return {"schema":"pulsar-v14-weather-pit-row-v1","role":ROLE,"auto_activation":False,"game_pk":game_pk,"game_date":_dt(game_time).isoformat(),"as_of":_dt(as_of).isoformat(),"home":home,"point_in_time":True,"weather":weather,"champion_impact":False}


def build(features:Iterable[dict[str,Any]],*,fetch_json:FetchJson|None=None)->dict[str,Any]:
    rows=[];failures=[]
    for feature in features:
        try:rows.append(build_row(feature,fetch_json=fetch_json))
        except Exception as exc:failures.append({"game_pk":str(feature.get("game_pk") or ""),"reason":f"{type(exc).__name__}:{exc}"})
    available=sum(1 for r in rows if (r.get("weather") or {}).get("available") is True)
    digest=hashlib.sha256(("\n".join(json.dumps(r,sort_keys=True,separators=(",",":"),ensure_ascii=False) for r in rows)+"\n").encode("utf-8")).hexdigest()
    return {"schema":"pulsar-v14-weather-pit-backfill-v1","role":ROLE,"auto_activation":False,"point_in_time":True,"rows":rows,"coverage":{"input_rows":len(rows)+len(failures),"pit_rows":len(rows),"available_weather":available,"availability_rate":available/len(rows) if rows else 0.0},"failures":failures[:200],"content_sha256":digest,"champion_impact":False,"native_live_confirmation_required":True}


def read_gzip_features(path:Path|str)->list[dict[str,Any]]:
    out=[]
    with gzip.open(Path(path),"rt",encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row=json.loads(line)
                if isinstance(row,dict):out.append(row)
    return out


def write(features:Iterable[dict[str,Any]],output:Path|str,*,fetch_json:FetchJson|None=None)->dict[str,Any]:
    artifact=build(features,fetch_json=fetch_json);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return artifact


def main()->None:
    parser=argparse.ArgumentParser(description="Build strict historical ECMWF forecast features from V137 PIT feature rows")
    parser.add_argument("features_gz");parser.add_argument("--output",required=True);parser.add_argument("--limit",type=int)
    args=parser.parse_args();features=read_gzip_features(args.features_gz);features=features[:args.limit] if args.limit else features;out=write(features,args.output);print(json.dumps({"schema":out["schema"],"coverage":out["coverage"],"failures":out["failures"][:20],"content_sha256":out["content_sha256"]},sort_keys=True))


if __name__=="__main__":main()
