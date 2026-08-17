from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

HIST = Path("data/mlb_backtest_2026.jsonl")
EXACT = Path("data/v13_historical_backfill.jsonl")
OUT = Path("data/v13_run_mean_prior.json")
DISPERSION = 2.835691107635618
MAX_ADJ = 0.75
MIN_WARM = 5
MIN_EXACT_FINAL = 20
RIDGES = (0.0, 10.0, 25.0, 50.0, 100.0, 200.0, 400.0, 800.0)


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _day(r: dict[str,Any]) -> str:
    return str(r.get("game_date") or "")[:10]


def _hist_rows() -> list[dict[str,Any]]:
    out=[]
    with HIST.open("r",encoding="utf-8") as fh:
        for line in fh:
            if not line.strip(): continue
            r=json.loads(line); v=r.get("v10") or {}
            if min(int(r.get("pregame_games_home") or 0),int(r.get("pregame_games_away") or 0)) < MIN_WARM: continue
            hm=v.get("home_mu"); am=v.get("away_mu")
            if hm is None or am is None or r.get("home_score") is None or r.get("away_score") is None: continue
            out.append({"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),"phase":"FINAL_RECONSTRUCTED",
                        "home_mu":_num(hm),"away_mu":_num(am),
                        "home_score":int(_num(r.get("home_score"))),"away_score":int(_num(r.get("away_score")))})
    return sorted(out,key=lambda r:(str(r["game_date"]),str(r["game_pk"])))


def _exact_rows() -> list[dict[str,Any]]:
    """Use only genuine exact FINAL V13 replays for transfer monitoring.

    The prior is FINAL-only. EARLY/LATE exact replays may be useful elsewhere,
    but they must not be presented as exact transfer evidence for this layer.
    """
    if not EXACT.exists(): return []
    best={}
    with EXACT.open("r",encoding="utf-8") as fh:
        for line in fh:
            if not line.strip(): continue
            r=json.loads(line)
            if str(r.get("phase") or "").upper() != "FINAL": continue
            if r.get("home_score") is None or r.get("away_score") is None: continue
            hm=r.get("projected_home_runs"); am=r.get("projected_away_runs")
            if hm is None or am is None: continue
            k=str(r.get("game_pk")); rank=str(r.get("analyzed_at") or "")
            if k not in best or rank > best[k][0]: best[k]=(rank,r)
    out=[]
    for _,r in best.values():
        out.append({"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),"phase":"FINAL",
                    "home_mu":_num(r.get("projected_home_runs")),"away_mu":_num(r.get("projected_away_runs")),
                    "home_score":int(_num(r.get("home_score"))),"away_score":int(_num(r.get("away_score")))})
    return sorted(out,key=lambda r:(str(r["game_date"]),str(r["game_pk"])))


def _split_days(rows):
    days=sorted({_day(r) for r in rows}); n=len(days)
    a=max(1,int(n*.60)); b=max(a+1,int(n*.80))
    tr=set(days[:a]); va=set(days[a:b]); te=set(days[b:])
    return ([r for r in rows if _day(r) in tr],[r for r in rows if _day(r) in va],[r for r in rows if _day(r) in te])


def _solve3(a,b):
    m=[list(a[i])+[b[i]] for i in range(3)]
    for c in range(3):
        p=max(range(c,3),key=lambda r:abs(m[r][c])); m[c],m[p]=m[p],m[c]
        if abs(m[c][c])<1e-12: continue
        d=m[c][c]; m[c]=[x/d for x in m[c]]
        for r in range(3):
            if r==c: continue
            f=m[r][c]; m[r]=[x-f*y for x,y in zip(m[r],m[c])]
    return [m[i][3] for i in range(3)]


def _fit(rows, ridge: float, affine: bool=True):
    ata=[[0.0]*3 for _ in range(3)]; aty=[0.0]*3
    for r in rows:
        for side in ("home","away"):
            mu=max(.1,_num(r[f"{side}_mu"])); y=_num(r[f"{side}_score"])
            x=[1.0 if side=="home" else 0.0,1.0 if side=="away" else 0.0,mu if affine else 0.0]
            target=y-mu
            for i in range(3):
                aty[i]+=x[i]*target
                for j in range(3): ata[i][j]+=x[i]*x[j]
    for i in range(3): ata[i][i]+=ridge
    c=_solve3(ata,aty)
    if not affine: c[2]=0.0
    return {"home_bias":c[0],"away_bias":c[1],"slope_delta":c[2],"ridge":ridge,
            "formula":"mu + side_bias + slope_delta*mu","max_adjustment":MAX_ADJ}


def apply(mu: float, side: str, model: dict[str,Any]) -> float:
    bias=_num(model.get(f"{side}_bias")); sd=_num(model.get("slope_delta"))
    adj=max(-MAX_ADJ,min(MAX_ADJ,bias+sd*mu))
    return max(1.4,mu+adj)


def _nb_nll(mu,y):
    r=DISPERSION; mu=max(.01,mu); y=max(0,int(y)); p=r/(r+mu)
    return -(math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p))


def _metrics(rows,model=None):
    ae=[]; se=[]; nl=[]
    for r in rows:
        for side in ("home","away"):
            base=max(.1,_num(r[f"{side}_mu"])); mu=apply(base,side,model) if model else base; y=_num(r[f"{side}_score"])
            ae.append(abs(mu-y)); se.append((mu-y)**2); nl.append(_nb_nll(mu,y))
    n=len(ae)
    return {"team_observations":n,"mae":sum(ae)/n if n else None,
            "rmse":math.sqrt(sum(se)/n) if n else None,"nb_nll":sum(nl)/n if n else None}


def _gain(rows,model):
    b=_metrics(rows); c=_metrics(rows,model)
    return {"games":len(rows),"baseline":b,"candidate":c,
            "mae_gain":b["mae"]-c["mae"] if b["mae"] is not None else None,
            "rmse_gain":b["rmse"]-c["rmse"] if b["rmse"] is not None else None,
            "nll_gain":b["nb_nll"]-c["nb_nll"] if b["nb_nll"] is not None else None}


def _passes(ev,min_games=20):
    return (ev["games"]>=min_games and ev["rmse_gain"] is not None and ev["nll_gain"] is not None and ev["mae_gain"] is not None
            and ev["rmse_gain"]>0 and ev["nll_gain"]>0 and ev["mae_gain"]>=-0.01)


def build():
    rows=_hist_rows(); train,val,test=_split_days(rows); exact=_exact_rows()
    variants=[]
    for affine in (False,True):
        name="side_bias" if not affine else "side_bias_shared_slope"
        for ridge in RIDGES:
            m=_fit(train,ridge,affine); v=_gain(val,m)
            if _passes(v,100): variants.append((v["nll_gain"],v["rmse_gain"],name,ridge,m,v))
    if not variants:
        return {"schema":"v13-run-mean-prior-v1","active":False,"reason":"no validation-passing candidate",
                "historical_games":len(rows),"exact_final_games":len(exact)}
    variants.sort(reverse=True,key=lambda z:(z[0],z[1]))
    best=variants[0]
    simple=[z for z in variants if z[2]=="side_bias" and z[0]>=best[0]-.001]
    chosen=max(simple,key=lambda z:(z[0],z[1])) if simple else best
    _,_,name,ridge,_,val_ev=chosen
    final=_fit(train+val,ridge,name!="side_bias")
    test_ev=_gain(test,final)
    historical_active=_passes(val_ev,100) and _passes(test_ev,100)
    exact_ready=len(exact)>=MIN_EXACT_FINAL
    exact_ev=_gain(exact,final) if exact else {"games":0,"baseline":{},"candidate":{},"mae_gain":None,"rmse_gain":None,"nll_gain":None}
    exact_passes=_passes(exact_ev,MIN_EXACT_FINAL) if exact_ready else False
    exact_status="PASS_FINAL_ONLY" if exact_ready and exact_passes else "FAIL_FINAL_ONLY" if exact_ready else "COLLECTING_FINAL_ONLY"
    return {"schema":"v13-run-mean-prior-v1","active":bool(historical_active),"phase_scope":"FINAL",
            "source":"1801-game leakage-safe reconstructed FINAL cohort",
            "historical_games":len(rows),"split":{"train":len(train),"validation":len(val),"test":len(test)},
            "exact_games":len(exact),"exact_final_games":len(exact),"exact_phase_counts":{"FINAL":len(exact)},
            "selected_variant":name,"model":final,"validation":val_ev,"test":test_ev,"exact_transfer":exact_ev,
            "exact_transfer_status":exact_status,"exact_transfer_required_games":MIN_EXACT_FINAL,
            "activation_rule":"historical chronological validation and untouched future test must improve RMSE and NB NLL; MAE may not regress by >0.01. Exact V13 FINAL transfer is monitored independently until >=20 genuine FINAL replays.",
            "transfer_caveat":"Exact transfer is FINAL-only and is not used to activate the historical prior while its FINAL sample is below the monitoring floor.",
            "safety":{"historical_odds_used":False,"market_probability_used":False,"feature_vector_fabricated":False,
                      "exact_transfer_used_for_activation":False,"applies_only_when_native_residual_and_legacy_run_bootstrap_are_inactive":True}}


def main():
    report=build(); OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__": main()
