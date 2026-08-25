from __future__ import annotations

"""Build Pulsar V14 structural inputs directly from point-in-time MLB data."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import math
import re
from typing import Any, Callable

from .acquisition import http_json
from .run_stack import StructuralRunInput
from .structural import LeagueBaselines, Starter, StructuralInputs, TeamInputs, enhance_starter, historical_pitcher_prior, project

MLB_API = "https://statsapi.mlb.com/api/"
MLBGetter = Callable[[str, dict[str, Any]], Any]

STATIC_PARK = {
    "Arizona Diamondbacks":1.04,"Athletics":1.05,"Atlanta Braves":1.01,"Baltimore Orioles":1.01,"Boston Red Sox":1.03,
    "Chicago White Sox":1.00,"Chicago Cubs":1.02,"Cincinnati Reds":1.05,"Cleveland Guardians":0.98,"Colorado Rockies":1.14,
    "Detroit Tigers":0.98,"Houston Astros":1.00,"Kansas City Royals":0.99,"Los Angeles Angels":1.01,"Los Angeles Dodgers":0.98,
    "Miami Marlins":0.96,"Milwaukee Brewers":1.00,"Minnesota Twins":0.99,"New York Mets":0.98,"New York Yankees":1.03,
    "Philadelphia Phillies":1.02,"Pittsburgh Pirates":0.97,"San Diego Padres":0.97,"San Francisco Giants":0.94,"Seattle Mariners":0.96,
    "St. Louis Cardinals":1.00,"Tampa Bay Rays":0.98,"Texas Rangers":1.02,"Toronto Blue Jays":1.01,"Washington Nationals":1.00,
}
COORD = {
    "Arizona Diamondbacks":(33.4453,-112.0667),"Athletics":(38.5806,-121.5130),"Atlanta Braves":(33.8907,-84.4677),
    "Baltimore Orioles":(39.2839,-76.6217),"Boston Red Sox":(42.3467,-71.0972),"Chicago White Sox":(41.8301,-87.6338),
    "Chicago Cubs":(41.9484,-87.6553),"Cincinnati Reds":(39.0975,-84.5069),"Cleveland Guardians":(41.4962,-81.6852),
    "Colorado Rockies":(39.7559,-104.9942),"Detroit Tigers":(42.3390,-83.0485),"Houston Astros":(29.7573,-95.3555),
    "Kansas City Royals":(39.0517,-94.4803),"Los Angeles Angels":(33.8003,-117.8827),"Los Angeles Dodgers":(34.0739,-118.2400),
    "Miami Marlins":(25.7781,-80.2197),"Milwaukee Brewers":(43.0280,-87.9712),"Minnesota Twins":(44.9817,-93.2776),
    "New York Mets":(40.7571,-73.8458),"New York Yankees":(40.8296,-73.9262),"Philadelphia Phillies":(39.9061,-75.1665),
    "Pittsburgh Pirates":(40.4469,-80.0057),"San Diego Padres":(32.7076,-117.1570),"San Francisco Giants":(37.7786,-122.3893),
    "Seattle Mariners":(47.5914,-122.3325),"St. Louis Cardinals":(38.6226,-90.1928),"Tampa Bay Rays":(27.7683,-82.6534),
    "Texas Rangers":(32.7473,-97.0832),"Toronto Blue Jays":(43.6414,-79.3894),"Washington Nationals":(38.8730,-77.0074),
}


def _num(value: Any, default: float=0.0) -> float:
    try:
        out=float(value); return out if math.isfinite(out) else float(default)
    except Exception: return float(default)


def _parse_dt(value: Any) -> datetime|None:
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"));
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception: return None


def _mlb(path: str, params: dict[str,Any]|None=None, *, getter: MLBGetter=http_json) -> Any:
    return getter(MLB_API+path.lstrip("/"), params or {})


def _stat_split(payload: dict[str,Any]|None) -> dict[str,Any]:
    try:
        splits=((payload or {}).get("stats") or [{}])[0].get("splits") or []
        return splits[0].get("stat") or {} if splits else {}
    except Exception: return {}


def team_season_stats(team_id: Any, group: str, season: int, *, getter: MLBGetter=http_json) -> dict[str,Any]:
    return _stat_split(_mlb(f"v1/teams/{team_id}/stats",{"stats":"season","group":group,"season":int(season)},getter=getter))


def player_season_stats(player_id: Any, group: str, season: int, *, getter: MLBGetter=http_json) -> dict[str,Any]:
    if not player_id: return {}
    return _stat_split(_mlb(f"v1/people/{player_id}/stats",{"stats":"season","group":group,"season":int(season)},getter=getter))


def league_baselines(season: int, *, getter: MLBGetter=http_json) -> LeagueBaselines:
    hitting=_mlb("v1/teams/stats",{"stats":"season","group":"hitting","season":int(season),"sportIds":1},getter=getter) or {}
    pitching=_mlb("v1/teams/stats",{"stats":"season","group":"pitching","season":int(season),"sportIds":1},getter=getter) or {}
    hs=(hitting.get("stats") or [{}])[0].get("splits") or []; ps=(pitching.get("stats") or [{}])[0].get("splits") or []
    rpg=[_num((r.get("stat") or {}).get("runsPerGame"),4.45) for r in hs]; ops=[_num((r.get("stat") or {}).get("ops"),.710) for r in hs]
    era=[_num((r.get("stat") or {}).get("era"),4.35) for r in ps]; whip=[_num((r.get("stat") or {}).get("whip"),1.32) for r in ps]
    return LeagueBaselines(rpg=sum(rpg)/len(rpg) if rpg else 4.45,ops=sum(ops)/len(ops) if ops else .710,era=sum(era)/len(era) if era else 4.35,whip=sum(whip)/len(whip) if whip else 1.32)


def pitcher_prior(player_id: Any, season: int, *, getter: MLBGetter=http_json) -> dict[str,float]:
    if not player_id: return {}
    payload=_mlb(f"v1/people/{player_id}/stats",{"stats":"yearByYear","group":"pitching"},getter=getter) or {}
    splits=(payload.get("stats") or [{}])[0].get("splits") or []
    by_season={int(_num(r.get("season"))):r.get("stat") or {} for r in splits if _num(r.get("season"))>0}
    return historical_pitcher_prior([(by_season.get(int(season)-1) or {},.65),(by_season.get(int(season)-2) or {},.35)])


def lineup(game_pk: Any, side: str, season: int, *, getter: MLBGetter=http_json) -> dict[str,Any]:
    try: box=_mlb(f"v1/game/{game_pk}/boxscore",getter=getter) or {}
    except Exception: return {"count":0,"players":[],"weighted_ops":None,"confirmed":False,"status":"UNAVAILABLE","coverage":0.0}
    team=((box.get("teams") or {}).get(side) or {}); players=team.get("players") or {}; hitters=[]
    weights=[1.04,1.05,1.08,1.10,1.06,1.00,.96,.93,.90]
    for player in players.values():
        batting_order=player.get("battingOrder")
        if batting_order is None: continue
        person=player.get("person") or {}; pid=person.get("id"); stats=player_season_stats(pid,"hitting",season,getter=getter) if pid else {}
        ops=_num(stats.get("ops"),0.0)
        hitters.append({"id":pid,"name":person.get("fullName"),"batting_order":batting_order,"ops":ops if .3<=ops<=1.5 else None})
    hitters.sort(key=lambda r:int(_num(r.get("batting_order"),999))); usable=[(r["ops"],weights[min(i,8)]) for i,r in enumerate(hitters[:9]) if r.get("ops") is not None]
    weighted_ops=sum(v*w for v,w in usable)/sum(w for _,w in usable) if len(usable)>=5 else None; count=min(9,len(hitters))
    return {"count":count,"players":hitters,"weighted_ops":weighted_ops,"confirmed":count>=9,"status":"CONFIRMED" if count>=9 else ("PARTIAL" if count else "UNAVAILABLE"),"coverage":count/9.0,"source":"official MLB boxscore batting order"}


def effective_lineup_ops(lineup_row: dict[str,Any], team_ops: float) -> tuple[float,float]:
    """Shrink partial-lineup OPS toward team OPS; 9/9 gets full weight."""
    raw=lineup_row.get("weighted_ops"); count=int(_num(lineup_row.get("count"),0))
    if raw is None or count<5: return float(team_ops),0.0
    confidence=max(0.0,min(1.0,(count-4)/5.0))
    return confidence*float(raw)+(1-confidence)*float(team_ops),confidence


def _raw_starter(game: dict[str,Any], side: str, league: LeagueBaselines, season: int, *, getter: MLBGetter) -> tuple[Starter,Starter,dict[str,Any]]:
    probable=(((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {}); pid,name=probable.get("id"),probable.get("fullName")
    current=player_season_stats(pid,"pitching",season,getter=getter) if pid else {}; innings=_num(current.get("inningsPitched"),0.0); weight=max(0.0,min(1.0,innings/70.0))
    era_raw,whip_raw=_num(current.get("era"),league.era),_num(current.get("whip"),league.whip)
    base=Starter(era=weight*era_raw+(1-weight)*league.era,whip=weight*whip_raw+(1-weight)*league.whip,k9=_num(current.get("strikeoutsPer9Inn"),8.5) if current else None,bb9=_num(current.get("walksPer9Inn"),3.2) if current else None,hr9=_num(current.get("homeRunsPer9"),1.15) if current else None,innings=innings,sample_weight=weight)
    prior=pitcher_prior(pid,season,getter=getter); enhanced=enhance_starter(current,prior,fallback=base)
    ctx={"id":pid,"name":name,"announced":bool(pid and name),"era":enhanced.era,"whip":enhanced.whip,"k9":enhanced.k9,"bb9":enhanced.bb9,"hr9":enhanced.hr9,"inningsPitched":enhanced.innings,"sample_weight":enhanced.sample_weight,"current_stats_available":bool(current),"prior_available":bool(prior)}
    return base,enhanced,ctx


def _distance_km(a: tuple[float,float]|None,b: tuple[float,float]|None) -> float|None:
    if not a or not b:return None
    lat1,lon1,lat2,lon2=map(math.radians,(a[0],a[1],b[0],b[1])); h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742*math.asin(min(1.0,math.sqrt(h)))


def _recent_completed_games(team_id: Any,target_date: str,*,current_game_pk: Any|None=None,current_game_date: Any|None=None,getter: MLBGetter) -> list[dict[str,Any]]:
    try: target=date.fromisoformat(str(target_date))
    except Exception:return []
    current_dt=_parse_dt(current_game_date); games=[]
    for back in range(0,4):
        day=(target-timedelta(days=back)).isoformat(); payload=_mlb("v1/schedule",{"sportId":1,"date":day,"hydrate":"linescore","teamId":team_id},getter=getter) or {}
        for game in [g for block in payload.get("dates") or [] for g in block.get("games") or []]:
            if str(game.get("gamePk") or "")==str(current_game_pk or ""):continue
            game_dt=_parse_dt(game.get("gameDate"))
            if current_dt and game_dt and game_dt>=current_dt:continue
            status=game.get("status") or {}; final=str(status.get("abstractGameState") or "").lower()=="final" or str(status.get("codedGameState") or "").upper()=="F"
            if final: games.append(game)
    games.sort(key=lambda g:_parse_dt(g.get("gameDate")) or datetime.min.replace(tzinfo=timezone.utc),reverse=True); return games


def _game_team_side(box: dict[str,Any],team_id: Any) -> dict[str,Any]:
    for side in ("home","away"):
        candidate=((box.get("teams") or {}).get(side) or {})
        if str((candidate.get("team") or {}).get("id") or "")==str(team_id):return candidate
    return {}


def _reliever_rows(team: dict[str,Any]) -> list[tuple[Any,dict[str,Any]]]:
    ids=list(team.get("pitchers") or []); players=team.get("players") or {}; out=[]
    for idx,pid in enumerate(ids):
        player=players.get(f"ID{pid}") or {}; pitching=((player.get("stats") or {}).get("pitching") or {})
        started=_num(pitching.get("gamesStarted"),0)>0 or idx==0
        if not started: out.append((pid,player))
    return out


def _bullpen_usage(team_id: Any,game_pk: Any|None,*,getter: MLBGetter) -> dict[str,Any]:
    if not game_pk:return {"relief_pitches":0,"heavy_relievers":0,"relievers_used":0,"bulk_relievers":0}
    box=_mlb(f"v1/game/{game_pk}/boxscore",getter=getter) or {}; team=_game_team_side(box,team_id)
    if not team:return {"relief_pitches":0,"heavy_relievers":0,"relievers_used":0,"bulk_relievers":0}
    counts=[]
    for _pid,player in _reliever_rows(team): counts.append(int(_num((((player.get("stats") or {}).get("pitching") or {}).get("pitchesThrown")),0)))
    return {"relief_pitches":sum(counts),"heavy_relievers":sum(c>=20 for c in counts),"relievers_used":len(counts),"bulk_relievers":sum(c>=40 for c in counts)}


def bullpen_three_day_snapshot(team_id: Any,games: list[dict[str,Any]],*,getter: MLBGetter) -> dict[str,Any]:
    usage: dict[str,dict[str,Any]]={}
    for game in games[:4]:
        box=_mlb(f"v1/game/{game.get('gamePk')}/boxscore",getter=getter) or {}; team=_game_team_side(box,team_id)
        for pid,player in _reliever_rows(team):
            person=player.get("person") or {}; pitching=((player.get("stats") or {}).get("pitching") or {}); row=usage.setdefault(str(pid),{"id":pid,"name":person.get("fullName"),"uses_last_3d":0,"pitches_last_3d":0,"game_pitches":[]})
            pitches=int(_num(pitching.get("pitchesThrown"),0)); row["uses_last_3d"]+=1; row["pitches_last_3d"]+=pitches; row["game_pitches"].append(pitches)
    relievers=list(usage.values())
    for row in relievers:
        pitches=int(row.get("pitches_last_3d") or 0); uses=int(row.get("uses_last_3d") or 0); row["taxed"]=pitches>=35 or uses>=2; row["likely_unavailable"]=pitches>=55 or uses>=3; row["available"]=not row["likely_unavailable"]; row["bulk_workload"]=any(int(x)>=40 for x in row.get("game_pitches") or [])
    return {"coverage":min(1.0,len(relievers)/7.0),"relievers":relievers,"games_considered":min(len(games),4),"source":"MLB boxscores last 3 days including earlier same-day completed game"}


def _wind_speed_mph(text: Any) -> float|None:
    match=re.search(r"(\d+(?:\.\d+)?)\s*mph",str(text or ""),flags=re.I); return float(match.group(1)) if match else None


def game_environment(game_pk: Any,*,getter: MLBGetter) -> dict[str,Any]:
    try: feed=_mlb(f"v1.1/game/{game_pk}/feed/live",getter=getter) or {}
    except Exception:return {"available":False,"reason":"game feed unavailable"}
    gd=feed.get("gameData") or {}; weather=gd.get("weather") or {}; venue=gd.get("venue") or {}; field=venue.get("fieldInfo") or {}; condition=str(weather.get("condition") or ""); wind=str(weather.get("wind") or ""); roof=field.get("roofType") or venue.get("roofType"); temp=_num(weather.get("temp"),math.nan); temp=temp if math.isfinite(temp) else None
    return {"available":bool(weather or roof),"temperature_f":temp,"condition":condition or None,"wind":wind or None,"wind_mph":_wind_speed_mph(wind),"roof":roof,"source":"MLB live gameData.weather/venue"}


def operational(game: dict[str,Any],*,target_date: str,home: str,home_id: Any,away_id: Any,getter: MLBGetter=http_json) -> dict[str,Any]:
    current=COORD.get(home); game_pk=game.get("gamePk"); game_date=game.get("gameDate"); out={"current_doubleheader":str(game.get("doubleHeader") or "N")!="N"}
    for side,team_id in (("home",home_id),("away",away_id)):
        recent=_recent_completed_games(team_id,target_date,current_game_pk=game_pk,current_game_date=game_date,getter=getter); previous=recent[0] if recent else None; teams=(previous or {}).get("teams") or {}; previous_home=((teams.get("home") or {}).get("team") or {}).get("name") if previous else None; previous_coord=COORD.get(previous_home); distance=_distance_km(previous_coord,current); previous_dt=_parse_dt((previous or {}).get("gameDate")); current_dt=_parse_dt(game_date); days_back=max(0,(current_dt.date()-previous_dt.date()).days) if previous_dt and current_dt else None; innings=int(_num(((previous or {}).get("linescore") or {}).get("currentInning"),9)) if previous else 9
        out[side]={"rest_days":max(0,days_back-1) if days_back is not None else None,"travel_km":round(distance,1) if distance is not None else None,"timezone_shift_hours_approx":round((current[1]-previous_coord[1])/15,2) if current and previous_coord else None,"previous_extra_innings":bool(previous and innings>9),"previous_doubleheader":bool(previous and str(previous.get("doubleHeader") or "N")!="N"),"bullpen_previous_game":_bullpen_usage(team_id,(previous or {}).get("gamePk"),getter=getter),"bullpen_three_day":bullpen_three_day_snapshot(team_id,recent,getter=getter)}
    return out


@dataclass(frozen=True)
class NativeGameInputs:
    structural: StructuralRunInput
    home: str
    away: str
    context: dict[str,Any]
    feature_row: dict[str,Any]
    structural_debug: dict[str,Any]


def build_game_inputs(game: dict[str,Any],*,target_date: str,analyzed_at: str,getter: MLBGetter=http_json) -> NativeGameInputs:
    teams=game.get("teams") or {}; home_team=((teams.get("home") or {}).get("team") or {}); away_team=((teams.get("away") or {}).get("team") or {}); home_id,away_id=home_team.get("id"),away_team.get("id"); home,away=str(home_team.get("name") or ""),str(away_team.get("name") or "")
    if not home_id or not away_id or not home or not away: raise ValueError("game missing team identity")
    game_pk,game_date=game.get("gamePk"),game.get("gameDate")
    if game_pk is None or not game_date: raise ValueError("game missing identity/date")
    season=int(str(game_date)[:4]); league=league_baselines(season,getter=getter); home_hit=team_season_stats(home_id,"hitting",season,getter=getter); away_hit=team_season_stats(away_id,"hitting",season,getter=getter); home_pitch=team_season_stats(home_id,"pitching",season,getter=getter); away_pitch=team_season_stats(away_id,"pitching",season,getter=getter); home_lineup=lineup(game_pk,"home",season,getter=getter); away_lineup=lineup(game_pk,"away",season,getter=getter); home_starter,home_enhanced,home_starter_ctx=_raw_starter(game,"home",league,season,getter=getter); away_starter,away_enhanced,away_starter_ctx=_raw_starter(game,"away",league,season,getter=getter); oper=operational(game,target_date=target_date,home=home,home_id=home_id,away_id=away_id,getter=getter); environment=game_environment(game_pk,getter=getter); park_factor=float(STATIC_PARK.get(home,1.0))
    home_team_ops=_num(home_hit.get("ops"),league.ops); away_team_ops=_num(away_hit.get("ops"),league.ops); home_effective_ops,home_lineup_conf=effective_lineup_ops(home_lineup,home_team_ops); away_effective_ops,away_lineup_conf=effective_lineup_ops(away_lineup,away_team_ops)
    structural_inputs=StructuralInputs(league=league,home=TeamInputs(runs_per_game=_num(home_hit.get("runsPerGame"),league.rpg),ops=home_team_ops,lineup_ops=home_effective_ops,team_era=_num(home_pitch.get("era"),league.era),starter=home_starter,enhanced_starter=home_enhanced,operational=oper.get("home") or {}),away=TeamInputs(runs_per_game=_num(away_hit.get("runsPerGame"),league.rpg),ops=away_team_ops,lineup_ops=away_effective_ops,team_era=_num(away_pitch.get("era"),league.era),starter=away_starter,enhanced_starter=away_enhanced,operational=oper.get("away") or {}),static_park_factor=park_factor,current_doubleheader=bool(oper.get("current_doubleheader")))
    projected=project(structural_inputs); venue=str(((game.get("venue") or {}).get("name")) or ""); structural=StructuralRunInput(game_pk=str(game_pk),game_date=str(game_date),venue=venue,structural_home_mu=float(projected["home_mu"]),structural_away_mu=float(projected["away_mu"]),static_park_factor=park_factor).validated()
    context={"home":home,"away":away,"home_id":home_id,"away_id":away_id,"home_sp":home_starter_ctx.get("name"),"away_sp":away_starter_ctx.get("name"),"home_starter":home_starter_ctx,"away_starter":away_starter_ctx,"home_lineup":home_lineup,"away_lineup":away_lineup,"lineup_structural_confidence":{"home":home_lineup_conf,"away":away_lineup_conf},"environment":environment}
    starter_complete=bool(home_starter_ctx.get("announced") and away_starter_ctx.get("announced"))
    feature_row={"schema":"pulsar-v14-native-feature-row-v3","game_pk":str(game_pk),"game_date":str(game_date),"as_of":str(analyzed_at),"phase":"UNRESOLVED","model_generation":"pulsar-v14-native-inputs","feature_contract":"pulsar-v14-native-pit-v3","point_in_time":True,"point_in_time_validation_reasons":[],"home":home,"away":away,"context":context,"features":{"operational":oper,"bullpen":{"home":((oper.get("home") or {}).get("bullpen_three_day") or {}),"away":((oper.get("away") or {}).get("bullpen_three_day") or {})},"environment":environment},"rich_modules":{},"feature_provenance":{"mlb":{"point_in_time":True,"retrieval_timestamp_attested":True,"source_timestamp_attested":None,"postgame_identity":False}},"data_quality":{"eligible":True,"starter_complete":starter_complete,"home_lineup_count":home_lineup.get("count"),"away_lineup_count":away_lineup.get("count"),"home_lineup_structural_confidence":home_lineup_conf,"away_lineup_structural_confidence":away_lineup_conf},"disabled_unvalidated_modules":["h2h","recent_form"]}
    return NativeGameInputs(structural=structural,home=home,away=away,context=context,feature_row=feature_row,structural_debug={"league":asdict(league),"projection":projected,"operational":oper,"environment":environment,"static_park_factor":park_factor,"lineup_structural_confidence":{"home":home_lineup_conf,"away":away_lineup_conf}})
