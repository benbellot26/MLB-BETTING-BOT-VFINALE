from __future__ import annotations
import math
from . import config

def _num(x,d=0.0):
    try:
        y=float(x); return y if math.isfinite(y) else d
    except Exception:return d

def required_price(rec):
    p_cond=max(.001,min(.999,_num(rec.get("p_effective",rec.get("p_model")),.5)));push=max(0.0,min(.95,_num(rec.get("p_push"),0)));pwin=rec.get("p_win")
    if pwin is None:pwin=p_cond*(1-push)
    pwin=max(.001,min(.999,_num(pwin,p_cond)));fair=(1-push)/pwin;ev_floor=(1+config.MIN_EV-push)/pwin
    conditional_edge=max(.001,p_cond-config.MIN_EDGE);edge_floor=1/conditional_edge
    return max(fair,ev_floor,edge_floor,1.01)+config.PRICE_SAFETY_MARGIN

def value_gate(rec):
    e=rec.get("winamax_eval") or {};price=_num(e.get("price"),0);minimum=required_price(rec);push=max(0.0,min(.95,_num(rec.get("p_push"),0)));pwin=rec.get("p_win")
    if pwin is None:pwin=_num(rec.get("p_effective"),.5)*(1-push)
    ev=_num(pwin)*(price-1)-(1-_num(pwin)-push) if price>1 else None
    return {"ok":price>1 and price+1e-12>=minimum,"price":price if price>1 else None,"required_price":round(minimum,4),"ev_at_price":round(ev,6) if ev is not None else None,"p_win":round(_num(pwin),6),"p_push":round(push,6)}

def _score(result,rec):
    p=_num(rec.get("p_effective"),.5);conf=_num(rec.get("confidence"),0);q=_num(result.get("quality"),0);refs=int(_num(rec.get("refs"),0));phase=str(result.get("phase","EARLY")).upper();gate=value_gate(rec);ev=max(0.0,_num(gate.get("ev_at_price"),0))
    s=50+155*max(0,p-.5)+2.0*(conf-5)+12*(q-.6)+2*min(refs,4)+(5 if phase=="FINAL" else 2 if phase=="LATE" else 0)+min(8,70*ev)
    return max(0.0,min(100.0,s))

def allocate(results,unit_eur=.5):
    pool=[]
    for r in results:
        for rec in r.get("options") or []:
            e=rec.setdefault("winamax_eval",{});gate=value_gate(rec);score=_score(r,rec)
            e.update({"v11_price_gate":gate,"official_selected":False,"official_units":0,"selected":False,"units":0.0,"stake_eur":0.0,"official_reason":"non retenu par V11"});rec["selection_score"]=round(score,2)
            eligible=gate["ok"] and _num(rec.get("p_effective"),.5)>=.535 and _num(rec.get("confidence"),0)>=5.5 and int(_num(rec.get("refs"),0))>=1
            if eligible:pool.append({"result":r,"rec":rec,"score":score,"gate":gate,"profile":str(rec.get("market") or "OTHER")})
    pool.sort(key=lambda x:(x["score"],_num(x["gate"].get("ev_at_price"),0),_num(x["rec"].get("p_effective"),.5)),reverse=True)
    chosen=[];used_games=set();profiles={};used_units=0.0
    for c in pool:
        if len(chosen)>=config.MAX_OFFICIAL_BETS:break
        threshold=config.OFFICIAL_SCORE_THRESHOLDS[min(len(chosen),len(config.OFFICIAL_SCORE_THRESHOLDS)-1)]
        if c["score"]<threshold:continue
        gid=str(c["result"].get("game_pk"));profile=c["profile"]
        if gid in used_games or profiles.get(profile,0)>=2:continue
        units=2.0 if c["score"]>=86 and str(c["result"].get("phase")).upper()=="FINAL" and _num(c["gate"].get("ev_at_price"),0)>=.055 else 1.0
        if used_units+units>config.MAX_DAILY_UNITS:units=1.0
        if used_units+units>config.MAX_DAILY_UNITS:continue
        e=c["rec"]["winamax_eval"];e.update({"official_selected":True,"official_units":units,"selected":True,"units":units,"stake_eur":round(units*unit_eur,2),"official_reason":f"V11 value gate: score {c['score']:.1f}/100, cote {c['gate']['price']:.2f} >= mini {c['gate']['required_price']:.2f}, EV {100*_num(c['gate'].get('ev_at_price')):+.1f}%"})
        chosen.append(c);used_games.add(gid);profiles[profile]=profiles.get(profile,0)+1;used_units+=units
    legs=[];seen=set()
    for c in pool:
        if c["score"]<74 or _num(c["gate"].get("ev_at_price"),0)<config.MIN_EV:continue
        gid=str(c["result"].get("game_pk"))
        if gid in seen:continue
        legs.append(c);seen.add(gid)
        if len(legs)==2:break
    combo={"available":False,"official":False,"legs":[],"units":0.0,"reason":"moins de 2 legs V11 qualifiés"}
    if len(legs)==2:
        cp=math.prod(_num(c["rec"].get("p_effective"),.5) for c in legs);price=math.prod(_num(c["gate"].get("price"),0) for c in legs);ev=cp*price-1;room=config.MAX_DAILY_UNITS-used_units;official=ev>=config.MIN_COMBO_EV and room+1e-9>=config.COMBO_UNITS
        combo={"available":True,"official":official,"legs":legs,"units":config.COMBO_UNITS if official else 0.0,"probability":cp,"winamax_price":price,"ev":ev,"reason":"retenu V11" if official else ("EV combiné insuffisante" if ev<config.MIN_COMBO_EV else "plafond exposition")}
    total_units=used_units+(combo["units"] if combo.get("official") else 0)
    portfolio={"daily_cap":round(config.MAX_DAILY_UNITS*unit_eur,2),"allocated":round(total_units*unit_eur,2),"remaining":round(max(0,(config.MAX_DAILY_UNITS-total_units)*unit_eur),2),"official_count":len(chosen),"official_units":used_units,"combo_official":bool(combo.get("official")),"combo_units":_num(combo.get("units"),0),"selector_version":"V11-all-markets-value-v2"}
    return portfolio,chosen,combo,pool
