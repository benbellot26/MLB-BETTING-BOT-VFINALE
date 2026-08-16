from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Any

from . import v124_historical_reconstruction as hist
from . import v124_historical_daily_reconstruction as daily
from . import v13_run_mean_runtime as mean_prior

SCHEMA = "v13-rich-run-residual-v2"
OUT = Path("data/v13_rich_run_residual.json")
EXACT = Path("data/v13_historical_backfill.jsonl")
MODULES = ("starter_ip", "platoon", "statcast", "bullpen_player", "lineup_player")
# Predeclared model family. Selection happens only inside historical train.
CANDIDATE_SETS = (
    ("starter_ip",), ("platoon",), ("statcast",), ("bullpen_player",), ("lineup_player",),
    ("starter_ip", "statcast"), ("starter_ip", "platoon"), ("platoon", "statcast"),
    ("starter_ip", "platoon", "statcast"),
    MODULES,
)
RIDGES = (10.0, 25.0, 50.0, 100.0, 200.0, 400.0, 800.0)
MAX_ADJ = 0.45
DISPERSION = 2.835691107635618
MIN_HIST = 1200
MIN_VAL = 250
MIN_TEST = 250
MIN_EXACT = 20


def _num(v: Any, d: float = 0.0) -> float:
    try:
        x=float(v); return x if math.isfinite(x) else d
    except Exception:
        return d


def _day(r: dict[str,Any]) -> str:
    return str(r.get("game_date") or "")[:10]


def _module_feature(mod: dict[str,Any], side: str, base_mu: float) -> float:
    cov=max(0.0,min(1.0,_num(mod.get("coverage"),0.0)))
    factor=max(.80,min(1.20,_num(mod.get(f"{side}_factor"),1.0)))
    if cov<=0 or str(mod.get("status") or "").upper() in {"UNAVAILABLE","ERROR","DISABLED"}:
        return 0.0
    # Translate a multiplicative module signal to run units. V13.2 already
    # handles the global mean/bias, so this model learns module residuals only.
    return _num(base_mu,4.4)*cov*math.log(factor)


def _vector(base_mu: float, side: str, modules: dict[str,Any], selected: tuple[str,...] | list[str]) -> list[float]:
    return [_module_feature(modules.get(name) or {},side,base_mu) for name in selected]


def _solve(a,b):
    n=len(b); m=[list(a[i])+[b[i]] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(m[r][col]))
        if abs(m[pivot][col])<1e-12: continue
        m[col],m[pivot]=m[pivot],m[col]
        div=m[col][col]; m[col]=[x/div for x in m[col]]
        for r in range(n):
            if r==col: continue
            f=m[r][col]
            if abs(f)<1e-15: continue
            m[r]=[x-f*y for x,y in zip(m[r],m[col])]
    return [m[i][-1] for i in range(n)]


def _fit(rows: list[dict[str,Any]], ridge: float, selected: tuple[str,...] | list[str]) -> dict[str,Any]:
    selected=tuple(selected); p=len(selected)
    ata=[[0.0]*p for _ in range(p)]; aty=[0.0]*p; n=0
    for r in rows:
        mods=r.get("modules") or {}
        for side in ("home","away"):
            mu=_num(r.get(f"{side}_mu"),4.4); y=_num(r.get(f"{side}_score"),0.0)
            x=_vector(mu,side,mods,selected); target=y-mu; n+=1
            for i in range(p):
                aty[i]+=x[i]*target
                for j in range(p): ata[i][j]+=x[i]*x[j]
    for i in range(p): ata[i][i]+=ridge
    return {"ridge":ridge,"selected_modules":list(selected),"coefficients":_solve(ata,aty),
            "max_adjustment":MAX_ADJ,"team_observations":n}


def _apply(mu: float, side: str, modules: dict[str,Any], model: dict[str,Any]) -> tuple[float,float]:
    selected=tuple(model.get("selected_modules") or [])
    x=_vector(mu,side,modules,selected); coefs=model.get("coefficients") or []
    raw=sum(a*b for a,b in zip(coefs,x)) if len(coefs)==len(x) else 0.0
    adj=max(-MAX_ADJ,min(MAX_ADJ,raw))
    return max(1.4,_num(mu)+adj),adj


def _nb_nll(mu,y):
    r=DISPERSION; mu=max(.01,_num(mu,.01)); y=max(0,int(y)); p=r/(r+mu)
    return -(math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p))


def _metrics(rows,model=None):
    ae=[];se=[];nl=[]
    for r in rows:
        mods=r.get("modules") or {}
        for side in ("home","away"):
            base=_num(r.get(f"{side}_mu"),4.4); mu=_apply(base,side,mods,model)[0] if model else base
            y=int(_num(r.get(f"{side}_score"),0.0)); ae.append(abs(mu-y));se.append((mu-y)**2);nl.append(_nb_nll(mu,y))
    n=len(ae)
    return {"team_observations":n,"mae":sum(ae)/n if n else None,"rmse":math.sqrt(sum(se)/n) if n else None,"nb_nll":sum(nl)/n if n else None}


def _eval(rows,model):
    b=_metrics(rows);c=_metrics(rows,model)
    return {"games":len(rows),"baseline":b,"candidate":c,
            "mae_gain":b["mae"]-c["mae"] if b["mae"] is not None else None,
            "rmse_gain":b["rmse"]-c["rmse"] if b["rmse"] is not None else None,
            "nll_gain":b["nb_nll"]-c["nb_nll"] if b["nb_nll"] is not None else None}


def _split_days(rows):
    days=sorted({_day(r) for r in rows}); n=len(days); a=max(1,int(n*.60));b=max(a+1,int(n*.80))
    tr=set(days[:a]);va=set(days[a:b]);te=set(days[b:])
    return ([r for r in rows if _day(r) in tr],[r for r in rows if _day(r) in va],[r for r in rows if _day(r) in te])


def _historical_examples(reconstructed):
    prior=mean_prior.load();out=[]
    for r in reconstructed:
        shadow=r.get("shadow_v124") or {};mods=shadow.get("modules") or {}
        if not mods: continue
        bh=_num(shadow.get("base_home_mu"),4.4);ba=_num(shadow.get("base_away_mu"),4.2)
        h,a,_=mean_prior.apply_pair(bh,ba,"FINAL",prior)
        out.append({"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),"home_mu":h,"away_mu":a,
                    "home_score":r.get("home_score"),"away_score":r.get("away_score"),"modules":mods})
    return out


def _exact_examples():
    if not EXACT.exists(): return []
    best={}
    with EXACT.open("r",encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():continue
            r=json.loads(line);mods=(r.get("shadow_v124") or {}).get("modules") or {}
            if not mods or r.get("home_score") is None or r.get("away_score") is None:continue
            gid=str(r.get("game_pk") or "");rank=str(r.get("analyzed_at") or "")
            if gid and (gid not in best or rank>best[gid][0]):best[gid]=(rank,r)
    out=[]
    for _,r in best.values():
        hm=r.get("projected_home_runs");am=r.get("projected_away_runs")
        if hm is None or am is None:continue
        out.append({"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),"home_mu":_num(hm),"away_mu":_num(am),
                    "home_score":r.get("home_score"),"away_score":r.get("away_score"),"modules":(r.get("shadow_v124") or {}).get("modules") or {}})
    return sorted(out,key=lambda r:(_day(r),str(r.get("game_pk"))))


def _passes(ev,min_games):
    return bool(ev.get("games",0)>=min_games and _num(ev.get("rmse_gain"),-9)>0 and _num(ev.get("nll_gain"),-9)>0 and _num(ev.get("mae_gain"),-9)>=-.01)


def _walk_forward(rows,ridge,selected):
    days=sorted({_day(r) for r in rows});windows=[]
    for frac in (.35,.45,.55,.65,.75):
        cut=max(1,int(len(days)*frac));end=min(len(days),cut+max(5,int(len(days)*.08)))
        trd=set(days[:cut]);ted=set(days[cut:end]);tr=[r for r in rows if _day(r) in trd];te=[r for r in rows if _day(r) in ted]
        if len(tr)<300 or len(te)<40:continue
        m=_fit(tr,ridge,selected);ev=_eval(te,m);windows.append({"train_games":len(tr),"test_games":len(te),**ev,"passes":_passes(ev,40)})
    rate=sum(1 for w in windows if w["passes"])/len(windows) if windows else 0.0
    return {"windows":windows,"pass_rate":rate,"passes":len(windows)>=4 and rate>=.75}


def _select_inside_train(train):
    candidates=[]
    for selected in CANDIDATE_SETS:
        for ridge in RIDGES:
            wf=_walk_forward(train,ridge,selected)
            if not wf.get("passes"):continue
            gains=[_num(w.get("nll_gain")) for w in wf.get("windows") or []]
            rmse=[_num(w.get("rmse_gain")) for w in wf.get("windows") or []]
            candidates.append((sum(gains)/len(gains),sum(rmse)/len(rmse),-len(selected),-ridge,selected,ridge,wf))
    if not candidates:return None
    candidates.sort(reverse=True,key=lambda z:z[:4]);return candidates[0]


def build(reconstructed):
    rows=_historical_examples(reconstructed);train,val,test=_split_days(rows);exact=_exact_examples()
    selected=_select_inside_train(train)
    coverage={name:sum(max(0.0,min(1.0,_num((r.get("modules") or {}).get(name,{}).get("coverage"),0.0))) for r in rows)/len(rows) if rows else 0.0 for name in MODULES}
    if selected is None:
        return {"schema":SCHEMA,"status":"REJECTED","shadow_enabled":False,"active_for_production":False,
                "reason":"no train-only walk-forward-stable module set","historical_games":len(rows),"exact_games":len(exact),"coverage":coverage}
    _,_,_,_,mods,ridge,selection_wf=selected
    discovery_model=_fit(train,ridge,mods);validation=_eval(val,discovery_model)
    model=_fit(train+val,ridge,mods);test_ev=_eval(test,model);exact_ev=_eval(exact,model) if exact else {"games":0}
    hist_pass=len(rows)>=MIN_HIST and _passes(validation,MIN_VAL) and _passes(test_ev,MIN_TEST)
    transfer_pass=_passes(exact_ev,MIN_EXACT) if exact else False
    status="TRANSFER_VALIDATED_SHADOW" if hist_pass and transfer_pass else "HISTORICALLY_VALIDATED_SHADOW" if hist_pass else "REJECTED"
    return {"schema":SCHEMA,"status":status,"shadow_enabled":bool(hist_pass),"active_for_production":False,
            "production_promotion_requires_native_v13_exact_evidence":True,
            "historical_games":len(rows),"split":{"train":len(train),"validation":len(val),"test":len(test)},"exact_games":len(exact),
            "selection":{"method":"train-only walk-forward; fixed candidate families","selected_modules":list(mods),"ridge":ridge,"walk_forward":selection_wf},
            "model":model,"validation":validation,"test":test_ev,"exact_transfer":exact_ev,"coverage":coverage,"available_modules":list(MODULES),
            "weather_policy":"excluded from historical training because no archived pregame forecasts exist; collect natively only",
            "safety":{"historical_odds_used":False,"market_probability_used":False,"weather_trained":False,"same_day_results_visible":False,
                      "final_only_historical_identity":True,"affects_selector":False,"affects_staking":False}}


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument("--limit",type=int,default=0);parser.add_argument("--no-statcast",action="store_true")
    args=parser.parse_args(argv);source=hist._load_rows()
    if args.limit>0:source=source[:args.limit]
    boxes,failures=hist._prefetch_boxes(source);reconstructed,recon_fail=daily.reconstruct(source,boxes,use_statcast=not args.no_statcast)
    report=build(reconstructed);report["boxscores_loaded"]=len(boxes);report["reconstruction_failures"]=len(failures)+len(recon_fail)
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True));return 0

if __name__=="__main__":raise SystemExit(main())
