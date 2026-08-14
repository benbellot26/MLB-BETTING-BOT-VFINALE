from __future__ import annotations
import math
from datetime import datetime, timezone
from . import core, config

def _age_minutes(book):
    s=book.get("last_update") or book.get("lastUpdate")
    if not s:return 0.0
    try:
        dt=core.parse_dt(s);return max(0.0,(datetime.now(timezone.utc)-dt).total_seconds()/60.0)
    except Exception:return 0.0

def sharp_consensus(event,market,name,point=None):
    key={"ML":"h2h","RUNLINE":"spreads","TOTAL":"totals"}[market];vals=[];books=[];ages=[]
    for b in event.get("bookmakers") or []:
        if b.get("key") not in core.SHARP_BOOKS:continue
        age=_age_minutes(b)
        if age>config.MAX_SHARP_AGE_MIN:continue
        m=next((x for x in b.get("markets") or [] if x.get("key")==key),None)
        if not m:continue
        relevant=[]
        for o in m.get("outcomes") or []:
            if point is not None:
                op=core.num(o.get("point"),999)
                if market=="RUNLINE":
                    if abs(abs(op)-abs(core.num(point)))>1e-6:continue
                elif abs(op-core.num(point))>1e-6:continue
            if core.num(o.get("price"),0)>1:relevant.append(o)
        if len(relevant)<2:continue
        target=next((o for o in relevant if core.norm_name(o.get("name"))==core.norm_name(name) and (point is None or market!="RUNLINE" or abs(core.num(o.get("point"))-core.num(point))<1e-6)),None)
        if target is None:continue
        inv=[1/core.num(o.get("price")) for o in relevant];s=sum(inv)
        if s<=0:continue
        p=(1/core.num(target.get("price")))/s
        freshness=max(.25,1-age/max(1.0,config.MAX_SHARP_AGE_MIN)*.75)
        vals.append((p,freshness));books.append(b.get("key"));ages.append(age)
    if not vals:return {"p":None,"n":0,"books":[],"dispersion":None,"max_age_min":None,"robustness":0.0}
    wsum=sum(w for _,w in vals);p=sum(v*w for v,w in vals)/wsum
    variance=sum(w*(v-p)**2 for v,w in vals)/wsum if wsum else 0.0;disp=math.sqrt(max(0.0,variance));robust=max(.35,min(1.0,1-disp/max(.001,config.SHARP_DISAGREEMENT_SCALE)))
    return {"p":p,"n":len(vals),"books":books,"dispersion":disp,"max_age_min":max(ages) if ages else None,"robustness":robust}
