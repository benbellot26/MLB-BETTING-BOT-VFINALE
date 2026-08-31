from __future__ import annotations

"""Small persistent budget for paid Odds snapshots.

This is intentionally expressed in paid request-equivalent snapshots rather than
provider credits because provider pricing can change. The default protects close
capture from runaway schedules while remaining configurable through environment.
Production's normal manually-triggered slate request is not blocked here; this
budget is for automated CLOSE_CAPTURE requests only.
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
DEFAULT_MAX_CLOSE_PER_UTC_DAY=12


def daily_close_limit()->int:
    try: value=int(os.getenv("V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY",str(DEFAULT_MAX_CLOSE_PER_UTC_DAY)))
    except Exception: value=DEFAULT_MAX_CLOSE_PER_UTC_DAY
    return max(1,min(48,value))


def _now(now:datetime|None=None)->datetime:
    out=now or datetime.now(timezone.utc)
    if out.tzinfo is None: out=out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _read(path:Path|str=LEDGER)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists(): return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if isinstance(row,dict) and row.get("schema")==SCHEMA: rows.append(row)
    return rows


def _append(row:dict[str,Any],path:Path|str=LEDGER)->None:
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("a",encoding="utf-8") as handle: handle.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")


def day_key(now:datetime|None=None)->str:return _now(now).date().isoformat()


def used(kind:str=KIND_CLOSE,path:Path|str=LEDGER,*,now:datetime|None=None)->int:
    day=day_key(now)
    return sum(str(r.get("kind") or "")==kind and str(r.get("utc_day") or "")==day for r in _read(path))


def allowance(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    limit=daily_close_limit();count=used(KIND_CLOSE,path,now=now)
    return {"kind":KIND_CLOSE,"utc_day":day_key(now),"used":count,"limit":limit,"remaining":max(0,limit-count),"allowed":count<limit}


def record_close_snapshot(path:Path|str=LEDGER,*,now:datetime|None=None,due_rows:int=0)->dict[str,Any]:
    current=_now(now);before=allowance(path,now=current)
    if not before["allowed"]: raise RuntimeError("automated paid close-snapshot daily budget exhausted")
    row={"schema":SCHEMA,"recorded_at":current.isoformat(),"utc_day":current.date().isoformat(),"kind":KIND_CLOSE,"request_equivalents":1,"due_rows":int(due_rows),"provider_credit_cost":None,"note":"provider credit pricing intentionally not guessed"}
    _append(row,path);return row


def build_report(path:Path|str=LEDGER,*,now:datetime|None=None)->dict[str,Any]:
    rows=_read(path);counts=Counter(str(r.get("kind") or "UNKNOWN") for r in rows);today=allowance(path,now=now)
    return {"schema":"pulsar-v14-api-usage-report-v1","generated_at":_now(now).isoformat(),"request_equivalents_total":sum(int(r.get("request_equivalents") or 0) for r in rows),"by_kind":dict(sorted(counts.items())),"automated_close_today":today,"policy":{"default_max_paid_close_snapshots_per_utc_day":DEFAULT_MAX_CLOSE_PER_UTC_DAY,"config_env":"V14_MAX_PAID_CLOSE_SNAPSHOTS_PER_DAY","provider_credit_cost_not_assumed":True}}


def write_report(path:Path|str=LEDGER,output:Path|str=REPORT,*,now:datetime|None=None)->dict[str,Any]:
    report=build_report(path,now=now);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return report


def main()->None:
    parser=argparse.ArgumentParser(description="Pulsar paid API request-equivalent budget");sub=parser.add_subparsers(dest="command",required=True)
    a=sub.add_parser("allowance");a.add_argument("--ledger",default=str(LEDGER))
    r=sub.add_parser("report");r.add_argument("--ledger",default=str(LEDGER));r.add_argument("--output",default=str(REPORT))
    args=parser.parse_args();out=allowance(args.ledger) if args.command=="allowance" else write_report(args.ledger,args.output);print(json.dumps(out,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
