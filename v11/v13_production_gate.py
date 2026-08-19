from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import core
from . import v13_discord_delivery as delivery

SCHEMA="v13-production-gate-v2"


def _dt(v: Any):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:return None


def _probable_id(game: dict[str,Any],side: str) -> str:
    item=((game.get("teams") or {}).get(side) or {})
    p=item.get("probablePitcher") or {}
    return str(p.get("id") or p.get("fullName") or "")


def _starter_changed(old: Any,new: Any) -> bool:
    """Compare only compatible identities; ID-vs-name is treated as unknown."""
    a=str(old or "").strip();b=str(new or "").strip()
    if not a or not b:return False
    a_id=a.isdigit();b_id=b.isdigit()
    if a_id != b_id:return False
    if a_id:return a!=b
    return core.norm_name(a)!=core.norm_name(b)


def _feed_lineups(game_pk: Any) -> dict[str,list[str]]:
    """Read official batting order from the free MLB live feed when published."""
    try:
        feed=core.mlb(f"v1.1/game/{game_pk}/feed/live") or {}
        teams=((((feed.get("liveData") or {}).get("boxscore") or {}).get("teams")) or {})
        out={}
        for side in ("home","away"):
            order=((teams.get(side) or {}).get("battingOrder") or [])
            out[side]=[str(x) for x in order[:9] if x is not None]
        return out
    except Exception:
        return {"home":[],"away":[]}


def _critical_change(game: dict[str,Any],previous: dict[str,Any]) -> dict[str,Any]:
    state=previous.get("personnel_state") or {}
    if not state:
        return {"critical":False,"reason":"NO_PREVIOUS_PERSONNEL_STATE"}
    reasons=[]
    for side in ("home","away"):
        old=state.get(f"{side}_starter");new=_probable_id(game,side)
        if _starter_changed(old,new):reasons.append(f"{side.upper()}_STARTER_CHANGED")
    # Only spend the extra free MLB feed call if a prior confirmed/partial lineup
    # was persisted. Empty pregame lineups cannot create a false change.
    has_old_lineup=any(state.get(f"{side}_lineup") for side in ("home","away"))
    if has_old_lineup:
        current=_feed_lineups(game.get("gamePk"))
        for side in ("home","away"):
            old=[str(x) for x in state.get(f"{side}_lineup") or []];new=current.get(side) or []
            if old and new and set(old)!=set(new):reasons.append(f"{side.upper()}_LINEUP_PERSONNEL_CHANGED")
    return {"critical":bool(reasons),"reason":"+".join(reasons) if reasons else "UNCHANGED","reasons":reasons}


def build(now: datetime | None=None,games: list[dict[str,Any]] | None=None,delivered: dict[str,Any] | None=None):
    now=now or datetime.now(timezone.utc)
    games=core.mlb_schedule(core.TARGET_DATE) if games is None else games
    delivered=delivery.load() if delivered is None else delivered
    sent=(delivered.get("games") or {})
    due=[];future=0;critical_checks=0
    for game in games or []:
        gid=str(game.get("gamePk") or "");start=_dt(game.get("gameDate"))
        if not gid or start is None or start<=now:continue
        future+=1
        phase=core.phase_for_game(game,now)
        is_final=phase=="FINAL"
        if not is_final:continue
        prior=sent.get(gid) or {}
        if not prior.get("sent"):
            due.append({"game_pk":game.get("gamePk"),"game_date":game.get("gameDate"),"phase":phase,"reason":"undelivered-final-game"})
            continue
        if prior.get("personnel_state"):
            critical_checks+=1;change=_critical_change(game,prior)
            if change.get("critical"):
                due.append({"game_pk":game.get("gamePk"),"game_date":game.get("gameDate"),"phase":phase,"reason":"critical-personnel-change","change":change})
    reasons=sorted({str(x.get("reason")) for x in due})
    return {"schema":SCHEMA,"target_date":core.TARGET_DATE,"checked_at":now.isoformat(),"future_games":future,
            "undelivered_final_games":due,"run_needed":bool(due),"paid_odds_api_required":bool(due),"critical_change_checks":critical_checks,
            "reason":"+".join(reasons) if reasons else "no-undelivered-or-changed-final-game"}


def main():
    print(json.dumps(build(),ensure_ascii=False,sort_keys=True))


if __name__=="__main__":main()
