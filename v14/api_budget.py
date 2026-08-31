from __future__ import annotations

"""Persistent request-equivalent budgets for automated Odds snapshots.

Budgets are intentionally expressed in paid request-equivalent snapshots rather
than provider credits because provider pricing can change. Manual production
runs remain user-triggered and are not blocked here. Automated close capture and
automated FINAL prediction collection have independent conservative daily caps.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

LEDGER=Path("data/v14_api_usage.jsonl")
REPORT=Path("data/v14_api_usage_report.json")
SCHEMA="pulsar-v14-api-usage-v1"
KIND_CLOSE="ODDS_CLOSE_SNAPSHOT"
KIND_PREDICTION="ODDS_SCHEDULED_FINAL_PREDICTION_SNAPSHOT"
DEFAULT_MAX_CLOSE_PER_UTC_DAY=12
DEFAULT_MAX_PREDICTION_PER_UTC_DAY=12


def _env_limit(name:str,default:int)->int:
    try:value=int(os.getenv(name,str(default)))
    except Exception:value=default
    return max(1,min(48,value))


def daily_close_limit()->int:return _env_limit("V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY",DEFAULT_MAX_CLOSE_PER_UTC_DAY)
def daily_prediction_limit()->int:return _env_limit("V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY",DEFAULT_MAX_PREDICTION_PER_UTC_DAY)


def _now(now:datetime|None=None)->datetime:
    out=now or datetime.now(timezone.utc)
    if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _read(path:Path|str=LEDGER)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists():return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:row=json.loads(line)
        except Exception:continue
        if isinstance(row,dict) and row.get("schema")==SCHEMA:rows.append(row)
    return rows


def _append(row:dict[str,Any],path:Path|str=LEDGER)->None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("a",encoding="utf-8") as handle:handle.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")


def day_key(now:datetime|None=None)->str:return _now(now).date().isoformat()


def used(kind:str=KIND_CLOSE,path:Path|str=LEDGER,*,now:datetime|None=None)->int:
    day=day_key(now)
    return sum(str(r.get("kind") or "")==kind and str(r.get("utc_day") or "")==day for r in _read(path))


def _allowance(kind:str,limit:int,path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    count=used(kind,path,now=now)
    return {"kind":kind,"utc_day":day_key(now),"used":count,"limit":limit,"remaining":max(0,limit-count),"allowed":count<limit}


def allowance(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    return _allowance(KIND_CLOSE,daily_close_limit(),path,now=now)


def prediction_allowance(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    return _allowance(KIND_PREDICTION,daily_prediction_limit(),path,now=now)


def latest_recorded_at(kind:str,path:Path|str=LEDGER)->datetime|None:
    candidates=[]
    for row in _read(path):
        if str(row.get("kind") or "")!=kind:continue
        try:
            value=datetime.fromisoformat(str(row.get("recorded_at") or "").replace("Z","+00:00"))
            if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
            candidates.append(value.astimezone(timezone.utc))
        except Exception:continue
    return max(candidates) if candidates else None


def record_close_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,due_rows:int=0)->dict[str,Any]:
    current=_now(now);before=allowance(path,now=current)
    if not before["allowed"]:raise RuntimeError("automated paid close-snapshot daily budget exhausted")
    row={"schema":SCHEMA,"recorded_at":current.isoformat(),"utc_day":current.date().isoformat(),"kind":KIND_CLOSE,"request_equivalents":1,"due_rows":int(due_rows),"provider_credit_cost":None,"note":"provider credit pricing intentionally not guessed"}
    _append(row,path);return row


def record_prediction_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,due_games:list[str]|None=None)->dict[str,Any]:
    current=_now(now);before=prediction_allowance(path,now=current)
    if not before["allowed"]:raise RuntimeError("automated paid prediction-snapshot daily budget exhausted")
    ids=sorted({str(game) for game in (due_games or []) if str(game)})
    row={"schema":SCHEMA,"recorded_at":current.isoformat(),"utc_day":current.date().isoformat(),"kind":KIND_PREDICTION,"request_equivalents":1,"due_rows":len(ids),"due_games":ids,"provider_credit_cost":None,"note":"scheduled FINAL prediction request-equivalent; provider credit pricing intentionally not guessed"}
    _append(row,path);return row


def build_report(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    rows=_read(path);counts=Counter(str(r.get("kind") or "UNKNOWN") for r in rows);close_today=allowance(path,now=now);prediction_today=prediction_allowance(path,now=now)
    return {"schema":"pulsar-v14-api-usage-report-v2","generated_at":_now(now).isoformat(),"request_equivalents_total":sum(int(r.get("request_equivalents") or 0) for r in rows),"by_kind":dict(sorted(counts.items())),"automated_close_today":close_today,"automated_prediction_today":prediction_today,"policy":{"default_max_paid_close_snapshots_per_utc_day":DEFAULT_MAX_CLOSE_PER_UTC_DAY,"close_config_env":"V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY","default_max_paid_prediction_snapshots_per_utc_day":DEFAULT_MAX_PREDICTION_PER_UTC_DAY,"prediction_config_env":"V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY","manual_prediction_runs_budgeted":False,"provider_credit_cost_not_assumed":True}}


def write_report(path:Path|str=LEDGER,output:Path|str=REPORT,*,now:datetime|None=None)->dict[str,Any]:
    report=build_report(path,now=now);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return report


def main()->None:
    parser=argparse.ArgumentParser(description="Pulsar paid API request-equivalent budget");sub=parser.add_subparsers(dest="command",required=True)
    a=sub.add_parser("allowance");a.add_argument("--ledger",default=str(LEDGER))
    pa=sub.add_parser("prediction-allowance");pa.add_argument("--ledger",default=str(LEDGER))
    rp=sub.add_parser("record-prediction");rp.add_argument("--ledger",default=str(LEDGER));rp.add_argument("--due-games",default="")
    r=sub.add_parser("report");r.add_argument("--ledger",default=str(LEDGER));r.add_argument("--output",default=str(REPORT))
    args=parser.parse_args()
    if args.command=="allowance":out=allowance(args.ledger)
    elif args.command=="prediction-allowance":out=prediction_allowance(args.ledger)
    elif args.command=="record-prediction":out=record_prediction_snapshot(args.ledger,due_games=[x.strip() for x in str(args.due_games).split(",") if x.strip()])
    else:out=write_report(args.ledger,args.output)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
