from __future__ import annotations
import math
from . import config

def _num(x, d=0.0):
    try:
        y = float(x); return y if math.isfinite(y) else d
    except Exception: return d

def required_price(core, rec):
    p = max(.001, min(.999, _num(rec.get("p_effective", rec.get("p_model")), .5))); push = max(0.0, min(.95, _num(rec.get("p_push"), 0)))
    pw = rec.get("p_win")
    if pw is not None:
        pw = max(.001, min(.999, _num(pw, p))); ev_floor = (1 + config.MIN_EV - push) / pw; fair = (1-push) / pw
    else:
        fair = 1 / p; ev_floor = (1 + config.MIN_EV) / p
    edge_floor = 1 / max(.001, p - config.MIN_EDGE); existing = _num(rec.get("min_price_effective", rec.get("min_price")), 0)
    return max(fair, ev_floor, edge_floor, existing, 1.01) + config.PRICE_SAFETY_MARGIN

def value_gate(core, rec):
    e = rec.get("winamax_eval") or {}; price = _num(e.get("price"), 0); minimum = required_price(core, rec); p = max(.001, min(.999, _num(rec.get("p_effective", rec.get("p_model")), .5))); ev = p*price-1 if price>1 else None
    return {"ok": price>1 and price+1e-12>=minimum, "price": price if price>1 else None, "required_price": round(minimum,4), "ev_at_price": round(ev,6) if ev is not None else None}

def _candidate(core, result, rec):
    try: c = core.v1011_candidate(result, rec, True)
    except Exception: c = {"eligible": True, "score": _num(rec.get("selection_official_score"),0), "units": 1}
    gate = value_gate(core, rec); score = _num(rec.get("selection_official_score"), _num(c.get("official_score"), _num(c.get("score"),0)))
    try: profile=core.v1011_profile(rec)
    except Exception: profile=str(rec.get("market") or "UNKNOWN")
    return {"result": result, "rec": rec, "eligible": bool(c.get("eligible")) and gate["ok"], "score": score, "gate": gate, "units": max(1,int(_num(c.get("units"),1))), "profile":profile}

def allocate(core, results):
    pool=[]
    for result in results:
        for rec in core.v1011_iter_options(result):
            e = rec.get("winamax_eval") or {}; gate = value_gate(core, rec)
            if e: e.update({"official_selected":False,"official_units":0,"selected":False,"units":0.0,"stake_eur":0.0,"v11_price_gate":gate,"official_reason":"non retenu par sélecteur V11"})
            c = _candidate(core,result,rec)
            if c["eligible"]: pool.append(c)
    pool.sort(key=lambda c:(c["score"],_num(c["rec"].get("p_effective"),.5)),reverse=True)
    chosen=[]; used_games=set(); used_units=0.0; profiles={}
    for c in pool:
        if len(chosen)>=config.MAX_OFFICIAL_BETS: break
        gid=str(c["result"].get("game_pk")); profile=c["profile"]
        if gid in used_games or profiles.get(profile,0)>=2: continue
        units=float(c["units"])
        if used_units+units>config.MAX_DAILY_UNITS: units=1.0
        if used_units+units>config.MAX_DAILY_UNITS: continue
        e=c["rec"].get("winamax_eval") or {}
        if not e: continue
        e.update({"official_selected":True,"official_units":units,"selected":True,"units":units,"stake_eur":round(units*_num(getattr(core,"UNIT",.5),.5),2),"official_reason":f"retenu V11: Score {c['score']:.1f}/100, cote {c['gate']['price']:.2f} >= mini {c['gate']['required_price']:.2f}","portfolio_reason":"PARI OFFICIEL V11 VALUE-GATED"})
        chosen.append(c); used_games.add(gid); profiles[profile]=profiles.get(profile,0)+1; used_units += units
    combo={"available":False,"official":False,"legs":[],"units":0.0,"reason":"insufficient value-gated legs"}; combo_candidates=[c for c in pool if c["gate"]["price"] and c["score"]>=70]; legs=[]; seen=set()
    for c in combo_candidates:
        gid=str(c["result"].get("game_pk"))
        if gid in seen: continue
        legs.append(c); seen.add(gid)
        if len(legs)==2: break
    if len(legs)==2:
        cp=math.prod(max(.001,min(.999,_num(c["rec"].get("p_effective"),.5))) for c in legs); price=math.prod(c["gate"]["price"] for c in legs); ev=cp*price-1; room=config.MAX_DAILY_UNITS-used_units; official=ev>=config.MIN_COMBO_EV and room+1e-9>=config.COMBO_UNITS
        combo={"available":True,"official":official,"legs":legs,"units":config.COMBO_UNITS if official else 0.0,"probability":cp,"winamax_price":price,"ev":ev,"reason":"retenu V11 value-gated" if official else (f"EV combiné {ev:+.1%} < {config.MIN_COMBO_EV:.1%}" if ev<config.MIN_COMBO_EV else "plafond exposition atteint")}
    if hasattr(core,"_V1007_LAST_SLATE"):
        core._V1007_LAST_SLATE={"score":round(sum(c["score"] for c in chosen)/len(chosen),1) if chosen else 0.0,"grade":"FORT" if chosen and min(c["score"] for c in chosen)>=82 else "BON" if chosen else "FAIBLE","official_count":len(chosen),"units":used_units,"selector_version":"v11-value-gated-v1","combo_official":bool(combo["official"]),"combo_units":combo.get("units",0),"combo_probability":combo.get("probability")}
    if hasattr(core,"_V1013_LAST_COMBO"): core._V1013_LAST_COMBO=combo
    unit=_num(getattr(core,"UNIT",.5),.5); total_units=used_units+(_num(combo.get("units"),0) if combo.get("official") else 0)
    portfolio={"daily_cap":round(config.MAX_DAILY_UNITS*unit,2),"allocated":round(total_units*unit,2),"remaining":round(max(0.0,(config.MAX_DAILY_UNITS-total_units)*unit),2),"game_cap":round(2*unit,2),"official_count":len(chosen),"official_units":used_units,"combo_official":bool(combo.get("official")),"combo_units":_num(combo.get("units"),0),"selector_version":"v11-value-gated-v1","profile_counts":profiles}
    if hasattr(core,"_V10_LAST_PORTFOLIO"): core._V10_LAST_PORTFOLIO=portfolio
    return portfolio,chosen,combo
