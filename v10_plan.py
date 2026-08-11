#!/usr/bin/env python3
"""V10 daily-plan and parlay risk engine."""
import math

MIN_PLAN_CONF=6.20
MIN_COMBO_CONF=6.50
MAX_COMBO_EXPOSURE_PCT=.05

def num(x,d=0.0):
    try:
        y=float(x);return y if math.isfinite(y) else d
    except Exception:return d

def plan_pool(results):
    pool=[]
    for r in results or []:
        for market in ("ML","RUNLINE","TOTAL"):
            rec=(r.get("model_recs") or {}).get(market)
            if not rec:continue
            score=num(rec.get("confidence"))+max(0,num(rec.get("p_model"),.5)-.5)*.80+num(r.get("quality"),.5)*.25
            pool.append({"result":r,"rec":rec,"score":score})
    return sorted(pool,key=lambda x:(x["score"],num(x["rec"].get("confidence")),num(x["rec"].get("p_model"))),reverse=True)

def choose_distinct(pool,n,banned=None,min_conf=None):
    banned={str(x) for x in (banned or set())};used=set();out=[]
    for item in pool:
        gid=str(item["result"].get("game_pk"))
        if gid in banned or gid in used:continue
        if min_conf is not None and num(item["rec"].get("confidence"))<min_conf:continue
        out.append(item);used.add(gid)
        if len(out)>=n:break
    return out

def build_plan(results,min_plan_conf=MIN_PLAN_CONF,min_combo_conf=MIN_COMBO_CONF):
    pool=plan_pool(results);singles=choose_distinct(pool,3,min_conf=min_plan_conf);banned={str(x["result"].get("game_pk")) for x in singles}
    combo=choose_distinct(pool,3,banned=banned,min_conf=min_combo_conf)
    if len(combo)<2:combo=choose_distinct(pool,2,banned=banned,min_conf=min_combo_conf)
    if len(combo)<2:combo=[]
    return singles,combo

def combo_metrics(combo):
    if len(combo)<2:return {"legs":len(combo),"valid":False}
    p_all_win=1.0;p_no_loss=1.0;expected_multiplier=1.0;fair_conditional=1.0;quoted=1.0;min_product=1.0;all_prices=True;all_min=True
    for item in combo:
        rec=item["rec"];pw=num(rec.get("p_win"));pp=num(rec.get("p_push"));pl=num(rec.get("p_loss"));s=pw+pp+pl
        if s<=0:return {"legs":len(combo),"valid":False}
        pw,pp,pl=pw/s,pp/s,pl/s;nonpush=pw+pl
        if nonpush<=0:return {"legs":len(combo),"valid":False}
        e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);minimum=num(rec.get("min_price"),99)
        p_all_win*=pw;p_no_loss*=pw+pp;fair_conditional*=1/(pw/nonpush);min_product*=minimum
        if price<=1:all_prices=False
        else:
            quoted*=price;expected_multiplier*=pw*price+pp
            if price+1e-9<minimum:all_min=False
    return {"legs":len(combo),"valid":True,"p_all_win":p_all_win,"p_no_loss":p_no_loss,"fair_conditional":fair_conditional,"min_product":min_product,"quoted_price":quoted if all_prices else None,"expected_multiplier":expected_multiplier if all_prices else None,"ev":expected_multiplier-1 if all_prices else None,"all_prices":all_prices,"all_legs_above_min":all_min if all_prices else False}

def combo_stake(combo,bankroll,unit,portfolio_allocated,daily_cap,min_ev=.03,max_combo_pct=MAX_COMBO_EXPOSURE_PCT):
    m=combo_metrics(combo)
    if not m.get("valid") or not m.get("all_prices") or not m.get("all_legs_above_min"):return 0.0
    if m.get("ev") is None or m["ev"]<min_ev:return 0.0
    if any(x["result"].get("phase")=="EARLY" for x in combo):return 0.0
    room=max(0.0,num(daily_cap)-num(portfolio_allocated));cap=min(num(bankroll)*max_combo_pct,num(unit),room);q=max(.01,num(unit)/4)
    return round(math.floor((cap/q)+1e-9)*q,2) if cap>=q else 0.0

def self_test():
    def item(g,conf=7.0,pw=.58,pp=0,price=1.90,minimum=1.82,phase="FINAL"):
        return {"result":{"game_pk":g,"phase":phase,"quality":.9},"rec":{"confidence":conf,"p_model":pw/(pw+(1-pw-pp)),"p_win":pw,"p_push":pp,"p_loss":1-pw-pp,"min_price":minimum,"winamax_eval":{"price":price}}}
    pool=[item(1,7.0),item(2,6.8),item(3,5.9),item(4,6.7),item(5,6.6)]
    results=[x["result"]|{"model_recs":{"ML":x["rec"]}} for x in pool];singles,combo=build_plan(results)
    assert len(singles)<=3 and all(x["rec"]["confidence"]>=MIN_PLAN_CONF for x in singles) and all(x["rec"]["confidence"]>=MIN_COMBO_CONF for x in combo)
    assert not ({str(x["result"]["game_pk"]) for x in singles}&{str(x["result"]["game_pk"]) for x in combo})
    m=combo_metrics([item(10,7,.56,.05,1.95,1.84),item(11,7,.57,0,1.90,1.83)]);assert m["p_all_win"]>0 and m["p_no_loss"]>=m["p_all_win"]
    weak=[{"game_pk":20+i,"phase":"FINAL","quality":.8,"model_recs":{"ML":{"confidence":5.5,"p_model":.57,"p_win":.57,"p_push":0,"p_loss":.43,"min_price":1.9,"winamax_eval":{"price":2.0}}}} for i in range(5)]
    s,c=build_plan(weak);assert not s and not c
    print("SELF-TEST V10 PLAN/COMBO OK",m)
if __name__=="__main__":self_test()
