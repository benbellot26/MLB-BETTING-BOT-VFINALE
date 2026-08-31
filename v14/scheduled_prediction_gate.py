from __future__ import annotations

"""Zero-paid-call gate for the ultra-low automated FINAL snapshot.

The workflow may wake frequently, but this module performs only a free MLB
schedule read plus local ledger reads. With the 500-credit/month user plan,
automation is limited to one paid SCHEDULED_FINAL snapshot per UTC day. The gate
therefore waits for the best daily cluster instead of spending that snapshot on
the first isolated game that happens to enter the FINAL window.

Cluster policy:
- maximize uncovered games simultaneously inside the canonical 10-60m window;
- among equally large clusters, stay as close as possible to the frozen 30m
  FINAL target across covered games;
- ties prefer the later instant, improving lineup-confirmation probability.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .acquisition import mlb_schedule, parse_time, resolve_target_date
from .api_budget import KIND_PREDICTION, latest_recorded_at, prediction_allowance
from .certification_timing import (
    CERTIFICATION_RUN_TRIGGER,
    FINAL_MAX_MINUTES_TO_GAME,
    FINAL_MIN_MINUTES_TO_GAME,
    FINAL_TARGET_MINUTES_TO_GAME,
    is_certification_snapshot,
)

PREDICTIONS=Path("data/v14_predictions.jsonl")
API_USAGE=Path("data/v14_api_usage.jsonl")
OUTPUT=Path("runtime/v14/scheduled_prediction_gate.json")
RETRY_COOLDOWN_MINUTES=15.0
NON_STARTABLE_DETAIL_TOKENS=("postponed","cancelled","canceled","suspended","delayed")


def _now(value:datetime|None=None)->datetime:
    out=value or datetime.now(timezone.utc)
    if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _read_predictions(path:Path|str=PREDICTIONS)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists():return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:row=json.loads(line)
        except Exception:continue
        if isinstance(row,dict):rows.append(row)
    return rows


def _row_policy(row:dict[str,Any])->str|None:
    direct=row.get("probability_policy_id")
    if direct:return str(direct)
    nested=(row.get("calibration") or {}).get("probability_policy_id")
    return str(nested) if nested else None


def covered_game_ids(rows:list[dict[str,Any]])->set[str]:
    covered=set()
    for row in rows:
        if row.get("model_generation")!=MODEL_GENERATION or _row_policy(row)!=PROBABILITY_POLICY_ID:continue
        if is_certification_snapshot(row):
            game_pk=str(row.get("game_pk") or "")
            if game_pk:covered.add(game_pk)
    return covered


def _startable_pregame(game:dict[str,Any])->bool:
    status=game.get("status") or {}
    abstract=str(status.get("abstractGameState") or "").strip().lower()
    if abstract in {"live","final"}:return False
    detailed=str(status.get("detailedState") or "").strip().lower()
    if any(token in detailed for token in NON_STARTABLE_DETAIL_TOKENS):return False
    return True


def _uncovered_games(games:list[dict[str,Any]],predictions:list[dict[str,Any]])->list[dict[str,Any]]:
    covered=covered_game_ids(predictions);out=[]
    for game in games:
        game_pk=str(game.get("gamePk") or "")
        if not game_pk or game_pk in covered or not _startable_pregame(game):continue
        try:game_time=parse_time(game.get("gameDate"))
        except Exception:continue
        teams=game.get("teams") or {}
        out.append({"game_pk":game_pk,"game_time":game_time,"game_date":game_time.isoformat(),"home":(((teams.get("home") or {}).get("team") or {}).get("name")),"away":(((teams.get("away") or {}).get("team") or {}).get("name"))})
    return out


def _eligible_at(row:dict[str,Any],at:datetime)->bool:
    minutes=(row["game_time"]-at).total_seconds()/60.0
    return FINAL_MIN_MINUTES_TO_GAME<=minutes<=FINAL_MAX_MINUTES_TO_GAME


def due_games(games:list[dict[str,Any]],predictions:list[dict[str,Any]],*,now:datetime|None=None)->list[dict[str,Any]]:
    current=_now(now);due=[]
    for row in _uncovered_games(games,predictions):
        minutes=(row["game_time"]-current).total_seconds()/60.0
        if FINAL_MIN_MINUTES_TO_GAME<=minutes<=FINAL_MAX_MINUTES_TO_GAME:
            due.append({k:v for k,v in row.items() if k!="game_time"}|{"minutes_to_game":minutes})
    return sorted(due,key=lambda row:(float(row["minutes_to_game"]),str(row["game_pk"])))


def best_cluster(games:list[dict[str,Any]],predictions:list[dict[str,Any]],*,now:datetime|None=None)->dict[str,Any]:
    current=_now(now);rows=[row for row in _uncovered_games(games,predictions) if row["game_time"]>current]
    if not rows:return {"target_at":None,"game_ids":[],"games":0,"mean_target_error_minutes":None}
    candidates={current}
    for row in rows:
        game_time=row["game_time"]
        for minutes in (FINAL_MAX_MINUTES_TO_GAME,FINAL_TARGET_MINUTES_TO_GAME,FINAL_MIN_MINUTES_TO_GAME):
            candidate=game_time-timedelta(minutes=float(minutes))
            if candidate>=current:candidates.add(candidate)
    scored=[]
    for candidate in candidates:
        covered=[row for row in rows if _eligible_at(row,candidate)]
        if not covered:continue
        errors=[abs((row["game_time"]-candidate).total_seconds()/60.0-FINAL_TARGET_MINUTES_TO_GAME) for row in covered]
        scored.append((len(covered),sum(errors)/len(errors),candidate,covered))
    if not scored:return {"target_at":None,"game_ids":[],"games":0,"mean_target_error_minutes":None}
    max_games=max(item[0] for item in scored);same=[item for item in scored if item[0]==max_games];min_error=min(item[1] for item in same);best=[item for item in same if abs(item[1]-min_error)<1e-9];count,error,target,covered=max(best,key=lambda item:item[2])
    return {"target_at":target.isoformat(),"game_ids":[row["game_pk"] for row in covered],"games":count,"mean_target_error_minutes":error,"policy":"MAX_GAMES_THEN_CLOSEST_TO_30M_THEN_LATEST"}


def build(
    *,
    predictions_path:Path|str=PREDICTIONS,
    api_usage_path:Path|str=API_USAGE,
    target_date:str|None=None,
    now:datetime|None=None,
    games_loader:Callable[[str],list[dict[str,Any]]]|None=None,
)->dict[str,Any]:
    current=_now(now);day=target_date or resolve_target_date(now=current);loader=games_loader or (lambda value:mlb_schedule(value,hydrate=""));games=loader(day);predictions=_read_predictions(predictions_path);due=due_games(games,predictions,now=current);plan=best_cluster(games,predictions,now=current);budget=prediction_allowance(api_usage_path,now=current);last=latest_recorded_at(KIND_PREDICTION,api_usage_path);cooldown_remaining=0.0
    if last is not None:
        elapsed=(current-last).total_seconds()/60.0
        cooldown_remaining=max(0.0,RETRY_COOLDOWN_MINUTES-elapsed)
    target_at=parse_time(plan["target_at"]) if plan.get("target_at") else None
    waiting_for_cluster=bool(due and target_at is not None and target_at>current+timedelta(seconds=30))
    if not due:reason="NO_FINAL_SNAPSHOT_DUE"
    elif cooldown_remaining>0:reason="PREDICTION_RETRY_COOLDOWN"
    elif not budget.get("allowed"):reason="AUTOMATED_PREDICTION_BUDGET_EXHAUSTED"
    elif waiting_for_cluster:reason="WAITING_FOR_BEST_DAILY_CLUSTER"
    else:reason="FINAL_SNAPSHOT_DUE"
    run_required=bool(due and budget.get("allowed") and cooldown_remaining<=0 and not waiting_for_cluster)
    return {
        "schema":"pulsar-v14-scheduled-prediction-gate-v2",
        "checked_at":current.isoformat(),
        "target_date":day,
        "run_trigger":CERTIFICATION_RUN_TRIGGER,
        "run_required":run_required,
        "reason":reason,
        "network_policy":"MLB_SCHEDULE_FREE_PLUS_LOCAL_LEDGER_ONLY_BEFORE_PAID_RUN",
        "paid_api_calls_performed":0,
        "final_window_minutes_to_game":{"min":FINAL_MIN_MINUTES_TO_GAME,"target":FINAL_TARGET_MINUTES_TO_GAME,"max":FINAL_MAX_MINUTES_TO_GAME},
        "retry_cooldown_minutes":RETRY_COOLDOWN_MINUTES,
        "cooldown_remaining_minutes":cooldown_remaining,
        "due_games":due,
        "due_game_ids":[row["game_pk"] for row in due],
        "best_daily_cluster":plan,
        "already_covered_scheduled_final_games":len(covered_game_ids(predictions)),
        "prediction_budget":budget,
        "cost_policy":"one automated FINAL snapshot/day; wait for maximum-coverage cluster near frozen 30m target",
    }


def write(*,output:Path|str=OUTPUT,**kwargs:Any)->dict[str,Any]:
    result=build(**kwargs);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return result


def main()->None:
    parser=argparse.ArgumentParser(description="Check whether the single automated FINAL V14 prediction snapshot is optimally due")
    parser.add_argument("--predictions",default=str(PREDICTIONS));parser.add_argument("--api-usage-ledger",default=str(API_USAGE));parser.add_argument("--target-date");parser.add_argument("--output",default=str(OUTPUT));args=parser.parse_args()
    out=write(predictions_path=args.predictions,api_usage_path=args.api_usage_ledger,target_date=args.target_date,output=args.output)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
