from __future__ import annotations

"""Player/component true-talent challenger replacing OPS/ERA aggregates.

This module only composes already PIT-safe shadow evidence.  It is deliberately
small and transparent: richer features must prove incremental OOS value through
ablation rather than being added because they sound baseball-smart.
"""

import math
from typing import Any

ROLE="CHALLENGER_ONLY"


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _clip(v:float,lo:float,hi:float)->float: return max(lo,min(hi,float(v)))


def offense_component(lineup_statcast:dict[str,Any],pitch_matchup:dict[str,Any],baserunning:dict[str,Any]|None=None)->dict[str,Any]:
    xwoba=_num(lineup_statcast.get("xwoba")); hard=_num(lineup_statcast.get("hard_hit_rate")); barrel=_num(lineup_statcast.get("barrel_rate")); kbb=_num(lineup_statcast.get("k_minus_bb_rate")); matchup=_num(pitch_matchup.get("matchup_xwoba")); running=_num((baserunning or {}).get("baserunning_run_adjustment"))
    values=[]
    if xwoba is not None: values.append(((xwoba-.320)/.055,.45,"xwoba"))
    if matchup is not None: values.append(((matchup-.320)/.055,.25,"pitch_mix_matchup"))
    if hard is not None: values.append(((hard-.38)/.08,.10,"hard_hit"))
    if barrel is not None: values.append(((barrel-.08)/.05,.10,"barrel"))
    if kbb is not None: values.append(((kbb-.12)/.10,.10,"k_minus_bb"))
    if not values: return {"role":ROLE,"status":"COLLECTING","auto_activation":False,"reason":"offense evidence missing"}
    weight=sum(w for _v,w,_n in values); score=sum(_clip(v,-1.5,1.5)*w for v,w,_n in values)/weight; run_adjustment=_clip(.30*score+(running or 0.0),-.45,.45)
    return {"role":ROLE,"status":"READY_SHADOW","auto_activation":False,"score":score,"run_adjustment":run_adjustment,"components":[{"name":n,"z":v,"weight":w} for v,w,n in values],"baserunning_run_adjustment":running}


def prevention_component(starter:dict[str,Any],bullpen:dict[str,Any],defense:dict[str,Any],expected_starter_ip:float|None)->dict[str,Any]:
    sx=_num(starter.get("xwoba_allowed")); bx=_num(bullpen.get("xwoba_allowed")); df=_num(defense.get("defense_factor")); cf=_num(defense.get("catcher_factor")); ip=_num(expected_starter_ip)
    missing=[n for n,v in (("starter_xwoba",sx),("bullpen_xwoba",bx),("defense_factor",df),("catcher_factor",cf),("starter_ip",ip)) if v is None]
    if missing: return {"role":ROLE,"status":"COLLECTING","auto_activation":False,"missing":missing}
    sip=_clip(float(ip),3,7); pitching=(sip/9)*(float(sx)/.320)+(1-sip/9)*(float(bx)/.320); combined=_clip(pitching*float(df)*float(cf),.70,1.35)
    return {"role":ROLE,"status":"READY_SHADOW","auto_activation":False,"expected_starter_ip":sip,"pitching_factor":pitching,"prevention_factor":combined,"run_environment_direction":"factor>1 means easier opponent scoring"}


def build(*,statcast:dict[str,Any],pitch_matchup:dict[str,Any],research:dict[str,Any])->dict[str,Any]:
    defense=(research.get("defense_baserunning") or {}); home_usage=(research.get("home_starter_usage") or {}); away_usage=(research.get("away_starter_usage") or {})
    home_off=offense_component(((statcast.get("home") or {}).get("lineup") or {}),((pitch_matchup.get("home_offense") or {})),defense.get("home") or {}); away_off=offense_component(((statcast.get("away") or {}).get("lineup") or {}),((pitch_matchup.get("away_offense") or {})),defense.get("away") or {})
    home_prev=prevention_component(((statcast.get("home") or {}).get("starter") or {}),((statcast.get("home") or {}).get("bullpen") or {}),defense.get("home") or {},_num(home_usage.get("expected_innings"))); away_prev=prevention_component(((statcast.get("away") or {}).get("starter") or {}),((statcast.get("away") or {}).get("bullpen") or {}),defense.get("away") or {},_num(away_usage.get("expected_innings")))
    ready=all(x.get("status")=="READY_SHADOW" for x in (home_off,away_off,home_prev,away_prev))
    return {"schema":"pulsar-v14-true-talent-challenger-v1","role":ROLE,"auto_activation":False,"status":"READY_SHADOW" if ready else "COLLECTING","home_offense":home_off,"away_offense":away_off,"home_prevention":home_prev,"away_prevention":away_prev,"ablation_required":True,"market_probability_used_as_feature":False}
