from __future__ import annotations

"""Strictly-pregame recent-start workload collector.

This is usage evidence, not a narrative 'recent form' feature.  Completed starts
are filtered by actual game timestamp before the target game, preventing future
starts from entering historical/prospective starter-depth estimates.
"""

from typing import Any, Callable
from .acquisition import http_json, parse_time

MLB_API="https://statsapi.mlb.com/api/"
Getter=Callable[[str,dict[str,Any]],Any]


def recent_starts(player_id:Any,season:int,game_date:Any,*,getter:Getter=http_json,limit:int=8)->list[dict[str,Any]]:
    if not player_id: return []
    try: cutoff=parse_time(game_date)
    except Exception: return []
    payload=getter(MLB_API+f"v1/people/{player_id}/stats",{"stats":"gameLog","group":"pitching","season":int(season)}) or {}
    splits=((payload.get("stats") or [{}])[0].get("splits") or []); rows=[]
    for split in splits:
        stat=split.get("stat") or {}; started=float(stat.get("gamesStarted") or 0)>0
        if not started: continue
        raw_date=split.get("date") or ((split.get("game") or {}).get("gameDate"))
        if not raw_date: continue
        # MLB gameLog `date` can be YYYY-MM-DD; use end-of-day interpretation
        # only after proving the date is strictly before target calendar date.
        try:
            if "T" in str(raw_date):
                if parse_time(raw_date)>=cutoff: continue
            elif str(raw_date)[:10]>=cutoff.date().isoformat(): continue
        except Exception: continue
        try: ip=float(stat.get("inningsPitched") or 0)
        except Exception: ip=0.0
        pitches=stat.get("numberOfPitches")
        if pitches is None: pitches=stat.get("pitchesThrown")
        try: pitches=float(pitches) if pitches is not None else None
        except Exception: pitches=None
        rows.append({"game_date":str(raw_date),"innings":ip,"pitches":pitches,"batters_faced":stat.get("battersFaced"),"source":"MLB gameLog filtered strictly before target"})
    rows.sort(key=lambda r:str(r.get("game_date") or ""),reverse=True)
    return rows[:max(1,int(limit))]


def enrich_starter(starter:dict[str,Any],game_date:Any,*,getter:Getter=http_json)->dict[str,Any]:
    row=dict(starter or {}); pid=row.get("id"); season=int(str(game_date)[:4])
    starts=recent_starts(pid,season,game_date,getter=getter) if pid else []
    row["recent_starts"]=starts; row["recent_starts_pit_safe"]=True; row["recent_starts_n"]=len(starts)
    return row
