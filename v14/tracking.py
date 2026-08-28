from __future__ import annotations

"""Native prediction tracking and settlement for Pulsar V14.

Professional scoring rules are game-paired. Pulsar-vs-sharp gains are computed
on identical games. Raw-vs-calibrated metrics, phase slices and rolling windows
are retained for drift monitoring. Integer-total pushes are excluded from binary
proper scores instead of being mislabeled as losses. Certification-facing
performance is restricted to the exact current probability policy.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .acquisition import mlb_schedule, parse_time
from .pick_tracking import load_pick_performance

PREDICTIONS=Path("data/v14_predictions.jsonl")
PERFORMANCE=Path("data/v14_performance.json")


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _read_jsonl(path:Path|str)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists(): return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if isinstance(row,dict): rows.append(row)
    return rows


def _write_jsonl(path:Path|str,rows:list[dict[str,Any]])->None:
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows),encoding="utf-8")


def _is_strictly_pregame(row:dict[str,Any])->bool:
    try: return parse_time(row.get("analyzed_at"))<parse_time(row.get("game_date"))
    except Exception: return False


def _chronological_key(row:dict[str,Any])->tuple[datetime,datetime,str]:
    minimum=datetime.min.replace(tzinfo=timezone.utc)
    try: game=parse_time(row.get("game_date"))
    except Exception: game=minimum
    try: analyzed=parse_time(row.get("analyzed_at"))
    except Exception: analyzed=minimum
    return game,analyzed,str(row.get("game_pk") or "")


def _row_policy(row:dict[str,Any])->str|None:
    direct=row.get("probability_policy_id")
    if direct: return str(direct)
    nested=(row.get("calibration") or {}).get("probability_policy_id")
    return str(nested) if nested else None


def snapshot_rows(payload:dict[str,Any])->list[dict[str,Any]]:
    if payload.get("model_generation")!=MODEL_GENERATION: raise ValueError("tracking only accepts current V14 generation")
    target_date=str(payload.get("target_date") or ""); rows=[]
    for result in payload.get("results") or []:
        prediction=result.get("v14_prediction") or {}
        if prediction.get("model_generation")!=MODEL_GENERATION: raise ValueError(f"game {result.get('game_pk')} is not current V14")
        calibration=prediction.get("calibration") or {}; policy=calibration.get("probability_policy_id")
        if policy!=PROBABILITY_POLICY_ID: raise ValueError(f"game {result.get('game_pk')} probability policy missing or mismatch")
        analyzed_at=result.get("analyzed_at") or payload.get("analyzed_at"); game_date=result.get("game_date")
        if not _is_strictly_pregame({"analyzed_at":analyzed_at,"game_date":game_date}): raise ValueError(f"game {result.get('game_pk')} tracking snapshot is not strictly pregame")
        probabilities=prediction.get("probabilities") or {}; raw=prediction.get("raw_probabilities") or probabilities; projection=prediction.get("run_projection") or {}; total_line=_num(projection.get("total_line")); total_line=total_line if total_line is not None else _num((result.get("canonical_lines") or {}).get("TOTAL")); keys=("home_ml","away_ml","home_minus_1_5","away_plus_1_5","away_minus_1_5","home_plus_1_5","over","under")
        rows.append({"schema":"pulsar-v14-prediction-record-v6","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"game_pk":str(result.get("game_pk") or ""),"target_date":target_date or str(game_date or "")[:10],"game_date":game_date,"analyzed_at":analyzed_at,"phase":result.get("phase") or prediction.get("phase"),"home":result.get("home"),"away":result.get("away"),"home_mu":_num(projection.get("home_mu")),"away_mu":_num(projection.get("away_mu")),"total_line":total_line,"probabilities":{k:_num(probabilities.get(k)) for k in keys},"raw_probabilities":{k:_num(raw.get(k)) for k in keys},"calibration":calibration,"probability_intervals":prediction.get("probability_intervals") or {},"market_snapshot":result.get("market_snapshot") or {},"market_diagnostics":result.get("market_diagnostics") or {},"sharp_market":result.get("sharp_market") or {},"decision":result.get("decision") or {},"training_features":result.get("training_features") or {},"starter_fallback":result.get("starter_fallback") or {},"settled":False,"home_score":None,"away_score":None,"settled_at":None})
    return rows


def append_snapshot(payload:dict[str,Any],path:Path|str=PREDICTIONS)->int:
    existing=_read_jsonl(path); index={(str(r.get("game_pk") or ""),str(r.get("analyzed_at") or "")):r for r in existing}; before=len(index)
    for row in snapshot_rows(payload):
        key=(str(row.get("game_pk") or ""),str(row.get("analyzed_at") or "")); previous=index.get(key)
        if previous and previous.get("settled"):
            for name in ("settled","home_score","away_score","settled_at"): row[name]=previous.get(name)
        index[key]=row
    _write_jsonl(path,sorted(index.values(),key=_chronological_key)); return len(index)-before


def _final_scores(game:dict[str,Any])->tuple[int,int]|None:
    status=str(((game.get("status") or {}).get("abstractGameState") or "")).lower(); detailed=str(((game.get("status") or {}).get("detailedState") or "")).lower()
    if status!="final" and "final" not in detailed and "completed" not in detailed: return None
    teams=game.get("teams") or {}; home=_num((teams.get("home") or {}).get("score")); away=_num((teams.get("away") or {}).get("score")); return (int(home),int(away)) if home is not None and away is not None else None


def settle_predictions(path:Path|str=PREDICTIONS,*,schedule_loader:Callable[[str],list[dict[str,Any]]]|None=None)->int:
    rows=_read_jsonl(path); loader=schedule_loader or (lambda day:mlb_schedule(day,hydrate="linescore")); by_day=defaultdict(list)
    for row in rows:
        if not row.get("settled"): by_day[str(row.get("target_date") or "")].append(row)
    settled=0; now=datetime.now(timezone.utc).isoformat()
    for day,pending in by_day.items():
        if not day: continue
        games={str(g.get("gamePk") or ""):g for g in loader(day)}
        for row in pending:
            scores=_final_scores(games.get(str(row.get("game_pk") or ""),{}))
            if scores is None: continue
            row["home_score"],row["away_score"]=scores; row["settled"]=True; row["settled_at"]=now; settled+=1
    _write_jsonl(path,rows); return settled


def _calibration(items:list[tuple[float,int]],bins:int=10)->list[dict[str,Any]]:
    grouped=[[] for _ in range(bins)]
    for p,y in items: grouped[min(bins-1,max(0,int(p*bins)))].append((p,y))
    return [{"lower":i/bins,"upper":(i+1)/bins,"n":len(v),"mean_probability":sum(p for p,_ in v)/len(v),"observed_rate":sum(y for _,y in v)/len(v)} for i,v in enumerate(grouped) if v]


def _binary_metrics(items:list[tuple[float,int]])->dict[str,Any]:
    if not items: return {"n":0,"brier":None,"log_loss":None,"accuracy_50":None,"mean_probability":None,"observed_rate":None,"ece":None}
    eps=1e-12; bins=_calibration(items)
    return {"n":len(items),"brier":sum((p-y)**2 for p,y in items)/len(items),"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in items)/len(items),"accuracy_50":sum((p>=.5)==bool(y) for p,y in items)/len(items),"mean_probability":sum(p for p,_ in items)/len(items),"observed_rate":sum(y for _,y in items)/len(items),"ece":sum(row["n"]/len(items)*abs(row["mean_probability"]-row["observed_rate"]) for row in bins)}


def _mean_ci(values:list[float],z:float=1.96)->dict[str,Any]:
    if not values: return {"n":0,"mean":None,"ci95_lower":None,"ci95_upper":None,"std_error":None}
    mean=sum(values)/len(values)
    if len(values)<2: return {"n":len(values),"mean":mean,"ci95_lower":None,"ci95_upper":None,"std_error":None}
    var=sum((x-mean)**2 for x in values)/(len(values)-1); se=math.sqrt(var/len(values)); return {"n":len(values),"mean":mean,"ci95_lower":mean-z*se,"ci95_upper":mean+z*se,"std_error":se}


def _paired_benchmark(items:list[tuple[float,float,int]])->dict[str,Any]:
    if not items: return {"n":0,"paired_n":0,"brier":None,"log_loss":None,"model_paired":_binary_metrics([]),"brier_gain_vs_sharp":None,"logloss_gain_vs_sharp":None,"brier_gain_ci95_lower":None,"logloss_gain_ci95_lower":None}
    eps=1e-12; model=[(m,y) for m,_s,y in items]; sharp=[(s,y) for _m,s,y in items]; brier_diff=[]; ll_diff=[]
    for m,s,y in items:
        brier_diff.append((s-y)**2-(m-y)**2); mll=-(y*math.log(max(eps,min(1-eps,m)))+(1-y)*math.log(max(eps,min(1-eps,1-m)))); sll=-(y*math.log(max(eps,min(1-eps,s)))+(1-y)*math.log(max(eps,min(1-eps,1-s)))); ll_diff.append(sll-mll)
    sm=_binary_metrics(sharp); mm=_binary_metrics(model); bg=_mean_ci(brier_diff); lg=_mean_ci(ll_diff)
    return {**sm,"n":len(items),"paired_n":len(items),"model_paired":mm,"brier_gain_vs_sharp":bg["mean"],"logloss_gain_vs_sharp":lg["mean"],"brier_gain_ci95_lower":bg["ci95_lower"],"brier_gain_ci95_upper":bg["ci95_upper"],"logloss_gain_ci95_lower":lg["ci95_lower"],"logloss_gain_ci95_upper":lg["ci95_upper"],"paired_inference":"paired per-game score differences; normal 95% CI"}


def _canonical_settled(rows:list[dict[str,Any]])->tuple[list[dict[str,Any]],int]:
    records=[r for r in rows if r.get("settled") and r.get("model_generation")==MODEL_GENERATION and _row_policy(r)==PROBABILITY_POLICY_ID and _is_strictly_pregame(r)]; latest={}
    for row in records:
        key=str(row.get("game_pk") or ""); cur=latest.get(key)
        if cur is None or _chronological_key(row)[1]>_chronological_key(cur)[1]: latest[key]=row
    return sorted(latest.values(),key=_chronological_key),len(records)


def _price(row:dict[str,Any],market:str,selection:str)->float|None:
    return _num((((((row.get("market_snapshot") or {}).get("markets") or {}).get(market) or {}).get("selections") or {}).get(selection) or {}).get("price"))


def _sharp_probability(row:dict[str,Any],selection:str)->float|None:
    return _num((((row.get("sharp_market") or {}).get("selections") or {}).get(selection) or {}).get("fair_probability"))


def _market_movement_proxy(rows:list[dict[str,Any]])->dict[str,Any]:
    by_game=defaultdict(list)
    for row in rows:
        if row.get("model_generation")==MODEL_GENERATION and _row_policy(row)==PROBABILITY_POLICY_ID and _is_strictly_pregame(row): by_game[str(row.get("game_pk") or "")].append(row)
    diffs=[]
    for game_rows in by_game.values():
        ordered=sorted(game_rows,key=lambda r:_chronological_key(r)[1])
        if len(ordered)<2: continue
        close=ordered[-1]
        for early in ordered[:-1]:
            for market,sel in (("ML","home"),("ML","away"),("TOTAL","over"),("TOTAL","under")):
                old,new=_price(early,market,sel),_price(close,market,sel)
                if old and new and old>1 and new>1: diffs.append((1/new-1/old)*100)
    return {"status":"AVAILABLE_PROXY" if diffs else "UNAVAILABLE","definition":"market-wide movement to latest persisted pregame price; not bet CLV","n":len(diffs),"mean_implied_probability_move_pp":sum(diffs)/len(diffs) if diffs else None}


def _market_observations(rows:list[dict[str,Any]])->dict[str,dict[str,list[Any]]]:
    out={m:{"model":[],"raw":[],"paired":[],"pushes":0} for m in ("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")}
    for row in rows:
        hs=int(row["home_score"]); aws=int(row["away_score"]); probs=row.get("probabilities") or {}; raw=row.get("raw_probabilities") or probs; line=_num(row.get("total_line")); definitions=[("ML","home_ml",int(hs>aws)),("RL_HOME_-1.5","home_minus_1_5",int(hs-aws>=2)),("RL_AWAY_-1.5","away_minus_1_5",int(aws-hs>=2))]
        if line is not None:
            if abs((hs+aws)-line)<1e-9: out["TOTAL_OVER"]["pushes"]+=1
            else: definitions.append(("TOTAL_OVER","over",int(hs+aws>line)))
        for name,key,y in definitions:
            p=_num(probs.get(key)); rp=_num(raw.get(key)); sp=_sharp_probability(row,key)
            if p is not None: out[name]["model"].append((p,y))
            if rp is not None: out[name]["raw"].append((rp,y))
            if p is not None and sp is not None: out[name]["paired"].append((p,sp,y))
    return out


def _market_report(rows:list[dict[str,Any]])->dict[str,Any]:
    obs=_market_observations(rows); report={}
    for name,data in obs.items():
        metrics=_binary_metrics(data["model"]); metrics["calibration"]=_calibration(data["model"]); metrics["raw_metrics"]=_binary_metrics(data["raw"]); metrics["sharp_benchmark"]=_paired_benchmark(data["paired"]); metrics["pushes_excluded"]=int(data.get("pushes") or 0); report[name]=metrics
    return report


def _phase_segments(rows:list[dict[str,Any]])->dict[str,Any]:
    return {phase:{"games":len(scoped),"markets":_market_report(scoped)} for phase in ("EARLY","LATE","FINAL") if (scoped:=[r for r in rows if str(r.get("phase") or "EARLY").upper()==phase])}


def _quality_segments(rows:list[dict[str,Any]])->dict[str,Any]:
    degraded=[r for r in rows if bool((r.get("starter_fallback") or {}).get("degraded") or (r.get("starter_fallback") or {}).get("degraded_sides"))]; clean=[r for r in rows if r not in degraded]; return {"STARTER_CLEAN":{"games":len(clean),"markets":_market_report(clean)},"STARTER_DEGRADED":{"games":len(degraded),"markets":_market_report(degraded)}}


def _rolling_segments(rows:list[dict[str,Any]])->dict[str,Any]:
    if not rows: return {}
    anchor=max(_chronological_key(r)[0] for r in rows); out={}
    for days in (30,60,90):
        cutoff=anchor-timedelta(days=days); scoped=[r for r in rows if _chronological_key(r)[0]>=cutoff]; out[f"{days}d"]={"games":len(scoped),"through":anchor.isoformat(),"markets":_market_report(scoped)}
    return out


def performance_report(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,record_count=_canonical_settled(rows); markets=_market_report(settled); observations=_market_observations(settled); all_items=[]; run_errors=[]; total_errors=[]
    for values in observations.values(): all_items.extend(values["model"])
    for row in settled:
        hs=int(row["home_score"]); aws=int(row["away_score"]); hmu=_num(row.get("home_mu")); amu=_num(row.get("away_mu"))
        if hmu is not None and amu is not None: run_errors.extend((abs(hmu-hs),abs(amu-aws))); total_errors.append(abs(hmu+amu-hs-aws))
    overall=_binary_metrics(all_items); overall["interpretation"]="dashboard-only; correlated markets must not drive model promotion"
    latest_observation=max((_chronological_key(r)[0] for r in settled),default=None)
    excluded_policy=sum(1 for r in rows if r.get("settled") and r.get("model_generation")==MODEL_GENERATION and _row_policy(r)!=PROBABILITY_POLICY_ID)
    return {"schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":datetime.now(timezone.utc).isoformat(),"latest_observation_at":latest_observation.isoformat() if latest_observation else None,"prediction_records_settled":record_count,"prediction_records_excluded_other_policy":excluded_policy,"games_settled":len(settled),"canonical_snapshot_policy":"latest strictly-pregame snapshot per game, exact game_date ordering, exact probability policy","total_push_policy":"excluded from binary Brier/LogLoss/calibration/benchmark","overall":overall,"calibration":_calibration(all_items),"markets":markets,"segments":{"phase":_phase_segments(settled),"data_quality":_quality_segments(settled),"rolling":_rolling_segments(settled)},"runs":{"team_run_mae":sum(run_errors)/len(run_errors) if run_errors else None,"total_run_mae":sum(total_errors)/len(total_errors) if total_errors else None},"roi":{"status":"UNAVAILABLE","reason":"No certified real-execution sample yet."},"clv":{"status":"UNAVAILABLE","n":0,"mean_clv":None,"reason":"Use authorized/paper ledgers and verified close feed; market movement proxy is separate."},"market_movement_proxy":_market_movement_proxy(rows)}


def write_performance(path:Path|str=PREDICTIONS,report_path:Path|str=PERFORMANCE)->dict[str,Any]:
    report=performance_report(_read_jsonl(path)); report["selection_feedback"]=load_pick_performance()
    try:
        from .certification import evaluate as evaluate_certification
        from .probability_calibration import load_artifact
        report["betting_certification"]=evaluate_certification(report,load_artifact())
    except Exception as exc: report["betting_certification"]={"certified":False,"betting_status":"RESEARCH_ONLY","reasons":[f"certification_error:{type(exc).__name__}"]}
    target=Path(report_path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return report


def main()->None:
    parser=argparse.ArgumentParser(description="Pulsar V14 native prediction tracking"); sub=parser.add_subparsers(dest="command",required=True); snap=sub.add_parser("snapshot"); snap.add_argument("--payload",default="runtime/v14/discord_payload.json"); snap.add_argument("--predictions",default=str(PREDICTIONS)); settle=sub.add_parser("settle"); settle.add_argument("--predictions",default=str(PREDICTIONS)); settle.add_argument("--report",default=str(PERFORMANCE)); rep=sub.add_parser("report"); rep.add_argument("--predictions",default=str(PREDICTIONS)); rep.add_argument("--report",default=str(PERFORMANCE)); args=parser.parse_args()
    if args.command=="snapshot":
        payload=json.loads(Path(args.payload).read_text(encoding="utf-8")); print(f"PULSAR_V14_TRACKING appended={append_snapshot(payload,args.predictions)}")
    elif args.command=="settle":
        settled=settle_predictions(args.predictions); report=write_performance(args.predictions,args.report); print(f"PULSAR_V14_SETTLE settled={settled} games={report['games_settled']}")
    else:
        report=write_performance(args.predictions,args.report); print(f"PULSAR_V14_REPORT games={report['games_settled']}")

if __name__=="__main__": main()
