from __future__ import annotations

"""Point-in-time source contracts for Statcast run-value leaderboards.

Defense/catching uses Baseball Savant's team Fielding Run Value CSV with an
explicit dateEnd before the target game. Baserunning uses completed prior-season
team totals by default until a date-bounded endpoint is independently verified.
Raw provider rows are retained so schema changes fail closed instead of silently
changing model inputs.
"""

import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FIELDING_URL="https://baseballsavant.mlb.com/leaderboard/fielding-run-value"
BASERUN_URL="https://baseballsavant.mlb.com/leaderboard/baserunning-run-value"
UserTextGetter=Callable[[str],str]


def _get_text(url:str)->str:
    request=Request(url,headers={"User-Agent":"Pulsar-V14.5","Accept":"text/csv,text/plain,*/*"})
    with urlopen(request,timeout=45) as response: return response.read().decode("utf-8","replace")

def _url(base:str,params:dict[str,Any])->str: return f"{base}?{urlencode(params)}"
def _rows(text:str)->list[dict[str,str]]:
    rows=list(csv.DictReader(io.StringIO(text or "")))
    if not rows: raise ValueError("Savant CSV returned no rows")
    return rows

def _target_prior_day(target_day:str)->str: return (date.fromisoformat(target_day)-timedelta(days=1)).isoformat()

def fielding_team_snapshot(target_day:str,*,getter:UserTextGetter=_get_text)->dict[str,Any]:
    season=int(target_day[:4]); prior=_target_prior_day(target_day); start=f"{season}-03-01"; params={"csv":"true","dateStart":start,"dateEnd":prior,"gameType":"Regular","groupBy":"year","minInnings":"q","minResults":1,"position":0,"seasonEnd":season,"seasonStart":season,"type":"fielding-team"}; url=_url(FIELDING_URL,params)
    rows=_rows(getter(url)); return {"schema":"pulsar-v14-savant-fielding-team-pit-v1","role":"SHADOW_DATA_ONLY","provider":"Baseball Savant Fielding Run Value CSV","source_url":url,"target_day":target_day,"effective_cutoff":prior,"point_in_time":True,"same_day_excluded":True,"raw_columns":list(rows[0].keys()),"rows":rows}

def baserunning_prior_snapshot(target_season:int,*,getter:UserTextGetter=_get_text)->dict[str,Any]:
    prior=int(target_season)-1; params={"csv":"true","game_type":"Regular","n":"q","season_end":prior,"season_start":prior,"split":"no","team":"","type":"Batting Team","with_team_only":1}; url=_url(BASERUN_URL,params); rows=_rows(getter(url)); return {"schema":"pulsar-v14-savant-baserunning-prior-v1","role":"SHADOW_DATA_ONLY","provider":"Baseball Savant Baserunning Run Value CSV","source_url":url,"target_season":int(target_season),"source_season":prior,"point_in_time":True,"current_target_season_results_used":False,"team_level":True,"raw_columns":list(rows[0].keys()),"rows":rows}

def write_snapshot(snapshot:dict[str,Any],path:Path|str)->Path:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return target
