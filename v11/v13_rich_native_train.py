from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from . import engine_v12 as engine
from . import journal
from . import point_in_time_v13 as pit
from . import v13_rich_run_residual as rich
from .probability_contract_v13 import row_is_predictively_compatible

OUT = Path("data/v13_rich_native_candidate.json")
SCHEMA = "v13-rich-native-candidate-v4"
TARGET_PHASE = "FINAL"
MIN_GAMES = 300
MIN_HOLDOUT = 100
MIN_WF_GAMES = 180
MIN_WF_WINDOWS = 4
MIN_WF_PASS_RATE = .75
MIN_DOWNSTREAM_MARKET = 75
NATIVE_MODULES = ("starter_ip","platoon","statcast","bullpen_player","lineup_player","weather_park")
NATIVE_CANDIDATE_SETS = (
    ("starter_ip",),("platoon",),("statcast",),("bullpen_player",),("lineup_player",),("weather_park",),
    ("starter_ip","statcast"),("starter_ip","platoon"),("lineup_player","platoon"),
    ("bullpen_player","lineup_player"),("statcast","weather_park"),
    ("starter_ip","platoon","statcast"),NATIVE_MODULES,
)


def _day(r: dict[str,Any]) -> str:
    return str(r.get("game_date") or "")[:10]


def _norm(v: Any) -> str:
    return "".join(c.lower() for c in str(v or "") if c.isalnum())


def _means(r: dict[str,Any]):
    hm,am=r.get("hmu"),r.get("amu")
    if hm is not None and am is not None:return rich._num(hm),rich._num(am),"v13_hmu_amu"
    hm,am=r.get("projected_home_runs"),r.get("projected_away_runs")
    if hm is not None and am is not None:return rich._num(hm),rich._num(am),"legacy_projected_runs"
    return None,None,"missing"


def _reject_reason(r: dict[str,Any]) -> str | None:
    if not row_is_predictively_compatible(r): return "predictive_contract_mismatch"
    if r.get("result_status") != "FINAL": return "not_settled_final"
    if r.get("home_score") is None or r.get("away_score") is None: return "scores_missing"
    if str(r.get("phase") or "").upper() != TARGET_PHASE: return "not_final_phase"
    valid,reasons=pit.validate_pregame_row(r)
    if not valid: return "pit:"+"|".join(reasons[:4])
    mods=(r.get("shadow_v124") or {}).get("modules") or {}
    if not mods: return "rich_modules_missing"
    hm,am,_=_means(r)
    if hm is None or am is None: return "base_means_missing"
    if not str(r.get("game_pk") or ""): return "game_pk_missing"
    return None


def _native_rows_with_diagnostics(rows: list[dict[str,Any]]) -> tuple[list[dict[str,Any]],dict[str,int]]:
    best={}; rejected=Counter()
    for r in rows:
        reason=_reject_reason(r)
        if reason:
            rejected[reason]+=1
            continue
        hm,am,source=_means(r)
        gid=str(r.get("game_pk") or "");rank=str(r.get("analyzed_at") or "")
        if gid not in best or rank>best[gid][0]:best[gid]=(rank,r,hm,am,source)
    out=[]
    for _,r,hm,am,source in best.values():
        features=r.get("features") or {}
        out.append({
            "game_pk":r.get("game_pk"),"game_date":r.get("game_date"),
            "home":r.get("home") or ((r.get("ctx") or {}).get("home")),
            "away":r.get("away") or ((r.get("ctx") or {}).get("away")),
            "home_mu":hm,"away_mu":am,"mean_source":source,
            "home_score":r.get("home_score"),"away_score":r.get("away_score"),
            "dispersion":rich._num(features.get("run_dispersion"),7.5),
            "environment_sigma":rich._num(features.get("run_environment_sigma"),.08),
            "options":[dict(o) for o in (r.get("options") or [])],
            "modules":(r.get("shadow_v124") or {}).get("modules") or {},
        })
    return sorted(out,key=lambda r:(_day(r),str(r.get("game_pk")))),dict(sorted(rejected.items()))


def _native_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    return _native_rows_with_diagnostics(rows)[0]


def _split_outer(rows):
    days=sorted({_day(r) for r in rows});hold_days=max(1,int(len(days)*.25));cut=max(1,len(days)-hold_days)
    tr=set(days[:cut]);te=set(days[cut:])
    return [r for r in rows if _day(r) in tr],[r for r in rows if _day(r) in te]


def _walk_forward(rows,selected,ridge):
    days=sorted({_day(r) for r in rows});wins=[]
    if len(rows)<MIN_WF_GAMES:return {"windows":[],"pass_rate":0.0,"passes":False}
    for frac in (.45,.55,.65,.75,.85):
        cut=max(1,int(len(days)*frac));end=min(len(days),cut+max(4,int(len(days)*.08)))
        trd=set(days[:cut]);ted=set(days[cut:end]);tr=[r for r in rows if _day(r) in trd];te=[r for r in rows if _day(r) in ted]
        if len(tr)<120 or len(te)<25:continue
        model=rich._fit(tr,ridge,selected);ev=rich._eval(te,model);passed=rich._passes(ev,25)
        wins.append({"train_games":len(tr),"test_games":len(te),**ev,"passes":passed})
    rate=sum(1 for w in wins if w["passes"])/len(wins) if wins else 0.0
    return {"windows":wins,"pass_rate":rate,"passes":len(wins)>=MIN_WF_WINDOWS and rate>=MIN_WF_PASS_RATE}


def _canonical_option(row: dict[str,Any], market: str) -> dict[str,Any] | None:
    opts=[o for o in (row.get("options") or []) if str(o.get("market") or "").upper()==market and o.get("result") in {"WIN","LOSS"}]
    if not opts:return None
    home=_norm(row.get("home"))
    marked=[o for o in opts if o.get("is_canonical_line")]
    pool=marked or opts
    if market=="ML":
        return next((o for o in pool if _norm(o.get("name"))==home),pool[0])
    if market=="RUNLINE":
        homes=[o for o in pool if _norm(o.get("name"))==home and o.get("point") is not None]
        candidates=homes or [o for o in pool if o.get("point") is not None]
        return min(candidates,key=lambda o:abs(abs(rich._num(o.get("point")))-1.5)) if candidates else None
    overs=[o for o in pool if str(o.get("name") or "").lower()=="over"]
    return (overs or pool)[0]


def _binary_probability(row: dict[str,Any], opt: dict[str,Any], hmu: float, amu: float) -> float:
    market=str(opt.get("market") or "").upper();name=str(opt.get("name") or "")
    disp=rich._num(row.get("dispersion"),7.5);env=rich._num(row.get("environment_sigma"),.08)
    if market=="ML":
        p=engine.prob_home_win(hmu,amu,disp,env)
        return p if _norm(name)==_norm(row.get("home")) else 1-p
    if market=="RUNLINE":
        side="home" if _norm(name)==_norm(row.get("home")) else "away"
        win,push=engine.prob_cover_parts(hmu,amu,side,rich._num(opt.get("point")),disp,env)
        return win/max(1e-9,1-push)
    side="over" if name.lower()=="over" else "under"
    win,push=engine.prob_total_parts(hmu,amu,side,rich._num(opt.get("point")),disp,env)
    return win/max(1e-9,1-push)


def _proper_metrics(items: list[tuple[float,int]]) -> dict[str,Any]:
    if not items:return {"n":0,"brier":None,"logloss":None}
    xs=[(max(.001,min(.999,p)),int(y)) for p,y in items]
    return {"n":len(xs),
            "brier":sum((p-y)**2 for p,y in xs)/len(xs),
            "logloss":sum(-(y*math.log(p)+(1-y)*math.log(1-p)) for p,y in xs)/len(xs)}


def _downstream_eval(rows: list[dict[str,Any]], model: dict[str,Any]) -> dict[str,Any]:
    markets={}
    all_base=[];all_candidate=[]
    for market in ("ML","RUNLINE","TOTAL"):
        base=[];cand=[]
        for r in rows:
            opt=_canonical_option(r,market)
            if not opt:continue
            y=1 if opt.get("result")=="WIN" else 0
            bh,ba=rich._num(r.get("home_mu")),rich._num(r.get("away_mu"))
            ch,_=rich._apply(bh,"home",r.get("modules") or {},model)
            ca,_=rich._apply(ba,"away",r.get("modules") or {},model)
            base.append((_binary_probability(r,opt,bh,ba),y))
            cand.append((_binary_probability(r,opt,ch,ca),y))
        bm=_proper_metrics(base);cm=_proper_metrics(cand)
        gain_b=(bm["brier"]-cm["brier"]) if bm["brier"] is not None else None
        gain_l=(bm["logloss"]-cm["logloss"]) if bm["logloss"] is not None else None
        passed=bool(bm["n"]>=MIN_DOWNSTREAM_MARKET and gain_b is not None and gain_b>0 and gain_l is not None and gain_l>=0)
        markets[market]={"baseline":bm,"candidate":cm,"brier_gain":gain_b,"logloss_gain":gain_l,"passes":passed,
                         "required_n":MIN_DOWNSTREAM_MARKET}
        all_base.extend(base);all_candidate.extend(cand)
    gb=_proper_metrics(all_base);gc=_proper_metrics(all_candidate)
    overall_b=(gb["brier"]-gc["brier"]) if gb["brier"] is not None else None
    overall_l=(gb["logloss"]-gc["logloss"]) if gb["logloss"] is not None else None
    passes=all(markets[m]["passes"] for m in ("ML","RUNLINE","TOTAL")) and overall_b is not None and overall_b>0 and overall_l is not None and overall_l>=0
    return {"by_market":markets,"overall":{"baseline":gb,"candidate":gc,"brier_gain":overall_b,"logloss_gain":overall_l},"passes":passes}


def build(rows: list[dict[str,Any]] | None = None) -> dict[str,Any]:
    source=journal.load_rows() if rows is None else rows
    native,rejections=_native_rows_with_diagnostics(source)
    coverage={name:(sum(max(0.0,min(1.0,rich._num((r.get("modules") or {}).get(name,{}).get("coverage"),0.0))) for r in native)/len(native) if native else 0.0) for name in NATIVE_MODULES}
    base={"schema":SCHEMA,"target_phase":TARGET_PHASE,"native_games":len(native),"minimum_games":MIN_GAMES,"active_for_production":False,"status":"COLLECTING",
          "baseline_role":"heuristic_structural_champion","native_rejection_reasons":rejections,"source_rows":len(source),
          "replacement_policy":"Do not hand-tune production coefficients. Rich/native modules may replace or augment the heuristic champion only after exact current-generation PIT walk-forward, untouched run holdout, and downstream ML/RL/TOTAL proper-score validation.",
          "native_feature_coverage":coverage,"available_native_modules":list(NATIVE_MODULES),
          "safety":{"market_probability_used":False,"historical_reconstruction_used_for_promotion":False,"point_in_time_required":True,
                    "point_in_time_validated_from_feature_provenance":True,"native_predictive_contract_required":True,"phase_specific_training":True,
                    "selector_unchanged_until_promotion":True,"manual_structural_retuning_allowed_without_oos_evidence":False,
                    "weather_requires_native_pregame_snapshot":True,"downstream_probability_gate_required":True}}
    if len(native)<MIN_GAMES:return base
    train,hold=_split_outer(native)
    if len(hold)<MIN_HOLDOUT:
        base.update({"status":"COLLECTING_OUTER_HOLDOUT","train_games":len(train),"holdout_games":len(hold)})
        return base
    candidates=[]
    for selected in NATIVE_CANDIDATE_SETS:
        for ridge in rich.RIDGES:
            wf=_walk_forward(train,selected,ridge)
            if wf.get("passes"):
                gains=[rich._num(w.get("nll_gain")) for w in wf.get("windows") or []]
                candidates.append((sum(gains)/len(gains),-len(selected),-ridge,selected,ridge,wf))
    if not candidates:
        base.update({"status":"NO_STABLE_NATIVE_CANDIDATE","train_games":len(train),"holdout_games":len(hold)})
        return base
    candidates.sort(reverse=True,key=lambda z:z[:3]);_,_,_,selected,ridge,wf=candidates[0]
    model=rich._fit(train,ridge,selected);outer=rich._eval(hold,model);run_pass=rich._passes(outer,MIN_HOLDOUT)
    downstream=_downstream_eval(hold,model);passed=bool(run_pass and downstream.get("passes"))
    status="PROMOTION_ELIGIBLE" if passed else "DOWNSTREAM_PROBABILITY_REJECTED" if run_pass else "OUTER_HOLDOUT_REJECTED"
    base.update({"status":status,"active_for_production":passed,"train_games":len(train),"holdout_games":len(hold),
                 "selection":{"selected_modules":list(selected),"ridge":ridge,"walk_forward":wf},"model":model,
                 "outer_holdout":outer,"downstream_probability_holdout":downstream,
                 "promotion_rule":"FINAL only; >=300 exact PIT V13-contract games; train-only walk-forward >=75%; >=100-game untouched run holdout improves RMSE and NB-NLL with MAE regression <=0.01; same untouched holdout must also improve Brier and not worsen LogLoss for ML, RUNLINE and TOTAL with >=75 independent targets each."})
    return base


def main():
    report=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":main()
