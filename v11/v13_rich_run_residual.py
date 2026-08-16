from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from . import v124_historical_reconstruction as hist
from . import v124_historical_daily_reconstruction as daily
from . import v13_run_mean_runtime as mean_prior

SCHEMA = "v13-rich-run-residual-v1"
OUT = Path("data/v13_rich_run_residual.json")
EXACT = Path("data/v13_historical_backfill.jsonl")
MODULES = ("starter_ip", "platoon", "statcast", "bullpen_player", "lineup_player")
RIDGES = (25.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0)
MAX_ADJ = 0.55
DISPERSION = 2.835691107635618
MIN_HIST = 1200
MIN_VAL = 250
MIN_TEST = 250
MIN_EXACT = 20


def _num(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d


def _day(r: dict[str, Any]) -> str:
    return str(r.get("game_date") or "")[:10]


def _module_feature(mod: dict[str, Any], side: str) -> float:
    cov = max(0.0, min(1.0, _num(mod.get("coverage"), 0.0)))
    factor = max(.80, min(1.20, _num(mod.get(f"{side}_factor"), 1.0)))
    if cov <= 0 or str(mod.get("status") or "").upper() in {"UNAVAILABLE", "ERROR", "DISABLED"}:
        return 0.0
    return cov * math.log(max(.80, min(1.20, factor)))


def _vector(base_mu: float, side: str, modules: dict[str, Any]) -> list[float]:
    return [
        1.0 if side == "home" else 0.0,
        1.0 if side == "away" else 0.0,
        (_num(base_mu, 4.4) - 4.4) / 1.5,
        *[_module_feature(modules.get(name) or {}, side) for name in MODULES],
    ]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [list(a[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            continue
        m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        m[col] = [x / div for x in m[col]]
        for r in range(n):
            if r == col:
                continue
            f = m[r][col]
            if abs(f) < 1e-15:
                continue
            m[r] = [x - f*y for x, y in zip(m[r], m[col])]
    return [m[i][-1] for i in range(n)]


def _fit(rows: list[dict[str, Any]], ridge: float) -> dict[str, Any]:
    p = 3 + len(MODULES)
    ata = [[0.0]*p for _ in range(p)]
    aty = [0.0]*p
    n = 0
    for r in rows:
        mods = r.get("modules") or {}
        for side in ("home", "away"):
            mu = _num(r.get(f"{side}_mu"), 4.4)
            y = _num(r.get(f"{side}_score"), 0.0)
            x = _vector(mu, side, mods)
            target = y - mu
            n += 1
            for i in range(p):
                aty[i] += x[i]*target
                for j in range(p):
                    ata[i][j] += x[i]*x[j]
    for i in range(2, p):
        ata[i][i] += ridge
    # Side intercepts receive mild shrinkage too, but less than rich effects.
    ata[0][0] += ridge*.10
    ata[1][1] += ridge*.10
    c = _solve(ata, aty)
    return {
        "ridge": ridge,
        "coefficients": c,
        "feature_names": ["home_intercept", "away_intercept", "base_mu_centered", *MODULES],
        "max_adjustment": MAX_ADJ,
        "team_observations": n,
    }


def _apply(mu: float, side: str, modules: dict[str, Any], model: dict[str, Any]) -> tuple[float, float]:
    x = _vector(mu, side, modules)
    coefs = model.get("coefficients") or []
    raw = sum(a*b for a, b in zip(coefs, x)) if len(coefs) == len(x) else 0.0
    adj = max(-MAX_ADJ, min(MAX_ADJ, raw))
    return max(1.4, _num(mu)+adj), adj


def _nb_nll(mu: float, y: int) -> float:
    r = DISPERSION
    mu = max(.01, _num(mu, .01)); y = max(0, int(y))
    p = r/(r+mu)
    return -(math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p))


def _metrics(rows: list[dict[str, Any]], model: dict[str, Any] | None = None) -> dict[str, Any]:
    ae=[]; se=[]; nl=[]
    for r in rows:
        mods = r.get("modules") or {}
        for side in ("home", "away"):
            base = _num(r.get(f"{side}_mu"), 4.4)
            mu = _apply(base, side, mods, model)[0] if model else base
            y = int(_num(r.get(f"{side}_score"), 0.0))
            ae.append(abs(mu-y)); se.append((mu-y)**2); nl.append(_nb_nll(mu,y))
    n=len(ae)
    return {"team_observations":n,"mae":sum(ae)/n if n else None,
            "rmse":math.sqrt(sum(se)/n) if n else None,
            "nb_nll":sum(nl)/n if n else None}


def _eval(rows: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    b=_metrics(rows); c=_metrics(rows,model)
    return {"games":len(rows),"baseline":b,"candidate":c,
            "mae_gain":b["mae"]-c["mae"] if b["mae"] is not None else None,
            "rmse_gain":b["rmse"]-c["rmse"] if b["rmse"] is not None else None,
            "nll_gain":b["nb_nll"]-c["nb_nll"] if b["nb_nll"] is not None else None}


def _split_days(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],list[dict[str, Any]],list[dict[str, Any]]]:
    days=sorted({_day(r) for r in rows}); n=len(days)
    a=max(1,int(n*.60)); b=max(a+1,int(n*.80))
    tr=set(days[:a]); va=set(days[a:b]); te=set(days[b:])
    return ([r for r in rows if _day(r) in tr], [r for r in rows if _day(r) in va], [r for r in rows if _day(r) in te])


def _historical_examples(reconstructed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out=[]
    prior=mean_prior.load()
    for r in reconstructed:
        shadow=r.get("shadow_v124") or {}
        mods=shadow.get("modules") or {}
        if not mods:
            continue
        bh=_num(shadow.get("base_home_mu"),4.4); ba=_num(shadow.get("base_away_mu"),4.2)
        # V13.2 is the baseline. The rich model must add value on top of it.
        h,a,_=mean_prior.apply_pair(bh,ba,"FINAL",prior)
        out.append({"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),
                    "home_mu":h,"away_mu":a,"home_score":r.get("home_score"),"away_score":r.get("away_score"),
                    "modules":mods})
    return out


def _exact_examples() -> list[dict[str, Any]]:
    if not EXACT.exists(): return []
    best={}
    with EXACT.open("r",encoding="utf-8") as fh:
        for line in fh:
            if not line.strip(): continue
            r=json.loads(line); shadow=r.get("shadow_v124") or {}
            mods=shadow.get("modules") or {}
            if not mods or r.get("home_score") is None or r.get("away_score") is None: continue
            gid=str(r.get("game_pk") or ""); rank=str(r.get("analyzed_at") or "")
            if gid and (gid not in best or rank>best[gid][0]): best[gid]=(rank,r)
    out=[]
    for _,r in best.values():
        shadow=r.get("shadow_v124") or {}
        hm=r.get("projected_home_runs"); am=r.get("projected_away_runs")
        if hm is None or am is None: continue
        out.append({"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),
                    "home_mu":_num(hm),"away_mu":_num(am),"home_score":r.get("home_score"),"away_score":r.get("away_score"),
                    "modules":shadow.get("modules") or {}})
    return sorted(out,key=lambda r:(_day(r),str(r.get("game_pk"))))


def _passes(ev: dict[str,Any], min_games: int) -> bool:
    return bool(ev.get("games",0)>=min_games and _num(ev.get("rmse_gain"),-9)>0 and _num(ev.get("nll_gain"),-9)>0 and _num(ev.get("mae_gain"),-9)>=-.01)


def _walk_forward(rows: list[dict[str,Any]], ridge: float) -> dict[str,Any]:
    days=sorted({_day(r) for r in rows})
    windows=[]
    if len(days)<30: return {"windows":[],"pass_rate":0.0,"passes":False}
    starts=[.45,.55,.65,.75,.85]
    for frac in starts:
        cut=max(1,int(len(days)*frac)); end=min(len(days),cut+max(5,int(len(days)*.08)))
        train_days=set(days[:cut]); test_days=set(days[cut:end])
        tr=[r for r in rows if _day(r) in train_days]; te=[r for r in rows if _day(r) in test_days]
        if len(tr)<400 or len(te)<40: continue
        model=_fit(tr,ridge); ev=_eval(te,model); windows.append({"train_games":len(tr),"test_games":len(te),**ev,"passes":_passes(ev,40)})
    rate=sum(1 for w in windows if w["passes"])/len(windows) if windows else 0.0
    return {"windows":windows,"pass_rate":rate,"passes":len(windows)>=4 and rate>=.75}


def build(reconstructed: list[dict[str,Any]]) -> dict[str,Any]:
    rows=_historical_examples(reconstructed); train,val,test=_split_days(rows); exact=_exact_examples()
    candidates=[]
    for ridge in RIDGES:
        m=_fit(train,ridge); ev=_eval(val,m)
        if _passes(ev,MIN_VAL): candidates.append((_num(ev.get("nll_gain")),_num(ev.get("rmse_gain")),ridge,m,ev))
    if not candidates:
        return {"schema":SCHEMA,"status":"REJECTED","active_for_production":False,"shadow_enabled":True,
                "reason":"no validation-passing ridge candidate","historical_games":len(rows),"exact_games":len(exact)}
    candidates.sort(reverse=True,key=lambda z:(z[0],z[1])); _,_,ridge,_,validation=candidates[0]
    model=_fit(train+val,ridge); test_ev=_eval(test,model); wf=_walk_forward(train+val,ridge)
    exact_ev=_eval(exact,model) if exact else {"games":0}
    hist_pass=len(rows)>=MIN_HIST and _passes(validation,MIN_VAL) and _passes(test_ev,MIN_TEST) and wf.get("passes")
    transfer_pass=_passes(exact_ev,MIN_EXACT) if exact else False
    status="TRANSFER_VALIDATED_SHADOW" if hist_pass and transfer_pass else "HISTORICALLY_VALIDATED_SHADOW" if hist_pass else "REJECTED"
    coverage={}
    for name in MODULES:
        vals=[max(0.0,min(1.0,_num((r.get("modules") or {}).get(name,{}).get("coverage"),0.0))) for r in rows]
        coverage[name]=sum(vals)/len(vals) if vals else 0.0
    return {"schema":SCHEMA,"status":status,"shadow_enabled":bool(hist_pass),"active_for_production":False,
            "production_promotion_requires_native_v13_exact_evidence":True,
            "historical_games":len(rows),"split":{"train":len(train),"validation":len(val),"test":len(test)},
            "exact_games":len(exact),"model":model,"validation":validation,"test":test_ev,"walk_forward":wf,"exact_transfer":exact_ev,
            "coverage":coverage,"modules":list(MODULES),
            "safety":{"historical_odds_used":False,"market_probability_used":False,"weather_trained":False,
                      "same_day_results_visible":False,"final_only_historical_identity":True,"affects_selector":False,"affects_staking":False}}


def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--limit",type=int,default=0); parser.add_argument("--no-statcast",action="store_true")
    args=parser.parse_args(argv)
    source=hist._load_rows()
    if args.limit>0: source=source[:args.limit]
    boxes,failures=hist._prefetch_boxes(source)
    reconstructed,recon_fail=daily.reconstruct(source,boxes,use_statcast=not args.no_statcast)
    report=build(reconstructed); report["boxscores_loaded"]=len(boxes); report["reconstruction_failures"]=len(failures)+len(recon_fail)
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__": raise SystemExit(main())
