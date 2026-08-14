from __future__ import annotations
from . import core

def sharp_consensus(event,market,name,point=None):
    key={"ML":"h2h","RUNLINE":"spreads","TOTAL":"totals"}[market];probs=[];books=[]
    for b in event.get("bookmakers") or []:
        if b.get("key") not in core.SHARP_BOOKS:continue
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
        inv=[1/core.num(o.get("price")) for o in relevant];s=sum(inv);probs.append((1/core.num(target.get("price")))/s);books.append(b.get("key"))
    return {"p":sum(probs)/len(probs) if probs else None,"n":len(probs),"books":books}
