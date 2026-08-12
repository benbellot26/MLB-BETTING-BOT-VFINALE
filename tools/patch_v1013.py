from pathlib import Path

p=Path('bot.py')
s=p.read_text(encoding='utf-8')
marker='if __name__=="__main__":\n'
if marker not in s:
    raise SystemExit('main marker not found')
if 'V10.0.13 OFFICIAL COMBO' in s:
    print('V10.0.13 already applied')
    raise SystemExit(0)

layer=r'''

# ==================== V10.0.13 OFFICIAL COMBO =====================
# Reintroduces one conservative 2-leg parlay as part of the official daily plan.
# The combo is derived from the expanded V10.0.11 option pool, never uses two
# legs from the same game, never uses Winamax price/availability as a selection
# gate, and stays inside the existing 4u total daily exposure cap.
_V1012_SELF_TEST_013=v10_self_test
_V1012_ALLOCATE_013=allocate_portfolio
_V1012_MAKE_RUN_ROWS_013=v1010_make_run_rows
_V1012_SETTLE_JOURNAL_013=v1010_settle_journal

VERSION="10.0.13"
SELECTION_VERSION="phase-open-plus-combo-v4"
V1013_COMBO_UNITS=clamp(float(os.getenv("V1013_COMBO_UNITS","0.5") or .5),.25,1.0)
V1013_COMBO_MIN_CONF=max(6.5,float(os.getenv("V1013_COMBO_MIN_CONF","6.8") or 6.8))
V1013_COMBO_MIN_QUALITY=max(.60,float(os.getenv("V1013_COMBO_MIN_QUALITY","0.70") or .70))
V1013_COMBO_MIN_REFS=max(2,int(os.getenv("V1013_COMBO_MIN_REFS","2") or 2))
V1013_COMBO_MIN_SCORE=max(70.0,float(os.getenv("V1013_COMBO_MIN_SCORE","74") or 74))
V1013_COMBO_EDGE_EFFECTIVE=.01
_V1013_LAST_COMBO=None


def v1013_combo_min_probability(rec):
    return V1007_MIN_EFFECTIVE.get(rec.get("market"),.60)+V1013_COMBO_EDGE_EFFECTIVE


def v1013_combo_pool(results):
    pool=[]
    for c in v1011_build_slate(results,False)["pool"]:
        r=c["result"];rec=c["rec"];pe=num(rec.get("p_effective"),.5);conf=num(rec.get("confidence"),0)
        if pe+1e-12<v1013_combo_min_probability(rec):continue
        if conf<V1013_COMBO_MIN_CONF:continue
        if num(r.get("quality"),0)<V1013_COMBO_MIN_QUALITY:continue
        if int(num(rec.get("refs"),0))<V1013_COMBO_MIN_REFS:continue
        if str(r.get("stability_alert","OK")).upper()!="OK":continue
        if num(c.get("score"),0)<V1013_COMBO_MIN_SCORE:continue
        pool.append(c)
    phase_rank={"FINAL":3,"LATE":2,"EARLY":1};market_rank={"ML":3,"RUNLINE":2,"TOTAL":1}
    pool.sort(key=lambda c:(
        1 if (v1012_ensure_execution(c["rec"])).get("official_selected") else 0,
        num(c.get("score"),0),phase_rank.get(str(c["result"].get("phase","EARLY")).upper(),0),
        market_rank.get(c["rec"].get("market"),0),num(c["rec"].get("p_effective"),.5),num(c["rec"].get("confidence"),0)
    ),reverse=True)
    return pool


def v1013_pick_combo(pool,simple_units):
    legs=[];seen_games=set()
    for c in pool:
        gid=str(c["result"].get("game_pk"))
        if not gid or gid in seen_games:continue
        legs.append(c);seen_games.add(gid)
        if len(legs)==2:break
    if len(legs)<2:
        return {"available":False,"official":False,"legs":legs,"units":0.0,"reason":"moins de 2 options suffisamment fortes sur des matchs différents"}
    combined_p=1.0;prices=[]
    for c in legs:
        combined_p*=clamp(num(c["rec"].get("p_effective"),.5),.001,.999)
        price=num(v1012_ensure_execution(c["rec"]).get("price"),0);prices.append(price if price>1 else None)
    combined_price=math.prod(prices) if all(x is not None for x in prices) else None
    room=num(V1007_MAX_DAILY_UNITS,4)-num(simple_units,0)
    official=room+1e-9>=V1013_COMBO_UNITS
    return {"available":True,"official":official,"legs":legs,"units":V1013_COMBO_UNITS if official else 0.0,
            "requested_units":V1013_COMBO_UNITS,"probability":combined_p,"winamax_price":combined_price,
            "reason":"retenu dans le plan officiel" if official else f"plafond quotidien {V1007_MAX_DAILY_UNITS}u déjà utilisé par les simples"}


def v1013_build_combo(results,simple_units):
    return v1013_pick_combo(v1013_combo_pool(results),simple_units)


def allocate_portfolio(results):
    global _V1013_LAST_COMBO,_V10_LAST_PORTFOLIO
    portfolio=_V1012_ALLOCATE_013(results)
    simple_units=num((_V1007_LAST_SLATE or {}).get("units"),0)
    combo=v1013_build_combo(results,simple_units) if results else {"available":False,"official":False,"legs":[],"units":0.0,"reason":"aucun match analysé"}
    _V1013_LAST_COMBO=combo
    combo_units=num(combo.get("units"),0) if combo.get("official") else 0.0
    combo_stake=round(combo_units*UNIT,2)
    portfolio["combo_units"]=combo_units;portfolio["combo_stake_eur"]=combo_stake;portfolio["combo_official"]=bool(combo.get("official"));portfolio["combo_reason"]=combo.get("reason")
    if combo.get("official"):
        portfolio["allocated"]=round(num(portfolio.get("allocated"),0)+combo_stake,2)
        portfolio["remaining"]=round(max(0,num(portfolio.get("daily_cap"),0)-portfolio["allocated"]),2)
    _V10_LAST_PORTFOLIO=portfolio
    if isinstance(_V1007_LAST_SLATE,dict):
        _V1007_LAST_SLATE["combo_official"]=bool(combo.get("official"));_V1007_LAST_SLATE["combo_units"]=combo_units;_V1007_LAST_SLATE["combo_probability"]=combo.get("probability")
    logging.info("V10.0.13 COMBO | available=%s official=%s legs=%d units=%.2fu p=%s price=%s reason=%s",
                 combo.get("available"),combo.get("official"),len(combo.get("legs") or []),combo_units,
                 pct(combo.get("probability")) if combo.get("probability") is not None else "-",
                 f"{combo.get('winamax_price'):.2f}" if combo.get("winamax_price") else "-",combo.get("reason"))
    return portfolio


def v1013_combo_leg_payload(c):
    r=c["result"];rec=c["rec"];e=v1012_ensure_execution(rec);price=num(e.get("price"),0)
    return {"game_pk":r.get("game_pk"),"game_date":(r.get("game") or {}).get("gameDate"),"home":r["ctx"].get("home"),"away":r["ctx"].get("away"),
            "phase":r.get("phase"),"market":rec.get("market"),"pick":rec.get("name"),"point":rec.get("point"),
            "p_effective":round(num(rec.get("p_effective"),.5),6),"confidence":round(num(rec.get("confidence"),0),3),
            "quality":round(num(r.get("quality"),0),4),"refs":int(num(rec.get("refs"),0)),"candidate_score":round(num(c.get("score"),0),2),
            "winamax_price":round(price,4) if price>1 else None,"option_role":rec.get("option_role")}


def v1013_combo_text(combo):
    if not combo or not combo.get("available"):
        return "**Aucun combiné.** Il faut au moins 2 options fortes sur 2 matchs différents."
    lines=[]
    for i,c in enumerate(combo.get("legs") or [],1):
        r=c["result"];rec=c["rec"];e=v1012_ensure_execution(rec);price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "non récupérée"
        lines.append(f"**{i}. {v1011_market_label(rec)}** — {r['ctx']['away']} @ {r['ctx']['home']}\n{v1012_phase_badge(r.get('phase'))} • chance **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • Winamax **{price_txt}** *(info)*")
    ptxt=pct(combo.get("probability"));price_txt=f"{combo.get('winamax_price'):.2f}" if combo.get("winamax_price") else "à vérifier"
    if combo.get("official"):
        u=num(combo.get("units"),0);tail=f"\n\n✅ **COMBINÉ OFFICIEL — {u:g}u = {u*UNIT:.2f} €**\nChance combinée estimée ≈ **{ptxt}** • cote Winamax combinée **{price_txt}** *(info)*"
    else:
        tail=f"\n\n⚪ **Combiné non joué** — {combo.get('reason','non retenu')}\nChance combinée estimée ≈ **{ptxt}** • cote Winamax combinée **{price_txt}** *(info)*"
    return "\n\n".join(lines)+tail


def send_daily_plan(results):
    official=v1011_selected_items(results)
    plan="\n\n".join(v1011_plan_pick_text(x,i+1) for i,x in enumerate(official)) if official else "**AUCUN PARI SIMPLE OFFICIEL SUR CE RUN.** Aucun candidat ne passe actuellement les seuils statistiques minimums."
    combo=_V1013_LAST_COMBO or v1013_build_combo(results,num((_V1007_LAST_SLATE or {}).get("units"),0))
    others=[];official_ids={id(x["rec"]) for x in official};combo_ids={id(c["rec"]) for c in (combo.get("legs") or [])}
    for c in v1011_build_slate(results,False)["pool"]:
        if id(c["rec"]) in official_ids or id(c["rec"]) in combo_ids:continue
        e=v1012_ensure_execution(c["rec"]);price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "—"
        others.append(f"• **{v1011_market_label(c['rec'])}** • {c['result']['ctx']['away']} @ {c['result']['ctx']['home']} • **{v1012_phase_badge(c['result'].get('phase'))}** • {pct(c['rec'].get('p_effective'))} • conf {num(c['rec'].get('confidence')):.1f}/10 • Winamax {price_txt} *(info)*")
        if len(others)>=5:break
    other_txt="\n".join(others) if others else "Aucune autre option ne passe actuellement les filtres statistiques."
    slate=_V1007_LAST_SLATE or {};simple_units=num(slate.get("units"),0);combo_units=num(combo.get("units"),0) if combo.get("official") else 0;total_units=simple_units+combo_units
    status=f"Qualité de la journée : **{slate.get('grade','FAIBLE')} ({num(slate.get('score')):.0f}/100)**\nParis simples : **{int(num(slate.get('official_count'),len(official)))}/3** • combiné : **{'OUI' if combo.get('official') else 'NON'}** • exposition totale : **{total_units:g}/{V1007_MAX_DAILY_UNITS}u**"
    rule="Le Plan Officiel peut contenir jusqu'à **3 simples + 1 combiné de 2 sélections**. Le combiné utilise seulement des options fortes de **matchs différents**, vaut **0,5u par défaut** et reste inclus dans le plafond total de **4u**. EARLY/LATE restent à reconfirmer plus près du match. Winamax reste 100 % informatif."
    return send_embed("🎟️ PLAN OFFICIEL",[("✅ Paris simples",plan),("🔗 Combiné officiel — 2 sélections",v1013_combo_text(combo)),("🟢 Autres options intéressantes",other_txt),("📊 Journée",status),("ℹ️ Règle",rule)],5763719)


def v1010_make_run_rows(results,run_id=None,analyzed_at=None):
    analyzed_at=analyzed_at or NOW.isoformat();run_id=run_id or hashlib.sha1(f"{analyzed_at}|{TARGET_DATE}|{VERSION}".encode()).hexdigest()[:16]
    rows=_V1012_MAKE_RUN_ROWS_013(results,run_id,analyzed_at)
    for row in rows:row.setdefault("bet_type","SINGLE")
    combo=_V1013_LAST_COMBO
    if not combo or not combo.get("official") or len(combo.get("legs") or [])!=2:return rows
    legs=[v1013_combo_leg_payload(c) for c in combo["legs"]];leg_sig="|".join(f"{x['game_pk']}:{x['market']}:{norm_name(x['pick'])}:{x.get('point')}" for x in legs)
    jid=hashlib.sha1(f"{run_id}|COMBO|{leg_sig}".encode()).hexdigest();cp=num(combo.get("probability"),0);price=num(combo.get("winamax_price"),0);units=num(combo.get("units"),0);stake=round(units*UNIT,2)
    phase="EARLY" if any(str(x.get("phase")).upper()=="EARLY" for x in legs) else "LATE" if any(str(x.get("phase")).upper()=="LATE" for x in legs) else "FINAL"
    fair=(1/cp) if cp>0 else None;ev=(cp*price-1) if cp>0 and price>1 else None
    rows.append({"journal_version":JOURNAL_VERSION,"journal_id":jid,"run_id":run_id,"bot_version":VERSION,"analyzed_at":analyzed_at,"target_date":TARGET_DATE,
        "bet_type":"COMBO","portfolio_constructed":True,"game_pk":None,"game_date":min((x.get("game_date") for x in legs if x.get("game_date")),default=None),"home":None,"away":None,"phase":phase,"seconds_to_game":None,
        "market":"COMBO","pick":"Combiné 2 sélections","point":None,"model_proposed":False,"combo_leg_count":2,"combo_legs":legs,"p_model_raw":None,"p_effective":round(cp,6),
        "confidence":round(min(num(x.get("confidence"),0) for x in legs),3),"quality":round(min(num(x.get("quality"),0) for x in legs),4),"refs":min(int(num(x.get("refs"),0)) for x in legs),
        "p_market":None,"market_gap":None,"fair_raw":None,"fair_effective":round(fair,4) if fair else None,"min_price_raw":None,"min_price_effective":None,
        "winamax_price":round(price,4) if price>1 else None,"winamax_price_informational":True,"winamax_price_gate_enabled":False,"edge_effective":None,"ev_effective":round(ev,6) if ev is not None else None,
        "eligible_before_slate":True,"interesting_without_phase":True,"candidate_score":round(mean([num(x.get("candidate_score"),0) for x in legs]),2),"risk_profile":"COMBO_2LEG",
        "official_selected":True,"official_units":units,"official_stake_eur":stake,"official_reason":"combiné officiel V10.0.13","preview_selected":False,"rejection_reasons":[],"selection_status":"OFFICIAL",
        "slate_score":round(num((_V1007_LAST_SLATE or {}).get("score"),0),2),"slate_grade":(_V1007_LAST_SLATE or {}).get("grade"),"stability_alert":"OK","stability_delta":None,"p_structural_raw":None,
        "home_lineup_confirmed":None,"home_lineup_count":None,"away_lineup_confirmed":None,"away_lineup_count":None,"home_starter":None,"away_starter":None,"unit_eur":round(UNIT,4),
        "result_status":"PENDING","result":None,"home_score":None,"away_score":None,"settled_at":None,"hypothetical_profit_1u_eur":None,"official_profit_eur":None})
    return rows


def v1010_settle_journal(journal,hist):
    changed=_V1012_SETTLE_JOURNAL_013(journal,hist)
    for row in journal:
        if row.get("market")!="COMBO" or row.get("result") in ("W","L","P"):continue
        legs=row.get("combo_legs") or []
        if not legs:continue
        leg_results=[];ready=True
        for leg in legs:
            rec=hist.get(str(leg.get("game_pk")))
            if not rec or rec.get("status")!="FINAL" or rec.get("home_score") is None or rec.get("away_score") is None:
                ready=False;break
            lr=v10_settle_market(leg.get("market"),leg.get("pick"),leg.get("point"),leg.get("home",""),leg.get("away",""),rec.get("home_score"),rec.get("away_score"))
            if lr not in ("W","L","P"):ready=False;break
            leg_results.append((lr,num(leg.get("winamax_price"),0)))
        if not ready:continue
        result="L" if any(x[0]=="L" for x in leg_results) else "P" if all(x[0]=="P" for x in leg_results) else "W"
        all_prices=all(x[1]>1 for x in leg_results);settled_price=None
        if all_prices and result=="W":settled_price=math.prod(x[1] for x in leg_results if x[0]=="W")
        elif all_prices:settled_price=num(row.get("winamax_price"),0) or math.prod(x[1] for x in leg_results)
        profit=v1010_profit(result,num(row.get("official_stake_eur"),0),settled_price or 0) if (all_prices or result=="P") else None
        row.update({"result_status":"SETTLED","result":result,"settled_at":NOW.isoformat(),"combo_leg_results":[x[0] for x in leg_results],
                    "settled_combo_price":round(settled_price,4) if settled_price else None,"official_profit_eur":profit,"hypothetical_profit_1u_eur":None})
        changed+=1
    return changed


def v10_self_test():
    global VERSION,_V1013_LAST_COMBO
    current=VERSION;VERSION="10.0.12"
    try:_V1012_SELF_TEST_013()
    finally:VERSION=current
    assert VERSION=="10.0.13"
    def fc(gid,phase,market,name,p,conf,score,price=0):
        r={"game_pk":gid,"game":{"gameDate":"2026-08-12T20:00:00Z"},"phase":phase,"quality":.85,"stability_alert":"OK","ctx":{"home":f"H{gid}","away":f"A{gid}"}}
        rec={"market":market,"name":name,"point":None,"p_effective":p,"confidence":conf,"refs":3,"winamax_eval":{"price":price} if price else {}}
        return {"result":r,"rec":rec,"score":score}
    c1=fc(1,"EARLY","ML","H1",.63,7.5,82,1.70);c2=fc(2,"LATE","ML","H2",.62,7.2,79,1.80)
    combo=v1013_pick_combo([c1,c2],3);assert combo["official"] and abs(combo["units"]-.5)<1e-9 and len(combo["legs"])==2 and abs(combo["winamax_price"]-3.06)<1e-9
    blocked=v1013_pick_combo([c1,c2],4);assert blocked["available"] and not blocked["official"]
    _V1013_LAST_COMBO=combo
    rows=v1010_make_run_rows([],"combo-test","2026-08-12T13:00:00+00:00");cr=[x for x in rows if x.get("market")=="COMBO"];assert len(cr)==1 and cr[0]["official_units"]==.5 and len(cr[0]["combo_legs"])==2
    hist={"1":{"game_pk":1,"status":"FINAL","home":"H1","away":"A1","home_score":5,"away_score":3},"2":{"game_pk":2,"status":"FINAL","home":"H2","away":"A2","home_score":4,"away_score":2}}
    assert v1010_settle_journal(cr,hist)==1 and cr[0]["result"]=="W" and cr[0]["official_profit_eur"] is not None
    _V1013_LAST_COMBO=None
    print("SELF-TEST MLB BETTING BOT V10.0.13 OK")

'''
s=s.replace(marker,layer+marker,1)
p.write_text(s,encoding='utf-8')
print('Applied V10.0.13 combo layer')
