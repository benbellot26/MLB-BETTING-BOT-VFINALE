from __future__ import annotations

"""Build normalized point-in-time defense/catcher/baserunning shadow priors.

Fielding/catching comes from Baseball Savant through target-1 day and is
normalized with official MLB games played through the same cutoff. Baserunning
uses the completed prior season until a current-season date-bounded export is
independently validated. Any source-schema or team-mapping ambiguity fails
closed and cannot affect the champion.
"""

import argparse
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Callable

from .acquisition import http_json
from .savant_run_value_pit import baserunning_prior_snapshot, fielding_team_snapshot

OUTPUT=Path("data/v14_defense_baserunning_priors.json")
MLB_TEAMS_URL="https://statsapi.mlb.com/api/v1/teams"
MLB_TEAM_STATS_URL="https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
JsonGetter=Callable[[str,dict[str,Any]],Any]


def _num(value:Any)->float|None:
    if value is None:return None
    try: out=float(str(value).replace(",","").strip())
    except Exception:return None
    return out if math.isfinite(out) else None


def _norm(value:Any)->str:return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _pick(row:dict[str,Any],*names:str)->Any:
    normalized={_norm(k):v for k,v in row.items()}
    for name in names:
        key=_norm(name)
        if key in normalized:return normalized[key]
    return None


def _team_name(row:dict[str,Any])->str:return str(_pick(row,"team_name","team","name","teamname","entity_name") or "").strip()


def _teams(season:int,getter:JsonGetter=http_json)->dict[str,dict[str,Any]]:
    payload=getter(MLB_TEAMS_URL,{"sportId":1,"season":season}) or {};out={}
    for row in payload.get("teams") or []:
        if not isinstance(row,dict):continue
        tid=row.get("id");name=row.get("name")
        if not tid or not name:continue
        team={"id":str(tid),"name":str(name)}
        for value in (name,row.get("clubName"),row.get("shortName"),row.get("teamName"),row.get("abbreviation"),row.get("teamCode"),row.get("fileCode")):
            if value:out[_norm(value)]=team
    aliases={
        "dbacks":"Arizona Diamondbacks","diamondbacks":"Arizona Diamondbacks","athletics":"Athletics",
        "whitesox":"Chicago White Sox","redsox":"Boston Red Sox","bluejays":"Toronto Blue Jays",
        "guardians":"Cleveland Guardians","royals":"Kansas City Royals","rays":"Tampa Bay Rays","yankees":"New York Yankees","mets":"New York Mets",
        "dodgers":"Los Angeles Dodgers","angels":"Los Angeles Angels","giants":"San Francisco Giants","padres":"San Diego Padres","cubs":"Chicago Cubs",
        "cardinals":"St. Louis Cardinals","brewers":"Milwaukee Brewers","pirates":"Pittsburgh Pirates","phillies":"Philadelphia Phillies",
        "nationals":"Washington Nationals","orioles":"Baltimore Orioles","braves":"Atlanta Braves","marlins":"Miami Marlins","reds":"Cincinnati Reds",
        "tigers":"Detroit Tigers","twins":"Minnesota Twins","mariners":"Seattle Mariners","rangers":"Texas Rangers","astros":"Houston Astros","rockies":"Colorado Rockies"
    }
    by_full={_norm(v["name"]):v for v in out.values()}
    for alias,full in aliases.items():
        if _norm(full) in by_full:out[_norm(alias)]=by_full[_norm(full)]
    return out


def _team_stat(team_id:str,*,stats:str,group:str,season:int,getter:JsonGetter=http_json,start_date:str|None=None,end_date:str|None=None)->dict[str,Any]:
    url=MLB_TEAM_STATS_URL.format(team_id=team_id);params={"stats":stats,"group":group,"season":season,"gameType":"R"}
    if start_date:params["startDate"]=start_date
    if end_date:params["endDate"]=end_date
    payload=getter(url,params) or {}
    for block in payload.get("stats") or []:
        for split in block.get("splits") or []:
            stat=split.get("stat") or {}
            if isinstance(stat,dict):return stat
    return {}


def _plate_appearances(team_id:str,season:int,getter:JsonGetter=http_json)->float|None:
    pa=_num(_team_stat(team_id,stats="season",group="hitting",season=season,getter=getter).get("plateAppearances"));return pa if pa and pa>0 else None


def _games_played_through(team_id:str,season:int,cutoff:str,getter:JsonGetter=http_json)->float|None:
    stat=_team_stat(team_id,stats="byDateRange",group="hitting",season=season,getter=getter,start_date=f"{season}-03-01",end_date=cutoff)
    games=_num(stat.get("gamesPlayed"))
    return games if games and games>0 else None


def _fielding_rows(snapshot:dict[str,Any],team_map:dict[str,dict[str,Any]],season:int,cutoff:str,getter:JsonGetter=http_json)->tuple[dict[str,dict[str,Any]],list[str]]:
    out={};failures=[]
    for row in snapshot.get("rows") or []:
        name=_team_name(row);team=team_map.get(_norm(name))
        if not team:failures.append(f"unmapped_fielding_team:{name}");continue
        inf_of=_num(_pick(row,"inf_of_runs","inf/of runs","infield_outfield_runs","infieldoutfieldruns"));catching=_num(_pick(row,"catcher_runs","catching_runs","catching runs"))
        if inf_of is None or catching is None:failures.append(f"fielding_schema_missing:{name}");continue
        games=_games_played_through(team["id"],season,cutoff,getter=getter)
        if games is None:failures.append(f"fielding_games_played_missing:{name}");continue
        scale=150.0/games
        out[team["id"]]={"team_name":team["name"],"fielding_run_value_per_150":inf_of*scale,"catcher_run_value_per_150":catching*scale,"fielding_raw":{"inf_of_runs":inf_of,"catching_runs":catching,"games_played_through_cutoff":games,"cutoff":cutoff}}
    return out,failures


def _baserunning_rows(snapshot:dict[str,Any],team_map:dict[str,dict[str,Any]],season:int,getter:JsonGetter=http_json)->tuple[dict[str,dict[str,Any]],list[str]]:
    out={};failures=[]
    for row in snapshot.get("rows") or []:
        name=_team_name(row);team=team_map.get(_norm(name))
        if not team:failures.append(f"unmapped_baserunning_team:{name}");continue
        runs=_num(_pick(row,"runner_runs_tot","baserunning_runs","baserunning runs","runner runs total"))
        if runs is None:failures.append(f"baserunning_schema_missing:{name}");continue
        pa=_plate_appearances(team["id"],season,getter=getter)
        if pa is None:failures.append(f"baserunning_pa_missing:{name}");continue
        out[team["id"]]={"team_name":team["name"],"baserunning_runs_per_600_pa":runs/pa*600.0,"baserunning_raw":{"runs":runs,"plate_appearances":pa,"season":season}}
    return out,failures


def build(target_day:str,*,text_getter=None,json_getter:JsonGetter=http_json)->dict[str,Any]:
    target=date.fromisoformat(str(target_day)[:10]);season=target.year;prior=season-1
    f=fielding_team_snapshot(target.isoformat(),**({"getter":text_getter} if text_getter else {}));b=baserunning_prior_snapshot(season,**({"getter":text_getter} if text_getter else {}));team_map=_teams(season,json_getter);cutoff=str(f.get("effective_cutoff") or "")
    fielding,ff=_fielding_rows(f,team_map,season,cutoff,getter=json_getter);running,bf=_baserunning_rows(b,team_map,prior,getter=json_getter)
    teams={};ids=sorted(set(fielding)|set(running))
    for tid in ids:teams[tid]={**fielding.get(tid,{}),**running.get(tid,{})}
    complete=[tid for tid,row in teams.items() if all(row.get(k) is not None for k in ("fielding_run_value_per_150","catcher_run_value_per_150","baserunning_runs_per_600_pa"))]
    failures=ff+bf
    return {"schema":"pulsar-v14-defense-baserunning-priors-v3","role":"SHADOW_DATA_ONLY","point_in_time":True,"cutoff_day":cutoff,"target_day":target.isoformat(),"fielding_source":{k:f.get(k) for k in ("provider","effective_cutoff","same_day_excluded","raw_columns")},"baserunning_source":{k:b.get(k) for k in ("provider","source_season","current_target_season_results_used","team_level","raw_columns")},"normalization":{"defense_catcher":"Savant run value scaled to 150 games using MLB byDateRange gamesPlayed through identical PIT cutoff","baserunning":"completed prior-season Savant run value per 600 official MLB plate appearances"},"teams":teams,"coverage":{"mapped_teams":len(teams),"complete_teams":len(complete),"complete_team_ids":complete},"failures":failures[:100],"promotion_ready":False,"champion_impact":False}


def write(target_day:str,path:Path|str=OUTPUT)->dict[str,Any]:
    artifact=build(target_day);target=Path(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return artifact


def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("target_day");parser.add_argument("--output",default=str(OUTPUT));args=parser.parse_args();out=write(args.target_day,args.output);print(json.dumps({"schema":out["schema"],"target_day":out["target_day"],"coverage":out["coverage"],"failures":out["failures"][:30]},ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":main()
