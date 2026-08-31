from __future__ import annotations

"""Persistent ultra-low budget for automated The Odds API snapshots.

The production endpoint currently requests three markets (h2h, spreads, totals)
from <=10 bookmakers, which costs three provider credits per snapshot under the
current provider contract. The user has a 500-credit/month plan, so automation
is deliberately capped far below that plan:

- at most 1 scheduled FINAL prediction snapshot per UTC day;
- at most 1 close snapshot per UTC day;
- at most 180 provider credits per UTC calendar month for all automation.

That leaves roughly 320 credits/month outside the automated budget for manual
runs, provider-pricing drift, or exceptional operations. All budget reservations
happen before the paid request, so failures cannot create an uncounted retry loop.
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
AUTOMATED_KINDS={KIND_CLOSE,KIND_PREDICTION}

DEFAULT_MAX_CLOSE_PER_UTC_DAY=1
DEFAULT_MAX_PREDICTION_PER_UTC_DAY=1
DEFAULT_PROVIDER_CREDITS_PER_SNAPSHOT=3
DEFAULT_MAX_AUTOMATED_PROVIDER_CREDITS_PER_UTC_MONTH=180


def _env_int(name:str,default:int,*,low:int=1,high:int=100000)->int:
    try:value=int(os.getenv(name,str(default)))
    except Exception:value=default
    return max(low,min(high,value))


def daily_close_limit()->int:return _env_int("V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY",DEFAULT_MAX_CLOSE_PER_UTC_DAY,high=48)
def daily_prediction_limit()->int:return _env_int("V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY",DEFAULT_MAX_PREDICTION_PER_UTC_DAY,high=48)
def provider_credits_per_snapshot()->int:return _env_int("V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT",DEFAULT_PROVIDER_CREDITS_PER_SNAPSHOT,high=100)
def monthly_automated_credit_limit()->int:return _env_int("V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH",DEFAULT_MAX_AUTOMATED_PROVIDER_CREDITS_PER_UTC_MONTH,high=100000)


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
def month_key(now:datetime|None=None)->str:return _now(now).strftime("%Y-%m")


def used(kind:str=KIND_CLOSE,path:Path|str=LEDGER,*,now:datetime|None=None)->int:
    day=day_key(now)
    return sum(str(r.get("kind") or "")==kind and str(r.get("utc_day") or "")==day for r in _read(path))


def automated_monthly_usage(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    month=month_key(now);rows=[]
    for row in _read(path):
        if str(row.get("kind") or "") not in AUTOMATED_KINDS:continue
        recorded=str(row.get("recorded_at") or "")
        row_month=str(row.get("utc_month") or recorded[:7])
        if row_month==month:rows.append(row)
    snapshots=sum(int(r.get("request_equivalents") or 0) for r in rows)
    default_cost=provider_credits_per_snapshot()
    credits=sum(int(r.get("provider_credit_cost") if r.get("provider_credit_cost") is not None else default_cost*int(r.get("request_equivalents") or 0)) for r in rows)
    limit=monthly_automated_credit_limit()
    return {"utc_month":month,"snapshots":snapshots,"provider_credits_used":credits,"provider_credit_limit":limit,"provider_credits_remaining":max(0,limit-credits),"allowed":credits+default_cost<=limit}


def _allowance(kind:str,limit:int,path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    count=used(kind,path,now=now);monthly=automated_monthly_usage(path,now=now)
    daily_allowed=count<limit
    return {"kind":kind,"utc_day":day_key(now),"used":count,"limit":limit,"remaining":max(0,limit-count),"daily_allowed":daily_allowed,"monthly":monthly,"allowed":daily_allowed and monthly["allowed"]}


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


def _budget_error(prefix:str,before:dict[str,Any])->RuntimeError:
    if not before.get("daily_allowed",False):return RuntimeError(f"{prefix} daily budget exhausted")
    return RuntimeError(f"{prefix} monthly provider-credit budget exhausted")


def _usage_row(kind:str,current:datetime,*,due_rows:int,due_games:list[str]|None=None,note:str)->dict[str,Any]:
    cost=provider_credits_per_snapshot()
    row={"schema":SCHEMA,"recorded_at":current.isoformat(),"utc_day":current.date().isoformat(),"utc_month":current.strftime("%Y-%m"),"kind":kind,"request_equivalents":1,"due_rows":int(due_rows),"provider_credit_cost":cost,"note":note}
    if due_games is not None:row["due_games"]=due_games
    return row


def record_close_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,due_rows:int=0)->dict[str,Any]:
    current=_now(now);before=allowance(path,now=current)
    if not before["allowed"]:raise _budget_error("automated paid close-snapshot",before)
    row=_usage_row(KIND_CLOSE,current,due_rows=due_rows,note="ultra-low automated close snapshot; reserved before paid request")
    _append(row,path);return row


def record_prediction_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,due_games:list[str]|None=None)->dict[str,Any]:
    current=_now(now);before=prediction_allowance(path,now=current)
    if not before["allowed"]:raise _budget_error("automated paid prediction-snapshot",before)
    ids=sorted({str(game) for game in (due_games or []) if str(game)})
    row=_usage_row(KIND_PREDICTION,current,due_rows=len(ids),due_games=ids,note="ultra-low scheduled FINAL prediction snapshot; reserved before paid request")
    _append(row,path);return row


def build_report(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    rows=_read(path);counts=Counter(str(r.get("kind") or "UNKNOWN") for r in rows);close_today=allowance(path,now=now);prediction_today=prediction_allowance(path,now=now);monthly=automated_monthly_usage(path,now=now)
    known_credits=sum(int(r.get("provider_credit_cost") or 0) for r in rows if r.get("provider_credit_cost") is not None)
    return {"schema":"pulsar-v14-api-usage-report-v3","generated_at":_now(now).isoformat(),"request_equivalents_total":sum(int(r.get("request_equivalents") or 0) for r in rows),"known_provider_credits_total":known_credits,"by_kind":dict(sorted(counts.items())),"automated_close_today":close_today,"automated_prediction_today":prediction_today,"automated_month":monthly,"policy":{"default_max_paid_close_snapshots_per_utc_day":DEFAULT_MAX_CLOSE_PER_UTC_DAY,"close_config_env":"V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY","default_max_paid_prediction_snapshots_per_utc_day":DEFAULT_MAX_PREDICTION_PER_UTC_DAY,"prediction_config_env":"V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY","default_provider_credits_per_snapshot":DEFAULT_PROVIDER_CREDITS_PER_SNAPSHOT,"provider_credit_cost_env":"V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT","default_max_automated_provider_credits_per_utc_month":DEFAULT_MAX_AUTOMATED_PROVIDER_CREDITS_PER_UTC_MONTH,"monthly_credit_config_env":"V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH","manual_prediction_runs_budgeted":False,"target_plan_provider_credits_per_month":500,"reserved_nonautomatic_credits_at_default_policy":320,"policy_mode":"ULTRA_LOW_MINIMUM_VIABLE_PROSPECTIVE_COLLECTION"}}


def write_report(path:Path|str=LEDGER,output:Path|str=REPORT,*,now:datetime|None=None)->dict[str,Any]:
    report=build_report(path,now=now);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return report


def main()->None:
    parser=argparse.ArgumentParser(description="Pulsar paid API budget");sub=parser.add_subparsers(dest="command",required=True)
    a=sub.add_parser("allowance");a.add_argument("--ledger",default=str(LEDGER))
    pa=sub.add_parser("prediction-allowance");pa.add_argument("--ledger",default=str(LEDGER))
    ma=sub.add_parser("monthly-allowance");ma.add_argument("--ledger",default=str(LEDGER))
    rp=sub.add_parser("record-prediction");rp.add_argument("--ledger",default=str(LEDGER));rp.add_argument("--due-games",default="")
    r=sub.add_parser("report");r.add_argument("--ledger",default=str(LEDGER));r.add_argument("--output",default=str(REPORT))
    args=parser.parse_args()
    if args.command=="allowance":out=allowance(args.ledger)
    elif args.command=="prediction-allowance":out=prediction_allowance(args.ledger)
    elif args.command=="monthly-allowance":out=automated_monthly_usage(args.ledger)
    elif args.command=="record-prediction":out=record_prediction_snapshot(args.ledger,due_games=[x.strip() for x in str(args.due_games).split(",") if x.strip()])
    else:out=write_report(args.ledger,args.output)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
