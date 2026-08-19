from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import core
from . import storage

OUT=Path("data/v13_coverage_report.json")
SCHEMA="v13-daily-coverage-v1"


def _dt(v: Any):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:return None


def _norm(v: Any) -> str:
    return "".join(c.lower() for c in str(v or "") if c.isalnum())


def _teams(game):
    teams=game.get("teams") or {}
    return (((teams.get("home") or {}).get("team") or {}).get("name") or "",
            ((teams.get("away") or {}).get("team") or {}).get("name") or "")


def _strict_match(games,events,tolerance_min=120.0):
    buckets={}
    for e in events or []:
        buckets.setdefault((_norm(e.get("home_team")),_norm(e.get("away_team"))),[]).append(e)
    out={};ambiguous=set()
    for g in games or []:
        home,away=_teams(g);gt=_dt(g.get("gameDate"));gid=str(g.get("gamePk") or "")
        if not gid or gt is None:continue
        candidates=[]
        for e in buckets.get((_norm(home),_norm(away)),[]):
            et=_dt(e.get("commence_time"))
            if et is None:continue
            delta=abs((et-gt).total_seconds())/60
            if delta<=tolerance_min:candidates.append((delta,et,e))
        candidates.sort(key=lambda x:(x[0],x[1]))
        if len(candidates)>1 and abs(candidates[0][0]-candidates[1][0])<1e-6:
            ambiguous.add(gid);continue
        if candidates:out[gid]=candidates[0][2]
    return out,ambiguous


def latest_snapshot(snapshot_dir: Path=storage.SNAPSHOT_DIR) -> Path | None:
    files=sorted(snapshot_dir.glob("*.json.gz"),key=lambda p:p.stat().st_mtime)
    return files[-1] if files else None


def load_snapshot(path: Path | None=None):
    path=path or latest_snapshot()
    if path is None or not path.exists():return None
    with gzip.open(path,"rt",encoding="utf-8") as fh:return json.load(fh)


def build(snapshot: dict[str,Any],results: list[dict[str,Any]] | None=None) -> dict[str,Any]:
    games=list(snapshot.get("games") or []);events=list(snapshot.get("odds_events") or [])
    analyzed_at=str(snapshot.get("analyzed_at") or "");ref=_dt(analyzed_at)
    matches,ambiguous=_strict_match(games,events)
    analyzed={str(r.get("game_pk") or "") for r in (results or [])}
    rows=[]
    for g in games:
        gid=str(g.get("gamePk") or "");home,away=_teams(g);start=_dt(g.get("gameDate"))
        if not gid:continue
        if gid in analyzed:status="ANALYZED"
        elif start is None:status="SKIPPED_GAME_TIME_MISSING"
        elif ref is not None and start<=ref:status="SKIPPED_ALREADY_STARTED"
        elif gid in ambiguous:status="SKIPPED_AMBIGUOUS_ODDS_EVENT"
        elif gid not in matches:status="SKIPPED_NO_ODDS_EVENT"
        else:status="SKIPPED_MATCHED_BUT_NOT_ANALYZED"
        rows.append({"game_pk":g.get("gamePk"),"game_date":g.get("gameDate"),"away":away,"home":home,"status":status,
                     "odds_event_id":(matches.get(gid) or {}).get("id")})
    future=[r for r in rows if r["status"]!="SKIPPED_ALREADY_STARTED"]
    counts={}
    for r in rows:counts[r["status"]]=counts.get(r["status"],0)+1
    future_analyzed=sum(r["status"]=="ANALYZED" for r in future)
    return {"schema":SCHEMA,"target_date":snapshot.get("target_date"),"run_id":snapshot.get("run_id"),"analyzed_at":analyzed_at,
            "scheduled_games":len(rows),"future_or_unresolved_games":len(future),"analyzed_games":len(analyzed),
            "future_coverage_rate":future_analyzed/len(future) if future else 1.0,"status_counts":counts,"games":rows,
            "complete_future_coverage":bool(future_analyzed==len(future)),
            "policy":"Every scheduled game is either ANALYZED or carries an explicit skip reason; ambiguous event identity fails closed."}


def main():
    snap=load_snapshot()
    if snap is None:
        report={"schema":SCHEMA,"status":"SNAPSHOT_MISSING","games":[]}
    else:
        payload_path=Path("runtime/v11/discord_payload.json")
        results=[]
        if payload_path.exists():
            try:results=json.loads(payload_path.read_text(encoding="utf-8")).get("results") or []
            except Exception:results=[]
        report=build(snap,results)
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":main()
