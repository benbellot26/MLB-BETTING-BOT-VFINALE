from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from . import v138_research_models as rm
from .v138_validation import brier, logloss

SCHEMA = "v13-8-advanced-research-v1"


def _num(v: Any, d: float = 0.0) -> float:
    try:
        x=float(v); return x if math.isfinite(x) else d
    except Exception:return d


def _clip(x: float, lo: float=.001, hi: float=.999) -> float:
    return max(lo,min(hi,float(x)))


def _logit(p: float) -> float:
    q=_clip(p,.001,.999);return math.log(q/(1-q))


def _sigmoid(x: float) -> float:
    if x>=0:
        z=math.exp(-x);return 1/(1+z)
    z=math.exp(x);return z/(1+z)


def fit_platt(probabilities: list[float], outcomes: list[int], l2: float=.1, iterations: int=80) -> dict[str,Any]:
    if len(probabilities)<80 or len(probabilities)!=len(outcomes):
        return {"active":False,"n":len(probabilities),"minimum_n":80}
    a,b=0.0,1.0
    for _ in range(iterations):
        ga=gb=0.0;haa=hbb=hab=0.0
        for p,y in zip(probabilities,outcomes):
            x=_logit(p);q=_sigmoid(a+b*x);w=max(1e-6,q*(1-q));err=q-int(y)
            ga+=err;gb+=err*x;haa+=w;hbb+=w*x*x;hab+=w*x
        ga+=l2*a;gb+=l2*(b-1.0);haa+=l2;hbb+=l2
        det=haa*hbb-hab*hab
        if abs(det)<1e-10:break
        da=(hbb*ga-hab*gb)/det;db=(-hab*ga+haa*gb)/det
        a-=da;b-=db
        if abs(da)+abs(db)<1e-7:break
    calibrated=[_sigmoid(a+b*_logit(p)) for p in probabilities]
    raw_ll=logloss(outcomes,probabilities);cal_ll=logloss(outcomes,calibrated)
    return {"active":True,"n":len(probabilities),"method":"platt","a":a,"b":b,
            "raw_logloss":raw_ll,"calibrated_logloss":cal_ll,"improved_in_sample":bool(cal_ll is not None and raw_ll is not None and cal_ll<raw_ll)}


def apply_platt(model: dict[str,Any], p: float) -> float:
    if not model.get("active"):return _clip(p)
    return _sigmoid(_num(model.get("a"))+_num(model.get("b"),1.0)*_logit(p))


def dynamic_calibration(rows: list[dict[str,Any]], min_window: int=300, max_window: int=1200) -> dict[str,Any]:
    """Fit rolling calibration candidates while keeping promotion separate."""
    usable=[r for r in rows if r.get("outcome") in (0,1) and r.get("p_model") is not None]
    usable.sort(key=lambda r:str(r.get("observed_at") or r.get("game_date") or ""))
    if len(usable)<min_window:
        return {"active":False,"n":len(usable),"minimum_n":min_window,"research_only":True}
    train=usable[-max_window:]
    p=[_clip(_num(r.get("p_model"),.5)) for r in train];y=[int(r["outcome"]) for r in train]
    m=fit_platt(p,y);m.update({"research_only":True,"promotion_eligible":False,"window_n":len(train)})
    return m


def fit_inning_profile(games: list[dict[str,Any]], min_games: int=300) -> dict[str,Any]:
    """Learn expected run share by inning from authenticated inning labels."""
    eligible=[]
    for g in games:
        home=g.get("home_innings");away=g.get("away_innings")
        if isinstance(home,list) and isinstance(away,list) and len(home)>=9 and len(away)>=9:
            eligible.append((home,away))
    if len(eligible)<min_games:
        return {"active":False,"n":len(eligible),"minimum_n":min_games,"research_only":True}
    h=[0.0]*9;a=[0.0]*9
    for home,away in eligible:
        for i in range(9):h[i]+=_num(home[i]);a[i]+=_num(away[i])
    hs=sum(h) or 1.0;asum=sum(a) or 1.0
    return {"active":True,"n":len(eligible),"home_shares":[x/hs for x in h],"away_shares":[x/asum for x in a],
            "research_only":True,"promotion_eligible":False}


def inning_run_means(profile: dict[str,Any], home_mu: float, away_mu: float) -> dict[str,Any]:
    if not profile.get("active"):return {"available":False,"reason":"inning_profile_not_active"}
    return {"available":True,"home":[home_mu*_num(x) for x in profile.get("home_shares") or []],
            "away":[away_mu*_num(x) for x in profile.get("away_shares") or []],"research_only":True}


def fit_contextual_dispersion(rows: list[dict[str,Any]], min_bin: int=80) -> dict[str,Any]:
    """Empirical variance/mean by total-run environment and season regime."""
    bins: dict[str,list[float]]=defaultdict(list)
    for r in rows:
        if r.get("total_runs") is None:continue
        mu=_num(r.get("predicted_total"),9.0);season=str(r.get("season") or "UNK")
        env="LOW" if mu<8 else "HIGH" if mu>=10 else "MID"
        bins[f"{season}:{env}"].append(_num(r.get("total_runs")))
        bins[f"ALL:{env}"].append(_num(r.get("total_runs")))
    out={}
    for key,vals in bins.items():
        if len(vals)<min_bin:continue
        m=sum(vals)/len(vals);var=sum((x-m)**2 for x in vals)/max(1,len(vals)-1)
        out[key]={"n":len(vals),"mean":m,"variance":var,"variance_to_mean":var/max(.1,m)}
    return {"active":bool(out),"bins":out,"minimum_bin":min_bin,"research_only":True,"promotion_eligible":False}


def dispersion_for(model: dict[str,Any], season: Any, predicted_total: float, default: float=7.5) -> float:
    env="LOW" if predicted_total<8 else "HIGH" if predicted_total>=10 else "MID"
    bins=model.get("bins") or {};row=bins.get(f"{season}:{env}") or bins.get(f"ALL:{env}")
    if not row:return default
    ratio=_num(row.get("variance_to_mean"),1.0)
    return max(default*.75,min(default*1.35,default*math.sqrt(max(.5,ratio))))


def fit_season_regimes(rows: list[dict[str,Any]], prior_games: float=300.0) -> dict[str,Any]:
    by: dict[str,list[float]]=defaultdict(list)
    for r in rows:
        if r.get("total_runs") is not None:by[str(r.get("season") or "UNK")].append(_num(r.get("total_runs")))
    all_vals=[x for vals in by.values() for x in vals];global_mean=sum(all_vals)/len(all_vals) if all_vals else 8.9
    regimes={}
    for s,vals in by.items():
        n=len(vals);raw=sum(vals)/n;shrunk=(n*raw+prior_games*global_mean)/(n+prior_games)
        regimes[s]={"n":n,"raw_total_mean":raw,"shrunk_total_mean":shrunk,"factor":shrunk/max(.1,global_mean)}
    return {"global_total_mean":global_mean,"seasons":regimes,"research_only":True,"promotion_eligible":False}


def fit_meta_model(candidate_rows: list[dict[str,Any]], target_home: list[float], target_away: list[float], alpha: float=5.0) -> dict[str,Any]:
    """Stack candidate run predictions with regularized linear meta-model."""
    names=sorted({k for r in candidate_rows for k,v in r.items() if isinstance(v,(list,tuple)) and len(v)==2})
    if len(candidate_rows)<200 or not names:
        return {"active":False,"n":len(candidate_rows),"candidate_names":names,"minimum_n":200}
    X=[[1.0]+[_num(r[n][0]) for n in names] for r in candidate_rows]
    Xa=[[1.0]+[_num(r[n][1]) for n in names] for r in candidate_rows]
    mh=rm.fit_ridge(X,target_home,alpha);ma=rm.fit_ridge(Xa,target_away,alpha)
    return {"active":True,"n":len(candidate_rows),"candidate_names":names,"home_coef":mh,"away_coef":ma,
            "research_only":True,"promotion_eligible":False}


def apply_meta(model: dict[str,Any], candidates: dict[str,tuple[float,float]]) -> tuple[float,float] | None:
    if not model.get("active"):return None
    names=model.get("candidate_names") or []
    if not all(n in candidates for n in names):return None
    xh=[1.0]+[_num(candidates[n][0]) for n in names];xa=[1.0]+[_num(candidates[n][1]) for n in names]
    return max(.15,min(15.0,rm._dot(model.get("home_coef") or [],xh))),max(.15,min(15.0,rm._dot(model.get("away_coef") or [],xa)))


def nonlinear_interactions(context: dict[str,Any]) -> dict[str,float]:
    """Explicit research interaction layer for SP × lineup × park × weather."""
    lineup=_num(context.get("lineup_factor"),1.0);starter=_num(context.get("starter_multiplier"),1.0)
    park=_num(context.get("park_factor"),1.0);weather=_num(context.get("weather_factor"),1.0)
    return {"lineup_x_starter":lineup*starter,"lineup_x_park":lineup*park,"starter_x_weather":starter*weather,
            "four_way":lineup*starter*park*weather}
