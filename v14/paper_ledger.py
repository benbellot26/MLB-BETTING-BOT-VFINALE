from __future__ import annotations

"""Prospective research ledger used to earn betting certification.

Only edge-qualified candidates with active calibration, verified fresh execution
prices, verified sharp consensus and non-degraded starter data enter this ledger.
They remain PAPER observations until the independent certification gate passes.
Closing sharp probability is captured prospectively near first pitch; it is never
backfilled from a fabricated historical price.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from .acquisition import canonical_team_name, mlb_schedule, odds_snapshot, parse_time
from .sharp_market import sharp_consensus

LEDGER=Path("data/v14_paper_bet_ledger.jsonl")
REPORT=Path("data/v14_paper_bet_performance.json")
CLOSE_WINDOW_MINUTES=75.0
EVENT_TOLERANCE_MINUTES=90.0


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception:return None
    return out if math.isfinite(out) else None


def _read(path:Path|str=LEDGER)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists():return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:r=json.loads(line)
        except Exception:continue
        if isinstance(r,dict) and r.get("schema")=="pulsar-v14-paper-bet-v1":rows.append(r)
    return rows


def _write(rows:list[dict[str,Any]],path:Path|str=LEDGER)->None:
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows),encoding="utf-8")


def record_payload(payload:dict[str,Any],path:Path|str=LEDGER)->int:
    existing=_read(path); index={(str(r.get("game_pk")),str(r.get("selection")),str(r.get("analyzed_at"))):r for r in existing}; before=len(index)
    for result in payload.get("results") or []:
        if (result.get("starter_fallback") or {}).get("degraded"):continue
        prediction=result.get("v14_prediction") or {}; raw=prediction.get("raw_probabilities") or prediction.get("probabilities") or {}; sharp=(result.get("sharp_market") or {}).get("selections") or {}; total_line=(result.get("canonical_lines") or {}).get("TOTAL")
        for row in (result.get("decision") or {}).get("candidates") or []:
            if row.get("research_ready") is not True or row.get("edge_qualified") is not True:continue
            selection=str(row.get("selection") or ""); analyzed_at=str(result.get("analyzed_at") or payload.get("analyzed_at") or ""); key=(str(result.get("game_pk") or ""),selection,analyzed_at)
            if key in index:continue
            index[key]={"schema":"pulsar-v14-paper-bet-v1","model_generation":payload.get("model_generation"),"game_pk":str(result.get("game_pk") or ""),"target_date":str(payload.get("target_date") or ""),"game_date":result.get("game_date"),"analyzed_at":analyzed_at,"home":result.get("home"),"away":result.get("away"),"market":row.get("market"),"selection":selection,"total_line":total_line,"execution_odds":row.get("price"),"probability":row.get("probability"),"raw_probability":_num(raw.get(selection)),"lower_probability":row.get("lower_probability"),"entry_sharp_probability":_num((sharp.get(selection) or {}).get("fair_probability")),"model_edge_pp":row.get("model_edge_pp"),"robust_edge_pp":row.get("robust_edge_pp"),"sharp_edge_pp":row.get("sharp_edge_pp"),"close_captured_at":None,"closing_sharp_probability":None,"sharp_clv_pp":None,"result":None,"flat_1u_profit":None,"home_score":None,"away_score":None,"settled_at":None}
    ordered=sorted(index.values(),key=lambda r:(str(r.get("target_date")),str(r.get("game_pk")),str(r.get("selection")),str(r.get("analyzed_at"))))); _write(ordered,path); return len(index)-before


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


def capture_close(path:Path|str=LEDGER,*,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->int:
    rows=_read(path); current=now or datetime.now(timezone.utc); current=current if current.tzinfo else current.replace(tzinfo=timezone.utc); pending=[]
    for row in rows:
        try:mins=(parse_time(row.get("game_date"))-current.astimezone(timezone.utc)).total_seconds()/60.0
        except Exception:continue
        if 0<mins<=CLOSE_WINDOW_MINUTES:pending.append(row)
    if not pending:return 0
    events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))(); changed=0; captured_at=current.astimezone(timezone.utc).isoformat()
    for row in pending:
        event=_event_for_row(row,events)
        if event is None:continue
        total_line=_num(row.get("total_line"))
        if total_line is None:continue
        sharp=sharp_consensus(event,total_line=total_line,as_of=captured_at); close=_num((((sharp.get("selections") or {}).get(str(row.get("selection") or "")) or {}).get("fair_probability")))
        if close is None or sharp.get("freshness_verified") is not True:continue
        entry=_num(row.get("entry_sharp_probability")); previous=row.get("close_captured_at")
        if previous:
            try:
                if parse_time(previous)>=current.astimezone(timezone.utc):continue
            except Exception:pass
        row["close_captured_at"]=captured_at; row["closing_sharp_probability"]=close; row["sharp_clv_pp"]=(close-entry)*100 if entry is not None else None; changed+=1
    if changed:_write(rows,path)
    return changed


def _grade(selection:str,hs:int,aws:int,line:float|None)->str:
    if selection=="home_ml":return "WIN" if hs>aws else "LOSS"
    if selection=="away_ml":return "WIN" if aws>hs else "LOSS"
    if selection=="home_minus_1_5":return "WIN" if hs-aws>=2 else "LOSS"
    if selection=="away_plus_1_5":return "WIN" if hs-aws<=1 else "LOSS"
    if selection=="away_minus_1_5":return "WIN" if aws-hs>=2 else "LOSS"
    if selection=="home_plus_1_5":return "WIN" if aws-hs<=1 else "LOSS"
    if selection=="over" and line is not None:
        total=hs+aws; return "WIN" if total>line else ("PUSH" if total==line else "LOSS")
    if selection=="under" and line is not None:
        total=hs+aws; return "WIN" if total<line else ("PUSH" if total==line else "LOSS")
    return "UNRESOLVED"


def settle(path:Path|str=LEDGER,*,schedule_loader:Callable[[str],list[dict[str,Any]]]|None=None)->int:
    rows=_read(path); loader=schedule_loader or (lambda day:mlb_schedule(day,hydrate="linescore")); by_day=defaultdict(list)
    for row in rows:
        if not row.get("result"):by_day[str(row.get("target_date") or "")].append(row)
    now=datetime.now(timezone.utc).isoformat(); changed=0
    for day,pending in by_day.items():
        if not day:continue
        games={str(g.get("gamePk") or ""):g for g in loader(day)}
        for row in pending:
            game=games.get(str(row.get("game_pk") or "")); status=str(((game or {}).get("status") or {}).get("abstractGameState") or "").lower()
            if status!="final":continue
            teams=(game or {}).get("teams") or {}; hs=_num((teams.get("home") or {}).get("score")); aws=_num((teams.get("away") or {}).get("score"))
            if hs is None or aws is None:continue
            result=_grade(str(row.get("selection") or ""),int(hs),int(aws),_num(row.get("total_line")))
            if result=="UNRESOLVED":continue
            odds=float(row.get("execution_odds") or 0); row["result"]=result; row["flat_1u_profit"]=(odds-1) if result=="WIN" else (-1.0 if result=="LOSS" else 0.0); row["home_score"]=int(hs); row["away_score"]=int(aws); row["settled_at"]=now; changed+=1
    if changed:_write(rows,path)
    return changed


def report(rows:list[dict[str,Any]])->dict[str,Any]:
    settled_rows=[r for r in rows if r.get("result") in {"WIN","LOSS","PUSH"}]; decisions=[r for r in settled_rows if r.get("result")!="PUSH"]; profit=sum(float(r.get("flat_1u_profit") or 0) for r in settled_rows); clv=[_num(r.get("sharp_clv_pp")) for r in rows]; clv=[x for x in clv if x is not None]
    return {"schema":"pulsar-v14-paper-bet-performance-v1","role":"CERTIFICATION_EVIDENCE_ONLY","observations":len(rows),"settled":len(settled_rows),"wins":sum(r.get("result")=="WIN" for r in settled_rows),"losses":sum(r.get("result")=="LOSS" for r in settled_rows),"pushes":sum(r.get("result")=="PUSH" for r in settled_rows),"flat_1u_profit":profit,"flat_1u_roi":profit/len(decisions) if decisions else None,"clv":{"status":"AVAILABLE" if clv else "UNAVAILABLE","n":len(clv),"mean_clv":sum(clv)/len(clv) if clv else None,"positive_rate":sum(x>0 for x in clv)/len(clv) if clv else None,"definition":"entry-to-latest captured verified sharp fair-probability move at <=75 minutes pregame; same selection/line only"}}


def write_report(path:Path|str=LEDGER,output:Path|str=REPORT)->dict[str,Any]:
    out=report(_read(path)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out


def main()->None:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="cmd",required=True); rec=sub.add_parser("record"); rec.add_argument("--payload",default="runtime/v14/discord_payload.json"); rec.add_argument("--ledger",default=str(LEDGER)); cap=sub.add_parser("capture-close"); cap.add_argument("--ledger",default=str(LEDGER)); st=sub.add_parser("settle"); st.add_argument("--ledger",default=str(LEDGER)); st.add_argument("--report",default=str(REPORT)); args=parser.parse_args()
    if args.cmd=="record":
        payload=json.loads(Path(args.payload).read_text(encoding="utf-8")); print(f"PULSAR_V14_PAPER_LEDGER added={record_payload(payload,args.ledger)}")
    elif args.cmd=="capture-close":print(f"PULSAR_V14_PAPER_CLOSE captured={capture_close(args.ledger)}")
    else:
        n=settle(args.ledger); out=write_report(args.ledger,args.report); print(f"PULSAR_V14_PAPER_LEDGER settled={n} observations={out['observations']}")

if __name__=="__main__":main()
