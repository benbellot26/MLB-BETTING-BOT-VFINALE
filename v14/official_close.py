from __future__ import annotations

"""Prospective verified-sharp close capture for certified official bets."""

from datetime import datetime, timezone
from typing import Any, Callable

from .acquisition import canonical_team_name, odds_snapshot, parse_time
from .bet_ledger import LEDGER, _read, _write
from .market_lines import choose_total_line
from .sharp_market import sharp_consensus

CLOSE_WINDOW_MINUTES=75.0
EVENT_TOLERANCE_MINUTES=90.0


def _event_for_row(row:dict[str,Any],events:list[dict[str,Any]])->dict[str,Any]|None:
    home=canonical_team_name(row.get("home")); away=canonical_team_name(row.get("away")); game_time=parse_time(row.get("game_date")); candidates=[]
    for event in events:
        if canonical_team_name(event.get("home_team"))!=home or canonical_team_name(event.get("away_team"))!=away:continue
        try:d=abs((parse_time(event.get("commence_time"))-game_time).total_seconds())/60.0
        except Exception:continue
        if d<=EVENT_TOLERANCE_MINUTES:candidates.append((d,event))
    candidates.sort(key=lambda x:x[0])
    if not candidates:return None
    if len(candidates)>1 and abs(candidates[1][0]-candidates[0][0])<30:return None
    return candidates[0][1]


def capture(*,path=LEDGER,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->int:
    rows=_read(path); current=now or datetime.now(timezone.utc); current=current if current.tzinfo else current.replace(tzinfo=timezone.utc); pending=[]
    for row in rows:
        if row.get("result"):continue
        try:mins=(parse_time(row.get("game_date"))-current.astimezone(timezone.utc)).total_seconds()/60.0
        except Exception:continue
        if 0<mins<=CLOSE_WINDOW_MINUTES:pending.append(row)
    if not pending:return 0
    events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))(); captured_at=current.astimezone(timezone.utc).isoformat(); changed=0
    for row in pending:
        event=_event_for_row(row,events)
        if event is None:continue
        if str(row.get("market"))=="TOTAL":
            total_line=row.get("line")
            if total_line is None:continue
        else:
            try:total_line=choose_total_line(event,as_of=captured_at)["line"]
            except Exception:continue
        sharp=sharp_consensus(event,total_line=float(total_line),as_of=captured_at); close=(((sharp.get("selections") or {}).get(str(row.get("selection") or "")) or {}).get("fair_probability"))
        try:close=float(close)
        except Exception:continue
        if not 0<close<1 or sharp.get("freshness_verified") is not True:continue
        entry=float(row.get("odds") or 0)
        if entry<=1:continue
        row["closing_odds"]=1.0/close
        row["closing_source"]="verified sharp fair probability <=75m pregame"
        row["clv_implied_probability_pp"]=(close-1.0/entry)*100
        row["close_captured_at"]=captured_at
        changed+=1
    if changed:_write(rows,path)
    return changed
