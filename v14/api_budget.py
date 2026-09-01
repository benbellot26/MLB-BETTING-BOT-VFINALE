from __future__ import annotations

"""Fail-closed budget for every paid The Odds API snapshot used by Pulsar V14.

The production endpoint requests three markets from <=10 bookmakers, so the
reviewed provider contract costs three credits per non-empty snapshot. The user
has a 500-credit/month plan. Pulsar therefore enforces complementary ceilings:

- automated collection: at most 180 locally budgeted credits per UTC month;
- all locally budgeted snapshots (automatic + manual): at most 450 credits per
  UTC month, preserving a 50-credit reserve;
- fresh provider-reported remaining quota: no new paid snapshot may be reserved
  if its conservative expected cost would reduce the provider balance below the
  same 50-credit reserve.

Per-slate limits are keyed by the MLB target date rather than UTC midnight.
Reservations happen before the paid request. A failed request therefore remains
counted and cannot create an unbounded retry loop. Provider quota attestations
are recorded from response headers. Old attestations become advisory-only and
must be refreshed through the provider's zero-credit /sports endpoint before a
production paid reservation.
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
PROVIDER_STATE=Path("runtime/v14/odds_provider_quota.json")
SCHEMA="pulsar-v14-api-usage-v2"
LEGACY_SCHEMA="pulsar-v14-api-usage-v1"
PROVIDER_STATE_SCHEMA="pulsar-v14-odds-provider-quota-v1"
KIND_CLOSE="ODDS_CLOSE_SNAPSHOT"
KIND_PREDICTION="ODDS_SCHEDULED_FINAL_PREDICTION_SNAPSHOT"
KIND_MANUAL="ODDS_MANUAL_PRODUCTION_SNAPSHOT"
KIND_PROVIDER="ODDS_PROVIDER_QUOTA_ATTESTATION"
AUTOMATED_KINDS={KIND_CLOSE,KIND_PREDICTION}
PAID_KINDS={KIND_CLOSE,KIND_PREDICTION,KIND_MANUAL}

DEFAULT_MAX_CLOSE_PER_SLATE=1
DEFAULT_MAX_PREDICTION_PER_SLATE=1
DEFAULT_PROVIDER_CREDITS_PER_SNAPSHOT=3
DEFAULT_MAX_AUTOMATED_PROVIDER_CREDITS_PER_UTC_MONTH=180
DEFAULT_MAX_ALL_PROVIDER_CREDITS_PER_UTC_MONTH=450
TARGET_PLAN_PROVIDER_CREDITS_PER_MONTH=500
DEFAULT_EMERGENCY_RESERVE_CREDITS=TARGET_PLAN_PROVIDER_CREDITS_PER_MONTH-DEFAULT_MAX_ALL_PROVIDER_CREDITS_PER_UTC_MONTH
DEFAULT_PROVIDER_QUOTA_MAX_AGE_MINUTES=360


def _env_int(name:str,default:int,*,low:int=1,high:int=100000)->int:
    try:value=int(os.getenv(name,str(default)))
    except Exception:value=default
    return max(low,min(high,value))


def daily_close_limit()->int:return _env_int("V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_SLATE",_env_int("V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY",DEFAULT_MAX_CLOSE_PER_SLATE,high=48),high=48)
def daily_prediction_limit()->int:return _env_int("V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_SLATE",_env_int("V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_DAY",DEFAULT_MAX_PREDICTION_PER_SLATE,high=48),high=48)
def provider_credits_per_snapshot()->int:return _env_int("V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT",DEFAULT_PROVIDER_CREDITS_PER_SNAPSHOT,high=100)
def provider_reserve_credits()->int:return _env_int("V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS",DEFAULT_EMERGENCY_RESERVE_CREDITS,low=0,high=TARGET_PLAN_PROVIDER_CREDITS_PER_MONTH)
def provider_quota_max_age_minutes()->int:return _env_int("V14_ODDS_PROVIDER_QUOTA_MAX_AGE_MINUTES",DEFAULT_PROVIDER_QUOTA_MAX_AGE_MINUTES,high=1440)
def monthly_automated_credit_limit()->int:return _env_int("V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH",DEFAULT_MAX_AUTOMATED_PROVIDER_CREDITS_PER_UTC_MONTH,high=100000)
def monthly_all_credit_limit()->int:return _env_int("V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH",DEFAULT_MAX_ALL_PROVIDER_CREDITS_PER_UTC_MONTH,high=TARGET_PLAN_PROVIDER_CREDITS_PER_MONTH)


def _now(now:datetime|None=None)->datetime:
    out=now or datetime.now(timezone.utc)
    if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _parse_dt(value:Any)->datetime|None:
    try:
        out=datetime.fromisoformat(str(value or "").replace("Z","+00:00"))
        if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:return None


def _read(path:Path|str=LEDGER)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists():return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:row=json.loads(line)
        except Exception:continue
        if isinstance(row,dict) and row.get("schema") in {SCHEMA,LEGACY_SCHEMA}:rows.append(row)
    return rows


def _append(row:dict[str,Any],path:Path|str=LEDGER)->None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("a",encoding="utf-8") as handle:handle.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")


def _int_or_none(value:Any)->int|None:
    try:return max(0,int(float(value)))
    except Exception:return None


def day_key(now:datetime|None=None)->str:return _now(now).date().isoformat()
def month_key(now:datetime|None=None)->str:return _now(now).strftime("%Y-%m")
def slate_key(slate_date:str|None=None,*,now:datetime|None=None)->str:
    value=str(slate_date or "")[:10]
    return value if len(value)==10 else day_key(now)


def _row_slate(row:dict[str,Any])->str:
    return str(row.get("slate_date") or row.get("target_date") or row.get("utc_day") or "")[:10]


def _row_cost(row:dict[str,Any])->int:
    default=provider_credits_per_snapshot()*int(row.get("request_equivalents") or 0)
    try:return max(0,int(row.get("provider_credit_cost") if row.get("provider_credit_cost") is not None else default))
    except Exception:return max(0,default)


def used(kind:str=KIND_CLOSE,path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None)->int:
    slate=slate_key(slate_date,now=now)
    return sum(str(r.get("kind") or "")==kind and _row_slate(r)==slate for r in _read(path))


def _monthly_usage(kinds:set[str],path:Path|str=LEDGER,*,now:datetime|None=None,limit:int)->dict[str,Any]:
    month=month_key(now);rows=[]
    for row in _read(path):
        if str(row.get("kind") or "") not in kinds:continue
        recorded=str(row.get("recorded_at") or "");row_month=str(row.get("utc_month") or recorded[:7])
        if row_month==month:rows.append(row)
    snapshots=sum(int(r.get("request_equivalents") or 0) for r in rows);credits=sum(_row_cost(r) for r in rows);cost=provider_credits_per_snapshot()
    return {"utc_month":month,"snapshots":snapshots,"provider_credits_used":credits,"provider_credit_limit":limit,"provider_credits_remaining":max(0,limit-credits),"allowed":credits+cost<=limit}


def automated_monthly_usage(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    return _monthly_usage(AUTOMATED_KINDS,path,now=now,limit=monthly_automated_credit_limit())


def all_paid_monthly_usage(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    return _monthly_usage(PAID_KINDS,path,now=now,limit=monthly_all_credit_limit())


def latest_provider_quota(path:Path|str=LEDGER)->dict[str,Any]|None:
    rows=[row for row in _read(path) if str(row.get("kind") or "")==KIND_PROVIDER]
    if not rows:return None
    def key(row:dict[str,Any])->str:return str(row.get("provider_captured_at") or row.get("recorded_at") or "")
    return max(rows,key=key)


def provider_guard(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    current=_now(now);attestation=latest_provider_quota(path);reserve=provider_reserve_credits();configured=provider_credits_per_snapshot();max_age=provider_quota_max_age_minutes()
    if not attestation:
        return {"status":"UNKNOWN_REFRESH_REQUIRED","attested":False,"fresh":False,"allowed":True,"requires_zero_credit_refresh_before_paid_reservation":True,"reserve_credits":reserve,"configured_next_credit_cost":configured,"conservative_next_credit_cost":configured,"credits_remaining_until_provider_reset":None,"credits_after_next_snapshot":None,"max_age_minutes":max_age}
    remaining=_int_or_none(attestation.get("provider_credits_remaining"));last=_int_or_none(attestation.get("provider_last_request_credit_cost"));used_credits=_int_or_none(attestation.get("provider_credits_used"));next_cost=max(configured,last or 0);after=(remaining-next_cost) if remaining is not None else None;captured=_parse_dt(attestation.get("provider_captured_at") or attestation.get("recorded_at"));age=((current-captured).total_seconds()/60.0) if captured is not None else None;same_month=bool(captured and captured.strftime("%Y-%m")==current.strftime("%Y-%m"));fresh=bool(age is not None and 0<=age<=max_age and same_month)
    if not fresh:
        allowed=True;status="STALE_REFRESH_REQUIRED"
    else:
        allowed=True if remaining is None else after>=reserve;status="ATTESTED_SAFE" if allowed else "PROVIDER_RESERVE_REACHED"
    return {"status":status,"attested":True,"fresh":fresh,"allowed":allowed,"requires_zero_credit_refresh_before_paid_reservation":not fresh,"reserve_credits":reserve,"configured_next_credit_cost":configured,"conservative_next_credit_cost":next_cost,"credits_remaining_until_provider_reset":remaining,"credits_used_since_provider_reset":used_credits,"last_request_credit_cost":last,"credits_after_next_snapshot":after,"provider_captured_at":attestation.get("provider_captured_at"),"recorded_at":attestation.get("recorded_at"),"age_minutes":age,"same_utc_month":same_month,"max_age_minutes":max_age,"provider_reset_cycle_guard":True}


def _allowance(kind:str,limit:int,path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None)->dict[str,Any]:
    slate=slate_key(slate_date,now=now);count=used(kind,path,now=now,slate_date=slate);automated=automated_monthly_usage(path,now=now);all_paid=all_paid_monthly_usage(path,now=now);provider=provider_guard(path,now=now);daily_allowed=count<limit
    return {"kind":kind,"slate_date":slate,"used":count,"limit":limit,"remaining":max(0,limit-count),"slate_allowed":daily_allowed,"daily_allowed":daily_allowed,"automated_month":automated,"all_paid_month":all_paid,"provider_guard":provider,"monthly":automated,"allowed":daily_allowed and automated["allowed"] and all_paid["allowed"] and provider["allowed"]}


def allowance(path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None)->dict[str,Any]:
    return _allowance(KIND_CLOSE,daily_close_limit(),path,now=now,slate_date=slate_date)


def prediction_allowance(path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None)->dict[str,Any]:
    return _allowance(KIND_PREDICTION,daily_prediction_limit(),path,now=now,slate_date=slate_date)


def manual_allowance(path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None)->dict[str,Any]:
    all_paid=all_paid_monthly_usage(path,now=now);provider=provider_guard(path,now=now);slate=slate_key(slate_date,now=now);used_on_slate=used(KIND_MANUAL,path,now=now,slate_date=slate)
    return {"kind":KIND_MANUAL,"slate_date":slate,"used":used_on_slate,"limit":None,"remaining":None,"all_paid_month":all_paid,"provider_guard":provider,"allowed":all_paid["allowed"] and provider["allowed"]}


def latest_recorded_at(kind:str,path:Path|str=LEDGER)->datetime|None:
    candidates=[]
    for row in _read(path):
        if str(row.get("kind") or "")!=kind:continue
        value=_parse_dt(row.get("recorded_at"))
        if value is not None:candidates.append(value)
    return max(candidates) if candidates else None


def _budget_error(prefix:str,before:dict[str,Any])->RuntimeError:
    if before.get("slate_allowed") is False or before.get("daily_allowed") is False:return RuntimeError(f"{prefix} slate budget exhausted")
    if not (before.get("provider_guard") or {}).get("allowed",True):return RuntimeError(f"{prefix} provider-reported emergency reserve reached")
    if not (before.get("all_paid_month") or {}).get("allowed",True):return RuntimeError(f"{prefix} all-paid monthly hard cap exhausted")
    return RuntimeError(f"{prefix} automated monthly provider-credit budget exhausted")


def _usage_row(kind:str,current:datetime,*,slate_date:str|None,due_rows:int,due_games:list[str]|None=None,note:str)->dict[str,Any]:
    cost=provider_credits_per_snapshot();slate=slate_key(slate_date,now=current)
    row={"schema":SCHEMA,"recorded_at":current.isoformat(),"utc_day":current.date().isoformat(),"utc_month":current.strftime("%Y-%m"),"slate_date":slate,"kind":kind,"request_equivalents":1,"due_rows":int(due_rows),"provider_credit_cost":cost,"note":note}
    if due_games is not None:row["due_games"]=due_games
    return row


def record_close_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None,due_rows:int=0)->dict[str,Any]:
    current=_now(now);before=allowance(path,now=current,slate_date=slate_date)
    if not before["allowed"]:raise _budget_error("automated paid close-snapshot",before)
    row=_usage_row(KIND_CLOSE,current,slate_date=slate_date,due_rows=due_rows,note="MLB-slate-budgeted automated close snapshot; reserved before paid request")
    _append(row,path);return row


def record_prediction_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None,due_games:list[str]|None=None)->dict[str,Any]:
    current=_now(now);before=prediction_allowance(path,now=current,slate_date=slate_date)
    if not before["allowed"]:raise _budget_error("automated paid prediction-snapshot",before)
    ids=sorted({str(game) for game in (due_games or []) if str(game)})
    row=_usage_row(KIND_PREDICTION,current,slate_date=slate_date,due_rows=len(ids),due_games=ids,note="MLB-slate-budgeted scheduled FINAL prediction snapshot; reserved before paid request")
    _append(row,path);return row


def record_manual_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None)->dict[str,Any]:
    current=_now(now);before=manual_allowance(path,now=current,slate_date=slate_date)
    if not before["allowed"]:raise _budget_error("manual paid production snapshot",before)
    row=_usage_row(KIND_MANUAL,current,slate_date=slate_date,due_rows=0,note="manual production snapshot; reserved before paid request and included in 450-credit hard cap")
    _append(row,path);return row


def record_provider_quota(path:Path|str=LEDGER,*,state_path:Path|str=PROVIDER_STATE,now:datetime|None=None)->dict[str,Any]:
    state_file=Path(state_path)
    if not state_file.exists():return {"recorded":False,"reason":"provider quota sidecar missing"}
    try:state=json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as exc:raise ValueError("provider quota sidecar is invalid JSON") from exc
    if not isinstance(state,dict) or state.get("schema")!=PROVIDER_STATE_SCHEMA or state.get("provider")!="THE_ODDS_API" or state.get("credentials_persisted") is not False:raise ValueError("provider quota sidecar lost audited schema/provider/privacy contract")
    captured=str(state.get("captured_at") or "");remaining=_int_or_none(state.get("credits_remaining_until_provider_reset"));used_credits=_int_or_none(state.get("credits_used_since_provider_reset"));last=_int_or_none(state.get("last_request_credit_cost"))
    if not captured or (remaining is None and used_credits is None and last is None):raise ValueError("provider quota sidecar contains no usable quota attestation")
    latest=latest_provider_quota(path)
    if latest and str(latest.get("provider_captured_at") or "")==captured and _int_or_none(latest.get("provider_credits_remaining"))==remaining and _int_or_none(latest.get("provider_credits_used"))==used_credits and _int_or_none(latest.get("provider_last_request_credit_cost"))==last:return {"recorded":False,"reason":"duplicate provider quota attestation","provider_captured_at":captured}
    current=_now(now);row={"schema":SCHEMA,"recorded_at":current.isoformat(),"utc_day":current.date().isoformat(),"utc_month":current.strftime("%Y-%m"),"kind":KIND_PROVIDER,"request_equivalents":0,"provider_credit_cost":0,"provider":"THE_ODDS_API","provider_captured_at":captured,"provider_credits_remaining":remaining,"provider_credits_used":used_credits,"provider_last_request_credit_cost":last,"credentials_persisted":False,"note":"provider-reported quota headers captured from zero-credit probe or paid response; attestation itself costs zero"};_append(row,path);return {"recorded":True,"row":row,"provider_guard":provider_guard(path,now=current)}


def build_report(path:Path|str=LEDGER,*,now:datetime|None=None,slate_date:str|None=None)->dict[str,Any]:
    rows=_read(path);counts=Counter(str(r.get("kind") or "UNKNOWN") for r in rows);close_today=allowance(path,now=now,slate_date=slate_date);prediction_today=prediction_allowance(path,now=now,slate_date=slate_date);manual=manual_allowance(path,now=now,slate_date=slate_date);automated=automated_monthly_usage(path,now=now);all_paid=all_paid_monthly_usage(path,now=now);provider=provider_guard(path,now=now);known_credits=sum(_row_cost(r) for r in rows if str(r.get("kind") or "") in PAID_KINDS)
    return {"schema":"pulsar-v14-api-usage-report-v5","generated_at":_now(now).isoformat(),"request_equivalents_total":sum(int(r.get("request_equivalents") or 0) for r in rows if str(r.get("kind") or "") in PAID_KINDS),"known_provider_credits_total":known_credits,"by_kind":dict(sorted(counts.items())),"automated_close_slate":close_today,"automated_prediction_slate":prediction_today,"manual_slate":manual,"automated_month":automated,"all_paid_month":all_paid,"provider_guard":provider,"policy":{"default_max_paid_close_snapshots_per_mlb_slate":DEFAULT_MAX_CLOSE_PER_SLATE,"close_config_env":"V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_SLATE","default_max_paid_prediction_snapshots_per_mlb_slate":DEFAULT_MAX_PREDICTION_PER_SLATE,"prediction_config_env":"V14_MAX_PAID_PREDICTION_SNAPSHOTS_PER_SLATE","default_provider_credits_per_snapshot":DEFAULT_PROVIDER_CREDITS_PER_SNAPSHOT,"provider_credit_cost_env":"V14_ODDS_PROVIDER_CREDITS_PER_SNAPSHOT","default_max_automated_provider_credits_per_utc_month":DEFAULT_MAX_AUTOMATED_PROVIDER_CREDITS_PER_UTC_MONTH,"monthly_automated_credit_config_env":"V14_MAX_AUTOMATED_ODDS_CREDITS_PER_UTC_MONTH","default_max_all_provider_credits_per_utc_month":DEFAULT_MAX_ALL_PROVIDER_CREDITS_PER_UTC_MONTH,"monthly_all_credit_config_env":"V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH","provider_emergency_reserve_config_env":"V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS","provider_quota_max_age_config_env":"V14_ODDS_PROVIDER_QUOTA_MAX_AGE_MINUTES","default_provider_quota_max_age_minutes":DEFAULT_PROVIDER_QUOTA_MAX_AGE_MINUTES,"provider_headers_attested_when_available":True,"zero_credit_provider_refresh_required_before_production_paid_reservation":True,"provider_reset_cycle_guard":True,"manual_prediction_runs_budgeted":True,"target_plan_provider_credits_per_month":TARGET_PLAN_PROVIDER_CREDITS_PER_MONTH,"hard_reserved_emergency_credits_at_default_policy":DEFAULT_EMERGENCY_RESERVE_CREDITS,"mlb_slate_keyed_limits":True,"policy_mode":"ULTRA_LOW_SLATEDATE_LOCAL_CAP_PLUS_FRESH_PROVIDER_GUARD"}}


def write_report(path:Path|str=LEDGER,output:Path|str=REPORT,*,now:datetime|None=None,slate_date:str|None=None)->dict[str,Any]:
    report=build_report(path,now=now,slate_date=slate_date);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return report


def main()->None:
    parser=argparse.ArgumentParser(description="Pulsar paid API budget");sub=parser.add_subparsers(dest="command",required=True)
    a=sub.add_parser("allowance");a.add_argument("--ledger",default=str(LEDGER));a.add_argument("--slate-date")
    pa=sub.add_parser("prediction-allowance");pa.add_argument("--ledger",default=str(LEDGER));pa.add_argument("--slate-date")
    ma=sub.add_parser("monthly-allowance");ma.add_argument("--ledger",default=str(LEDGER))
    aa=sub.add_parser("all-paid-monthly-allowance");aa.add_argument("--ledger",default=str(LEDGER))
    pg=sub.add_parser("provider-guard");pg.add_argument("--ledger",default=str(LEDGER))
    rq=sub.add_parser("record-provider-state");rq.add_argument("--ledger",default=str(LEDGER));rq.add_argument("--state",default=str(PROVIDER_STATE))
    rp=sub.add_parser("record-prediction");rp.add_argument("--ledger",default=str(LEDGER));rp.add_argument("--due-games",default="");rp.add_argument("--slate-date")
    rm=sub.add_parser("record-manual");rm.add_argument("--ledger",default=str(LEDGER));rm.add_argument("--slate-date")
    r=sub.add_parser("report");r.add_argument("--ledger",default=str(LEDGER));r.add_argument("--output",default=str(REPORT));r.add_argument("--slate-date")
    args=parser.parse_args()
    if args.command=="allowance":out=allowance(args.ledger,slate_date=args.slate_date)
    elif args.command=="prediction-allowance":out=prediction_allowance(args.ledger,slate_date=args.slate_date)
    elif args.command=="monthly-allowance":out=automated_monthly_usage(args.ledger)
    elif args.command=="all-paid-monthly-allowance":out=all_paid_monthly_usage(args.ledger)
    elif args.command=="provider-guard":out=provider_guard(args.ledger)
    elif args.command=="record-provider-state":out=record_provider_quota(args.ledger,state_path=args.state)
    elif args.command=="record-prediction":out=record_prediction_snapshot(args.ledger,slate_date=args.slate_date,due_games=[x.strip() for x in str(args.due_games).split(",") if x.strip()])
    elif args.command=="record-manual":out=record_manual_snapshot(args.ledger,slate_date=args.slate_date)
    else:out=write_report(args.ledger,args.output,slate_date=args.slate_date)
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
