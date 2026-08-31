from __future__ import annotations

"""Zero-paid-call gate for objective automated FINAL prediction snapshots.

The workflow may wake frequently, but this module performs only a free MLB
schedule read plus local ledger reads. A paid Odds prediction snapshot is allowed
only when at least one game is inside the canonical FINAL window, lacks an
already-observed SCHEDULED_FINAL snapshot, the retry cooldown has expired, and
the automated prediction budget still has capacity.
"""

import argparse
from datetime import datetime, timezone
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
    is_certification_snapshot,
)

PREDICTIONS=Path("data/v14_predictions.jsonl")
API_USAGE=Path("data/v14_api_usage.jsonl")
OUTPUT=Path("runtime/v14/scheduled_prediction_gate.json")
RETRY_COOLDOWN_MINUTES=15.0


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


def due_games(games:list[dict[str,Any]],predictions:list[dict[str,Any]],*,now:datetime|None=None)->list[dict[str,Any]]:
    current=_now(now);covered=covered_game_ids(predictions);due=[]
    for game in games:
        game_pk=str(game.get("gamePk") or "")
        if not game_pk or game_pk in covered:continue
        state=str(((game.get("status") or {}).get("abstractGameState") or "")).lower()
        if state in {"live","final"}:continue
        try:game_time=parse_time(game.get("gameDate"))
        except Exception:continue
        minutes=(game_time-current).total_seconds()/60.0
        if FINAL_MIN_MINUTES_TO_GAME<=minutes<=FINAL_MAX_MINUTES_TO_GAME:
            teams=game.get("teams") or {}
            due.append({
                "game_pk":game_pk,
                "game_date":game_time.isoformat(),
                "minutes_to_game":minutes,
                "home":(((teams.get("home") or {}).get("team") or {}).get("name")),
                "away":(((teams.get("away") or {}).get("team") or {}).get("name")),
            })
    return sorted(due,key=lambda row:(float(row["minutes_to_game"]),str(row["game_pk"])))


def build(
    *,
    predictions_path:Path|str=PREDICTIONS,
    api_usage_path:Path|str=API_USAGE,
    target_date:str|None=None,
    now:datetime|None=None,
    games_loader:Callable[[str],list[dict[str,Any]]]|None=None,
)->dict[str,Any]:
    current=_now(now);day=target_date or resolve_target_date(now=current);loader=games_loader or (lambda value:mlb_schedule(value,hydrate=""));games=loader(day);predictions=_read_predictions(predictions_path);due=due_games(games,predictions,now=current);budget=prediction_allowance(api_usage_path,now=current);last=latest_recorded_at(KIND_PREDICTION,api_usage_path);cooldown_remaining=0.0
    if last is not None:
        elapsed=(current-last).total_seconds()/60.0
        cooldown_remaining=max(0.0,RETRY_COOLDOWN_MINUTES-elapsed)
    if not due:reason="NO_FINAL_SNAPSHOT_DUE"
    elif not budget.get("allowed"):reason="DAILY_PREDICTION_BUDGET_EXHAUSTED"
    elif cooldown_remaining>0:reason="PREDICTION_RETRY_COOLDOWN"
    else:reason="FINAL_SNAPSHOT_DUE"
    run_required=bool(due and budget.get("allowed") and cooldown_remaining<=0)
    return {
        "schema":"pulsar-v14-scheduled-prediction-gate-v1",
        "checked_at":current.isoformat(),
        "target_date":day,
        "run_trigger":CERTIFICATION_RUN_TRIGGER,
        "run_required":run_required,
        "reason":reason,
        "network_policy":"MLB_SCHEDULE_FREE_PLUS_LOCAL_LEDGER_ONLY_BEFORE_PAID_RUN",
        "paid_api_calls_performed":0,
        "final_window_minutes_to_game":{"min":FINAL_MIN_MINUTES_TO_GAME,"max":FINAL_MAX_MINUTES_TO_GAME},
        "retry_cooldown_minutes":RETRY_COOLDOWN_MINUTES,
        "cooldown_remaining_minutes":cooldown_remaining,
        "due_games":due,
        "due_game_ids":[row["game_pk"] for row in due],
        "already_covered_scheduled_final_games":len(covered_game_ids(predictions)),
        "prediction_budget":budget,
    }


def write(*,output:Path|str=OUTPUT,**kwargs:Any)->dict[str,Any]:
    result=build(**kwargs);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return result


def main()->None:
    parser=argparse.ArgumentParser(description="Check whether an automated FINAL V14 prediction snapshot is objectively due")
    parser.add_argument("--predictions",default=str(PREDICTIONS));parser.add_argument("--api-usage-ledger",default=str(API_USAGE));parser.add_argument("--target-date");parser.add_argument("--output",default=str(OUTPUT));args=parser.parse_args()
    out=write(predictions_path=args.predictions,api_usage_path=args.api_usage_ledger,target_date=args.target_date,output=args.output)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
