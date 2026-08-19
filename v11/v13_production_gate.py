from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import core
from . import v13_discord_delivery as delivery

SCHEMA="v13-production-gate-v1"


def _dt(v: Any):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:return None


def build(now: datetime | None=None,games: list[dict[str,Any]] | None=None,delivered: dict[str,Any] | None=None):
    now=now or datetime.now(timezone.utc)
    games=core.mlb_schedule(core.TARGET_DATE) if games is None else games
    delivered=delivery.load() if delivered is None else delivered
    sent=(delivered.get("games") or {})
    due=[];future=0
    for game in games or []:
        gid=str(game.get("gamePk") or "");start=_dt(game.get("gameDate"))
        if not gid or start is None or start<=now:continue
        future+=1
        phase=core.phase_for_game(game,now)
        if phase=="FINAL" and not (sent.get(gid) or {}).get("sent"):
            due.append({"game_pk":game.get("gamePk"),"game_date":game.get("gameDate"),"phase":phase})
    return {"schema":SCHEMA,"target_date":core.TARGET_DATE,"checked_at":now.isoformat(),"future_games":future,
            "undelivered_final_games":due,"run_needed":bool(due),"paid_odds_api_required":bool(due),
            "reason":"undelivered-final-game" if due else "no-undelivered-final-game"}


def main():
    print(json.dumps(build(),ensure_ascii=False,sort_keys=True))


if __name__=="__main__":main()
