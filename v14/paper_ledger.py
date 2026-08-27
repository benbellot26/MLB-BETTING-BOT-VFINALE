from __future__ import annotations

"""Prospective research ledger used to earn market-specific betting certification.

Paper bets emulate executable behavior: the first qualified decision for a
(game, canonical market) is immutable. Repeated EARLY/LATE/FINAL snapshots do
not let the evaluator choose a better entry time after the fact. Only strict,
current-generation, verified-pregame observations are allowed to contribute to
future certification evidence.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION
from .acquisition import canonical_team_name, mlb_schedule, odds_snapshot, parse_time
from .market_lines import DEFAULT_MAX_MARKET_AGE_MINUTES, _book_freshness
from .sharp_market import sharp_consensus

LEDGER=Path("data/v14_paper_bet_ledger.jsonl")
REPORT=Path("data/v14_paper_bet_performance.json")
CLOSE_WINDOW_MINUTES=120.0
CERTIFIED_CLOSE_MAX_MINUTES=15.0
EVENT_TOLERANCE_MINUTES=60.0
EVENT_AMBIGUITY_MARGIN_MINUTES=20.0


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _read(path:Path|str=LEDGER)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists(): return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if isinstance(row,dict) and row.get("schema") in {"pulsar-v14-paper-bet-v1","pulsar-v14-paper-bet-v2","pulsar-v14-paper-bet-v3","pulsar-v14-paper-bet-v4","pulsar-v14-paper-bet-v5","pulsar-v14-paper-bet-v6"}: rows.append(row)
    return rows


def _write(rows:list[dict[str,Any]],path:Path|str=LEDGER)->None:
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows),encoding="utf-8")


def _canonical_market(candidate:dict[str,Any])->str:
    explicit=str(candidate.get("canonical_market") or "")
    if explicit: return explicit
    market=str(candidate.get("market") or ""); selection=str(candidate.get("selection") or "")
    if market=="TOTAL": return "TOTAL_OVER"
    if market=="ML": return "ML"
    if selection in {"home_minus_1_5","away_plus_1_5"}: return "RL_HOME_-1.5"
    if selection in {"away_minus_1_5","home_plus_1_5"}: return "RL_AWAY_-1.5"
    return market or selection


def _row_market(row:dict[str,Any])->str:
    return str(row.get("canonical_market") or "") or _canonical_market({"market":row.get("market"),"selection":row.get("selection")})


def _strictly_pregame(analyzed_at:Any,game_date:Any)->bool:
    try: return parse_time(analyzed_at)<parse_time(game_date)
    except Exception: return False


def _verified_entry_state(result:dict[str,Any])->bool:
    market=result.get("market_snapshot") or {}; sharp=result.get("sharp_market") or {}; execution=result.get("execution_market") or {}
    return market.get("freshness_verified") is True and sharp.get("freshness_verified") is True and execution.get("freshness_verified") is True


def record_payload(payload:dict[str,Any],path:Path|str=LEDGER)->int:
    if payload.get("model_generation")!=MODEL_GENERATION: return 0
    existing=_read(path)
    occupied={(str(r.get("game_pk") or ""),_row_market(r)) for r in existing if str(r.get("game_pk") or "") and _row_market(r)}
    before=len(existing)
    for result in payload.get("results") or []:
        if result.get("model_generation")!=MODEL_GENERATION: continue
        prediction=result.get("v14_prediction") or {}
        if prediction.get("model_generation")!=MODEL_GENERATION: continue
        if (result.get("starter_fallback") or {}).get("degraded"): continue
        analyzed_at=str(result.get("analyzed_at") or payload.get("analyzed_at") or ""); game_date=result.get("game_date")
        if not _strictly_pregame(analyzed_at,game_date): continue
        if not str(result.get("odds_event_id") or ""): continue
        if not _verified_entry_state(result): continue
        raw=prediction.get("raw_probabilities") or prediction.get("probabilities") or {}
        sharp=(result.get("sharp_market") or {}).get("selections") or {}
        total_line=(result.get("canonical_lines") or {}).get("TOTAL"); game_pk=str(result.get("game_pk") or "")
        for candidate in (result.get("decision") or {}).get("candidates") or []:
            if candidate.get("research_ready") is not True or candidate.get("edge_qualified") is not True: continue
            canonical=_canonical_market(candidate); key=(game_pk,canonical)
            if not game_pk or not canonical or key in occupied: continue
            price=_num(candidate.get("price")); execution_book=str(candidate.get("execution_book") or ""); robust_sharp=_num(candidate.get("robust_sharp_edge_pp"))
            if price is None or price<=1 or not execution_book or robust_sharp is None or robust_sharp<=0: continue
            selection=str(candidate.get("selection") or ""); entry_sharp=_num((sharp.get(selection) or {}).get("fair_probability"))
            if entry_sharp is None or not 0<entry_sharp<1: continue
            row={"schema":"pulsar-v14-paper-bet-v6","paper_bet_id":f"{game_pk}:{canonical}","model_generation":MODEL_GENERATION,"game_pk":game_pk,"odds_event_id":result.get("odds_event_id"),"target_date":str(payload.get("target_date") or ""),"game_date":game_date,"analyzed_at":analyzed_at,"home":result.get("home"),"away":result.get("away"),"market":candidate.get("market"),"canonical_market":canonical,"selection":selection,"total_line":total_line,"execution_odds":price,"execution_book":execution_book,"entry_execution_implied_probability":1/price,"probability":candidate.get("probability"),"raw_probability":_num(raw.get(selection)),"lower_probability":candidate.get("lower_probability"),"entry_sharp_probability":entry_sharp,"model_edge_pp":candidate.get("model_edge_pp"),"robust_edge_pp":candidate.get("robust_edge_pp"),"sharp_edge_pp":candidate.get("sharp_edge_pp"),"robust_sharp_edge_pp":robust_sharp,"entry_market_freshness_verified":True,"entry_sharp_freshness_verified":True,"entry_execution_freshness_verified":True,"close_history":[],"close_captured_at":None,"close_minutes_to_game":None,"close_quality":None,"closing_sharp_probability":None,"sharp_fair_close_odds":None,"sharp_clv_pp":None,"certification_clv_pp":None,"execution_close_odds":None,"execution_price_clv_pp":None,"result":None,"flat_1u_profit":None,"home_score":None,"away_score":None,"settled_at":None}
            existing.append(row); occupied.add(key)
    ordered=sorted(existing,key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or ""),_row_market(r),str(r.get("analyzed_at") or "")))
    _write(ordered,path); return len(existing)-before


def _event_for_row(row:dict[str,Any],events:list[dict[str,Any]])->dict[str,Any]|None:
    event_id=str(row.get("odds_event_id") or "")
    if event_id:
        exact=[event for event in events if str(event.get("id") or "")==event_id]
        return exact[0] if len(exact)==1 else None
    home=canonical_team_name(row.get("home")); away=canonical_team_name(row.get("away"))
    try: game_time=parse_time(row.get("game_date"))
    except Exception: return None
    candidates=[]
    for event in events:
        if canonical_team_name(event.get("home_team"))!=home or canonical_team_name(event.get("away_team"))!=away: continue
        try: delta=abs((parse_time(event.get("commence_time"))-game_time).total_seconds())/60
        except Exception: continue
        if delta<=EVENT_TOLERANCE_MINUTES: candidates.append((delta,event))
    candidates.sort(key=lambda x:x[0])
    if not candidates: return None
    if len(candidates)>1 and candidates[1][0]-candidates[0][0]<EVENT_AMBIGUITY_MARGIN_MINUTES: return None
    return candidates[0][1]


def _execution_close(event:dict[str,Any],row:dict[str,Any],*,as_of:str)->float|None:
    book_key=str(row.get("execution_book") or ""); selection=str(row.get("selection") or ""); home=str(event.get("home_team") or ""); away=str(event.get("away_team") or ""); line=_num(row.get("total_line"))
    if not book_key: return None
    book=next((b for b in event.get("bookmakers") or [] if str(b.get("key") or "")==book_key),None)
    if not book or _book_freshness(book,as_of,DEFAULT_MAX_MARKET_AGE_MINUTES)!="VERIFIED_FRESH": return None
    market_key="h2h" if selection.endswith("_ml") else "totals" if selection in {"over","under"} else "spreads"; outcomes=[]
    for market in book.get("markets") or []:
        if str(market.get("key") or "")==market_key: outcomes=market.get("outcomes") or []; break
    name=home if selection.startswith("home") else away if selection.startswith("away") else "Over" if selection=="over" else "Under"; point=None
    if "minus_1_5" in selection: point=-1.5
    elif "plus_1_5" in selection: point=1.5
    elif selection in {"over","under"}: point=line
    for outcome in outcomes:
        if str(outcome.get("name") or "")!=name: continue
        op=_num(outcome.get("point"))
        if point is not None and op!=point: continue
        price=_num(outcome.get("price"))
        if price and price>1: return price
    return None


def capture_close(path:Path|str=LEDGER,*,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->int:
    rows=_read(path); current=now or datetime.now(timezone.utc)
    if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc); pending=[]
    for row in rows:
        if row.get("model_generation")!=MODEL_GENERATION: continue
        try: mins=(parse_time(row.get("game_date"))-current).total_seconds()/60
        except Exception: continue
        if 0<mins<=CLOSE_WINDOW_MINUTES: pending.append((row,mins))
    if not pending: return 0
    events=(events_loader or (lambda:odds_snapshot(api_key=api_key)))(); changed=0; captured=current.isoformat()
    for row,mins in pending:
        event=_event_for_row(row,events); selection=str(row.get("selection") or ""); line=_num(row.get("total_line")) if selection in {"over","under"} else None
        if event is None or (selection in {"over","under"} and line is None): continue
        sharp=sharp_consensus(event,total_line=line,as_of=captured); close=_num((((sharp.get("selections") or {}).get(selection) or {}).get("fair_probability")))
        if close is None or sharp.get("freshness_verified") is not True: continue
        execution_close=_execution_close(event,row,as_of=captured); quality="CERTIFIED_CLOSE" if mins<=CERTIFIED_CLOSE_MAX_MINUTES else "PROVISIONAL_CLOSE"; entry=_num(row.get("entry_sharp_probability")); entry_odds=_num(row.get("execution_odds")); entry_execution=(1/entry_odds) if entry_odds and entry_odds>1 else None
        history=row.get("close_history") if isinstance(row.get("close_history"),list) else []
        history.append({"captured_at":captured,"minutes_to_game":mins,"quality":quality,"sharp_fair_probability":close,"sharp_dispersion_pp":_num((((sharp.get("selections") or {}).get(selection) or {}).get("dispersion_pp"))),"execution_close_odds":execution_close,"odds_event_id":event.get("id")}); row["close_history"]=history
        row["close_captured_at"]=captured; row["close_minutes_to_game"]=mins; row["close_quality"]=quality; row["closing_sharp_probability"]=close; row["sharp_fair_close_odds"]=1/close; row["sharp_clv_pp"]=(close-entry)*100 if entry is not None else None; row["certification_clv_pp"]=(close-entry_execution)*100 if entry_execution is not None else None; row["execution_close_odds"]=execution_close; row["execution_price_clv_pp"]=(1/float(execution_close)-entry_execution)*100 if execution_close and entry_execution is not None else None; changed+=1
    if changed: _write(rows,path)
    return changed


def _grade(selection:str,hs:int,aws:int,line:float|None)->str:
    if selection=="home_ml": return "WIN" if hs>aws else "LOSS"
    if selection=="away_ml": return "WIN" if aws>hs else "LOSS"
    if selection=="home_minus_1_5": return "WIN" if hs-aws>=2 else "LOSS"
    if selection=="away_plus_1_5": return "WIN" if hs-aws<=1 else "LOSS"
    if selection=="away_minus_1_5": return "WIN" if aws-hs>=2 else "LOSS"
    if selection=="home_plus_1_5": return "WIN" if aws-hs<=1 else "LOSS"
    if selection in {"over","under"} and line is not None:
        total=hs+aws
        if total==line: return "PUSH"
        return "WIN" if (selection=="over" and total>line) or (selection=="under" and total<line) else "LOSS"
    return "UNRESOLVED"


def settle(path:Path|str=LEDGER,*,schedule_loader:Callable[[str],list[dict[str,Any]]]|None=None)->int:
    rows=_read(path); loader=schedule_loader or (lambda day:mlb_schedule(day,hydrate="linescore")); by_day=defaultdict(list)
    for row in rows:
        if row.get("model_generation")==MODEL_GENERATION and not row.get("result"): by_day[str(row.get("target_date") or "")].append(row)
    changed=0; now=datetime.now(timezone.utc).isoformat()
    for day,pending in by_day.items():
        if not day: continue
        games={str(g.get("gamePk") or ""):g for g in loader(day)}
        for row in pending:
            game=games.get(str(row.get("game_pk") or "")); status=str(((game or {}).get("status") or {}).get("abstractGameState") or "").lower()
            if status!="final": continue
            teams=(game or {}).get("teams") or {}; hs=_num((teams.get("home") or {}).get("score")); aws=_num((teams.get("away") or {}).get("score"))
            if hs is None or aws is None: continue
            result=_grade(str(row.get("selection") or ""),int(hs),int(aws),_num(row.get("total_line")))
            if result=="UNRESOLVED": continue
            odds=float(row.get("execution_odds") or 0); row.update({"result":result,"flat_1u_profit":odds-1 if result=="WIN" else -1.0 if result=="LOSS" else 0.0,"home_score":int(hs),"away_score":int(aws),"settled_at":now}); changed+=1
    if changed: _write(rows,path)
    return changed


def _ci(values:list[float])->dict[str,Any]:
    if not values: return {"n":0,"mean_clv":None,"positive_rate":None,"mean_clv_ci95_lower":None,"mean_clv_ci95_upper":None}
    mean=sum(values)/len(values); rate=sum(v>0 for v in values)/len(values)
    if len(values)<2: return {"n":len(values),"mean_clv":mean,"positive_rate":rate,"mean_clv_ci95_lower":None,"mean_clv_ci95_upper":None}
    var=sum((v-mean)**2 for v in values)/(len(values)-1); se=math.sqrt(var/len(values))
    return {"n":len(values),"mean_clv":mean,"positive_rate":rate,"mean_clv_ci95_lower":mean-1.96*se,"mean_clv_ci95_upper":mean+1.96*se}


def _canonical_rows(rows:list[dict[str,Any]])->list[dict[str,Any]]:
    earliest={}
    for row in rows:
        if row.get("model_generation")!=MODEL_GENERATION: continue
        if not _strictly_pregame(row.get("analyzed_at"),row.get("game_date")): continue
        game=str(row.get("game_pk") or ""); market=_row_market(row)
        if not game or not market: continue
        key=(game,market); current=earliest.get(key)
        if current is None: earliest[key]=row; continue
        try: older=parse_time(row.get("analyzed_at"))<parse_time(current.get("analyzed_at"))
        except Exception: older=str(row.get("analyzed_at") or "")<str(current.get("analyzed_at") or "")
        if older: earliest[key]=row
    return sorted(earliest.values(),key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or ""),_row_market(r)))


def _latest_timestamp(rows:list[dict[str,Any]],field:str)->str|None:
    parsed=[]
    for row in rows:
        value=row.get(field)
        try: parsed.append((parse_time(value),str(value)))
        except Exception: continue
    return max(parsed,key=lambda x:x[0])[1] if parsed else None


def _slice(rows:list[dict[str,Any]])->dict[str,Any]:
    canonical=_canonical_rows(rows); settled=[r for r in canonical if r.get("result") in {"WIN","LOSS","PUSH"}]; decisions=[r for r in settled if r.get("result")!="PUSH"]; profit=sum(float(r.get("flat_1u_profit") or 0) for r in settled)
    directional=[_num(r.get("sharp_clv_pp")) for r in canonical if r.get("close_quality")=="CERTIFIED_CLOSE"]; directional=[v for v in directional if v is not None]
    certification=[]
    for r in canonical:
        if r.get("close_quality")!="CERTIFIED_CLOSE": continue
        value=_num(r.get("certification_clv_pp"))
        if value is None:
            close=_num(r.get("closing_sharp_probability")); odds=_num(r.get("execution_odds"))
            if close is not None and odds is not None and odds>1: value=(close-1/odds)*100
        if value is not None: certification.append(value)
    execution=[_num(r.get("execution_price_clv_pp")) for r in canonical if r.get("close_quality")=="CERTIFIED_CLOSE"]; execution=[v for v in execution if v is not None]
    certified_rows=[r for r in canonical if r.get("close_quality")=="CERTIFIED_CLOSE"]
    return {"raw_observations":len(rows),"observations":len(canonical),"independent_games":len({str(r.get("game_pk") or "") for r in canonical}),"canonical_policy":"first strict verified edge-qualified pregame row per game x canonical market; immutable","settled":len(settled),"wins":sum(r.get("result")=="WIN" for r in settled),"losses":sum(r.get("result")=="LOSS" for r in settled),"pushes":sum(r.get("result")=="PUSH" for r in settled),"flat_1u_profit":profit,"flat_1u_roi":profit/len(decisions) if decisions else None,"latest_certified_close_at":_latest_timestamp(certified_rows,"close_captured_at"),"latest_settled_at":_latest_timestamp(settled,"settled_at"),"clv":{**_ci(directional),"status":"AVAILABLE" if directional else "UNAVAILABLE","role":"DIAGNOSTIC_ONLY","definition":"entry sharp fair probability to verified <=15m sharp fair close"},"certification_clv":{**_ci(certification),"status":"AVAILABLE" if certification else "UNAVAILABLE","role":"PRIMARY_BETTING_CERTIFICATION","definition":"entry executable implied probability to verified <=15m no-vig sharp fair close"},"execution_clv":{**_ci(execution),"status":"AVAILABLE" if execution else "UNAVAILABLE","role":"SECONDARY_EXECUTION_CERTIFICATION","definition":"entry executable implied probability to same-book fresh <=15m close"}}


def report(rows:list[dict[str,Any]])->dict[str,Any]:
    current=[r for r in rows if r.get("model_generation")==MODEL_GENERATION]; excluded=len(rows)-len(current); overall=_slice(current); by_market={}
    for market in sorted({_row_market(r) for r in current if _row_market(r)}): by_market[market]=_slice([r for r in current if _row_market(r)==market])
    return {"schema":"pulsar-v14-paper-bet-performance-v6","role":"CERTIFICATION_EVIDENCE_ONLY","model_generation":MODEL_GENERATION,"generated_at":datetime.now(timezone.utc).isoformat(),"excluded_other_generation_rows":excluded,**overall,"by_market":by_market,"close_policy":{"certified_max_minutes_to_game":CERTIFIED_CLOSE_MAX_MINUTES,"capture_window_minutes":CLOSE_WINDOW_MINUTES,"event_match":"persisted odds event id is authoritative; strict time/team fallback only for legacy rows without id","execution_close_requires_fresh_book":True,"ml_rl_close_independent_of_total_market":True},"entry_policy":"first strict verified qualifying game x canonical market; no retrospective timing selection"}


def write_report(path:Path|str=LEDGER,output:Path|str=REPORT)->dict[str,Any]:
    out=report(_read(path)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out


def main()->None:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="cmd",required=True)
    rec=sub.add_parser("record"); rec.add_argument("--payload",default="runtime/v14/discord_payload.json"); rec.add_argument("--ledger",default=str(LEDGER))
    cap=sub.add_parser("capture-close"); cap.add_argument("--ledger",default=str(LEDGER))
    st=sub.add_parser("settle"); st.add_argument("--ledger",default=str(LEDGER)); st.add_argument("--report",default=str(REPORT)); args=parser.parse_args()
    if args.cmd=="record": print(f"PULSAR_V14_PAPER_LEDGER added={record_payload(json.loads(Path(args.payload).read_text(encoding='utf-8')),args.ledger)}")
    elif args.cmd=="capture-close": print(f"PULSAR_V14_PAPER_CLOSE captured={capture_close(args.ledger)}")
    else:
        settled_n=settle(args.ledger); out=write_report(args.ledger,args.report); print(f"PULSAR_V14_PAPER_LEDGER settled={settled_n} observations={out['observations']}")

if __name__=="__main__": main()
