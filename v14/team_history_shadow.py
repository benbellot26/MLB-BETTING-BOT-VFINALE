from __future__ import annotations

"""Native-live counterpart of the strict V137 team-history features.

The feature semantics intentionally match the historical dataset: only final
regular-season games from strictly earlier official calendar dates are used.
Same-day results are excluded even when already final so historical and live
shadow evidence remain comparable.
"""

from collections import defaultdict
from datetime import date
import math
from functools import lru_cache
from typing import Any, Callable

from .acquisition import MLB_SCHEDULE_URL, http_json

Getter = Callable[[str, dict[str, Any]], Any]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out=float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _is_final(game: dict[str, Any]) -> bool:
    status=game.get("status") or {}
    return str(status.get("abstractGameState") or "").lower()=="final" or str(status.get("codedGameState") or "").upper()=="F"


def _side(game: dict[str, Any], side: str) -> tuple[str, int | None]:
    item=((game.get("teams") or {}).get(side) or {}); team=item.get("team") or {}; score=item.get("score")
    return str(team.get("id") or ""), int(score) if score is not None else None


def _prior_summary(history: list[dict[str, Any]], n: int | None = None) -> dict[str, Any]:
    rows=history[-n:] if n is not None else history
    if not rows:
        return {"games":0,"runs_for_pg":None,"runs_against_pg":None,"run_diff_pg":None,"win_pct":None}
    games=len(rows); rf=sum(_num(r.get("runs_for")) for r in rows); ra=sum(_num(r.get("runs_against")) for r in rows); wins=sum(_num(r.get("win")) for r in rows)
    return {"games":games,"runs_for_pg":rf/games,"runs_against_pg":ra/games,"run_diff_pg":(rf-ra)/games,"win_pct":wins/games}


def _rest_days(history: list[dict[str, Any]], target_day: str) -> int | None:
    if not history: return None
    latest=max(str(r.get("official_day") or "") for r in history)
    if not latest: return None
    delta=(date.fromisoformat(target_day)-date.fromisoformat(latest)).days-1
    return max(0,min(10,delta))


def team_feature(history: list[dict[str, Any]], target_day: str) -> dict[str, Any]:
    return {"season_to_date":_prior_summary(history),"last_7_games":_prior_summary(history,7),"last_14_games":_prior_summary(history,14),"last_30_games":_prior_summary(history,30),"rest_days":_rest_days(history,target_day)}


def build_from_games(games: list[dict[str, Any]], target_day: str) -> dict[str, Any]:
    season=int(target_day[:4]); history: dict[str,list[dict[str,Any]]]=defaultdict(list); accepted=0; rejected_same_day=0
    for game in sorted(games,key=lambda g:(str(g.get("gameDate") or ""),str(g.get("gamePk") or ""))):
        official=_day(game.get("officialDate") or game.get("gameDate"))
        if not official or not official.startswith(str(season)): continue
        if official>=target_day:
            if official==target_day: rejected_same_day+=1
            continue
        if str(game.get("gameType") or "").upper()!="R" or not _is_final(game): continue
        home_id,hs=_side(game,"home"); away_id,aws=_side(game,"away")
        if not home_id or not away_id or hs is None or aws is None: continue
        history[home_id].append({"official_day":official,"runs_for":hs,"runs_against":aws,"win":int(hs>aws)})
        history[away_id].append({"official_day":official,"runs_for":aws,"runs_against":hs,"win":int(aws>hs)})
        accepted+=1
    return {"schema":"pulsar-v14-native-team-history-shadow-v1","role":"SHADOW_ONLY","champion_impact":False,"point_in_time":True,"target_day":target_day,"rule":"final regular-season games with officialDate strictly earlier than target day; same-day games excluded for historical parity","accepted_prior_games":accepted,"same_day_games_excluded":rejected_same_day,"teams":{team_id:team_feature(rows,target_day) for team_id,rows in sorted(history.items())}}


def fetch_prior_games(target_day: str, *, getter: Getter = http_json) -> list[dict[str, Any]]:
    season=int(target_day[:4]); start=f"{season}-03-01"; payload=getter(MLB_SCHEDULE_URL,{"sportId":1,"startDate":start,"endDate":target_day,"gameTypes":"R","hydrate":"linescore"}) or {}
    return [game for block in payload.get("dates") or [] for game in block.get("games") or [] if isinstance(game,dict)]


@lru_cache(maxsize=8)
def live_artifact(target_day: str) -> dict[str, Any]:
    try: return build_from_games(fetch_prior_games(target_day),target_day)
    except Exception as exc: return {"schema":"pulsar-v14-native-team-history-shadow-v1","role":"SHADOW_ONLY","champion_impact":False,"point_in_time":True,"target_day":target_day,"status":"UNAVAILABLE","reason":f"{type(exc).__name__}: {exc}","teams":{}}


def matchup(artifact: dict[str, Any], home_team_id: Any, away_team_id: Any) -> dict[str, Any]:
    teams=artifact.get("teams") or {}; home=teams.get(str(home_team_id or "")); away=teams.get(str(away_team_id or "")); ready=isinstance(home,dict) and isinstance(away,dict)
    return {"schema":"pulsar-v14-native-team-history-matchup-v1","role":"SHADOW_ONLY","champion_impact":False,"point_in_time":artifact.get("point_in_time") is True,"status":"READY_SHADOW" if ready else "COLLECTING","home":home or {},"away":away or {},"source_rule":artifact.get("rule"),"target_day":artifact.get("target_day")}
