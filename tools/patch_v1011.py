from pathlib import Path

path=Path('bot.py')
text=path.read_text(encoding='utf-8')
marker='if __name__=="__main__":\n'
tag='# ==================== V10.0.11 OPEN MARKET OPTIONS ====================='
if tag in text:
    print('V10.0.11 layer already present')
    raise SystemExit(0)
if marker not in text:
    raise SystemExit('main marker not found')

layer=r'''


# ==================== V10.0.11 OPEN MARKET OPTIONS =====================
# Open-option / selection layer:
# - six readable options per game (2 ML, favorite -1.5, dog +1.5,
#   best available Over, best available Under)
# - Winamax price is informational only and never compared with model minimum
#   for eligibility, score or premium staking
# - the official plan still keeps the strict portfolio limits (0-3 bets,
#   4u/day, 1 bet/game) and requires the market to actually be available
# - FINAL runs optionally enrich totals with event-level alternate_totals
#   from The Odds API; EARLY/LATE fall back to featured totals to save quota
_V1010_SELF_TEST_011=v10_self_test
_V1010_ATTACH_RECS_011=attach_model_recommendations
_V1010_BUILD_SNAPSHOT_011=build_snapshot

VERSION="10.0.11"
SELECTION_VERSION="open-market-winamax-info-v2"
V1011_ALT_TOTALS_ENABLED=str(os.getenv("V1011_ALT_TOTALS_ENABLED","1")).strip().lower() not in ("0","false","no","off")
V1011_ALT_TOTALS_PHASES={x.strip().upper() for x in os.getenv("V1011_ALT_TOTALS_PHASES","FINAL").split(",") if x.strip()}
V1011_ALT_TOTALS_MAX_CALLS=max(0,int(os.getenv("V1011_ALT_TOTALS_MAX_CALLS","12") or 12))
V1011_TOTAL_TARGET_EFFECTIVE=clamp(float(os.getenv("V1011_TOTAL_TARGET_EFFECTIVE","0.62") or .62),.58,.67)
_V1011_ALT_CALLS=0


def v1011_effective_probability(p,market,phase):
    p=clamp(num(p,.5),.001,.999)
    if p>=.5:return v1007_effective_probability(p,market,phase)
    return 1-v1007_effective_probability(1-p,market,phase)


def v1011_consensus_rows(rows,name,point=None,market="totals"):
    vals=[];ages=[]
    for b,m in rows:
        if b.get("key") not in REF_BOOKS:continue
        p=fair_book_probability(m.get("outcomes",[]),name,point,market)
        if p is None:continue
        try:age=max(0,(NOW-parse_dt(m.get("last_update",b.get("last_update")))).total_seconds()/60)
        except Exception:age=10
        if age>90:continue
        weight=max(.25,1-age/120);vals += [p]*max(1,int(round(weight*4)));ages.append(age)
    if not vals:return {"p":None,"n":0,"disp":None,"age_min":None}
    return {"p":median(vals),"n":len(ages),"disp":pstdev(vals) if len(vals)>1 else 0,"age_min":median(ages) if ages else None}


def v1011_calibrate_tuple(result,market,probs):
    pw,pp,pl=(num(probs[0]),num(probs[1]),num(probs[2]));s=pw+pp+pl
    if s<=0:return .5,0,.5
    pw,pp,pl=pw/s,pp/s,pl/s
    try:state=v10_market_cal_states().get(result.get("phase","EARLY"),{}).get(market,{})
    except Exception:state={}
    if state.get("active") and state.get("model"):
        return v10_calibrate_tuple(state["model"],pw,pp,pl)
    return pw,pp,pl


def v1011_apply_effective(rec,result):
    if not rec:return None
    phase=result.get("phase","EARLY");market=rec.get("market");pm=clamp(num(rec.get("p_model"),.5),.001,.999)
    pe=v1011_effective_probability(pm,market,phase);pp=clamp(num(rec.get("p_push"),0),0,.95);mass=1-pp;pw=mass*pe;pl=mass*(1-pe)
    rec["p_effective"]=pe;rec["p_effective_win"]=pw;rec["p_effective_loss"]=pl
    rec["fair_effective"]=(1-pp)/pw if pw>0 else 99
    rec["min_price_effective"]=min_acceptable_price(pw,pp,pl)
    rec["selection_version"]=SELECTION_VERSION;rec["stability_alert"]=result.get("stability_alert","OK");rec["stability_delta"]=result.get("stability_delta",0)
    e=rec.get("winamax_eval")
    if e:
        price=num(e.get("price"),0);np=pw+pl;pcond=pw/np if np else .5
        e.update({"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":pcond,"fair":rec["fair_effective"],"min_price":rec["min_price_effective"],
                  "effective_probability":pe,"effective_probability_source":"2026-walkforward-shrinkage-symmetric",
                  "effective_min_price":rec["min_price_effective"],"edge":pcond-1/price if price>1 else None,
                  "ev":pw*price+pp-1 if price>1 else None,"official_v1011":True,"official_selected":False,
                  "official_units":0,"official_reason":"hors plan officiel","price_gate_enabled":False,"price_informational":True})
    return rec


def v1011_make_rec(result,market,name,point,probs,cons,role):
    pw,pp,pl=probs;s=num(pw)+num(pp)+num(pl)
    if s<=0:return None
    pw,pp,pl=num(pw)/s,num(pp)/s,num(pl)/s;np=pw+pl
    if np<=0:return None
    pm=pw/np;mp=(cons or {}).get("p");refs=int(num((cons or {}).get("n"),0))
    e=winamax_eval_for(result,market,name,point)
    rec={"market":market,"name":name,"point":point,"option_role":role,"p_model":pm,"p_model_raw":pm,
         "p_win":pw,"p_push":pp,"p_loss":pl,"p_market":mp,"market_gap":pm-mp if mp is not None else None,
         "refs":refs,"fair":(1-pp)/pw if pw>0 else 99,"min_price":min_acceptable_price(pw,pp,pl),
         "confidence":model_signal_confidence(pm,result.get("quality",0),mp,refs),"winamax_eval":e}
    return v1011_apply_effective(rec,result)


def v1011_alt_totals_event(result):
    global _V1011_ALT_CALLS
    phase=str(result.get("phase","EARLY")).upper();event=result.get("event") or {};eid=event.get("id")
    if not V1011_ALT_TOTALS_ENABLED or phase not in V1011_ALT_TOTALS_PHASES or not eid:return None
    key=("v1011-alt-totals",eid)
    if key in _CACHE:return _CACHE[key]
    if _V1011_ALT_CALLS>=V1011_ALT_TOTALS_MAX_CALLS:
        _CACHE[key]=None;return None
    _V1011_ALT_CALLS+=1
    try:
        d,h=http_json(f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eid}/odds",
                      {"apiKey":ODDS_KEY,"bookmakers":BOOKMAKERS,"markets":"alternate_totals","oddsFormat":"decimal","dateFormat":"iso"},
                      return_headers=True,retries=1)
        logging.info("V10.0.11 ALT TOTALS | %s @ %s | coût=%s restant=%s",
                     result["ctx"]["away"],result["ctx"]["home"],h.get("x-requests-last","?"),h.get("x-requests-remaining","?"))
        _CACHE[key]=d or None
    except Exception as e:
        logging.info("V10.0.11 ALT TOTALS indisponibles | %s @ %s | %s",result["ctx"]["away"],result["ctx"]["home"],e)
        _CACHE[key]=None
    return _CACHE[key]


def v1011_total_rows(result):
    rows=list(market_rows(result.get("event") or {},"totals"))
    alt=v1011_alt_totals_event(result)
    if alt:rows.extend(market_rows(alt,"alternate_totals"))
    return rows


def v1011_enrich_alt_total_evals(result,rows):
    existing={(e.get("market"),str(e.get("name","")).lower(),round(num(e.get("point")),3)) for e in result.get("evals",[]) if e.get("point") is not None}
    for b,m in rows:
        if b.get("key")!="winamax_fr" or m.get("key")!="alternate_totals":continue
        for o in m.get("outcomes",[]):
            name=str(o.get("name",""));point=round(num(o.get("point")),3);price=num(o.get("price"),0);key=("TOTAL",name.lower(),point)
            if price<=1 or key in existing:continue
            probs=line_probs(result["hmu"],result["amu"],result["disp_state"]["alpha_home"],result["disp_state"]["alpha_away"],"TOTAL",name,point,result["ctx"]["home"],result["ctx"]["away"])
            con=v1011_consensus_rows(rows,name,point,"totals")
            e=evaluate(result["ctx"],result["quality"],"TOTAL",name,price,point,probs,con);e["source_market"]="alternate_totals"
            result.setdefault("evals",[]).append(e);existing.add(key)


def v1011_total_interest(rec,result):
    pe=num(rec.get("p_effective"),.5);gap=num(rec.get("market_gap"),0) if rec.get("market_gap") is not None else 0
    refs=int(num(rec.get("refs"),0));conf=num(rec.get("confidence"),0);price=num((rec.get("winamax_eval") or {}).get("price"),0)
    # "Best" deliberately means a strong, useful line around the bot's selection
    # band, not the easiest extreme line. Winamax price is not part of the score.
    return ((1 if price>1 else 0),-abs(pe-V1011_TOTAL_TARGET_EFFECTIVE)+.45*clamp(gap,-.12,.12)+.006*conf+.002*min(refs,4))


def v1011_build_options(result):
    home=result["ctx"]["home"];away=result["ctx"]["away"];disp=result["disp_state"]
    options=[]
    old_ml=(result.get("model_recs") or {}).get("ML")
    if old_ml:
        hp=num(old_ml.get("p_model"),.5) if norm_name(old_ml.get("name"))==norm_name(home) else 1-num(old_ml.get("p_model"),.5)
    else:hp=num(result.get("p_model"),.5)
    hp=clamp(hp,.001,.999)
    options.append(v1011_make_rec(result,"ML",home,None,(hp,0,1-hp),consensus(result["event"],"h2h",home),"ML_HOME"))
    options.append(v1011_make_rec(result,"ML",away,None,(1-hp,0,hp),consensus(result["event"],"h2h",away),"ML_AWAY"))

    fav=home if hp>=.5 else away;dog=away if fav==home else home
    fp=line_probs(result["hmu"],result["amu"],disp["alpha_home"],disp["alpha_away"],"RUNLINE",fav,-1.5,home,away)
    fp=v1011_calibrate_tuple(result,"RUNLINE",fp);dp=(fp[2],fp[1],fp[0])
    options.append(v1011_make_rec(result,"RUNLINE",fav,-1.5,fp,consensus(result["event"],"spreads",fav,-1.5),"RL_FAVORITE"))
    options.append(v1011_make_rec(result,"RUNLINE",dog,1.5,dp,consensus(result["event"],"spreads",dog,1.5),"RL_UNDERDOG"))

    rows=v1011_total_rows(result);v1011_enrich_alt_total_evals(result,rows)
    points=set()
    for b,m in rows:
        if b.get("key")!="winamax_fr":continue
        for o in m.get("outcomes",[]):
            if o.get("point") is not None:points.add(round(num(o.get("point")),3))
    if not points:
        for _,m in rows:
            for o in m.get("outcomes",[]):
                if o.get("point") is not None:points.add(round(num(o.get("point")),3))
    overs=[];unders=[]
    for point in sorted(points):
        op=line_probs(result["hmu"],result["amu"],disp["alpha_home"],disp["alpha_away"],"TOTAL","Over",point,home,away)
        op=v1011_calibrate_tuple(result,"TOTAL",op);up=(op[2],op[1],op[0])
        ro=v1011_make_rec(result,"TOTAL","Over",point,op,v1011_consensus_rows(rows,"Over",point,"totals"),"TOTAL_OVER_BEST")
        ru=v1011_make_rec(result,"TOTAL","Under",point,up,v1011_consensus_rows(rows,"Under",point,"totals"),"TOTAL_UNDER_BEST")
        if ro:overs.append(ro)
        if ru:unders.append(ru)
    if overs:options.append(max(overs,key=lambda x:v1011_total_interest(x,result)))
    if unders:options.append(max(unders,key=lambda x:v1011_total_interest(x,result)))
    options=[x for x in options if x]
    result["option_recs"]=options
    return options


def attach_model_recommendations(result):
    recs=_V1010_ATTACH_RECS_011(result)
    v1011_build_options(result)
    return recs


def v1011_iter_options(result):
    xs=result.get("option_recs")
    return list(xs) if xs else [x for x in (result.get("model_recs") or {}).values() if x]


def v1011_profile(rec):
    if rec.get("market")=="TOTAL":return "TOTAL_OVER" if str(rec.get("name","")).lower()=="over" else "TOTAL_UNDER"
    mp=rec.get("p_market")
    fav=(num(mp)>=.5) if mp is not None else num(rec.get("p_model"),.5)>=.5
    return "SIDE_FAVORITE" if fav else "SIDE_UNDERDOG"


def v1011_candidate(result,rec,require_phase=True):
    reasons=[];phase=str(result.get("phase","EARLY")).upper();market=rec.get("market");pe=num(rec.get("p_effective"),.5)
    conf=num(rec.get("confidence"),0);q=num(result.get("quality"),0);refs=int(num(rec.get("refs"),0));e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);alert=result.get("stability_alert","OK")
    if pe<V1007_MIN_EFFECTIVE.get(market,.60):reasons.append(f"proba effective {pe*100:.1f}% trop faible")
    if conf<V1007_MIN_CONF:reasons.append(f"confiance {conf:.1f}< {V1007_MIN_CONF:.1f}")
    if q<V1007_MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10 insuffisante")
    if refs<V1007_MIN_REFS:reasons.append(f"seulement {refs} book(s) référence")
    if alert in ("HIGH","FLIP"):reasons.append(f"instabilité modèle {alert}")
    # Price LEVEL never blocks a bet in V10.0.11. Availability still matters:
    # an official Winamax bet cannot be executed if that exact market is absent.
    if price<=1:reasons.append("marché Winamax indisponible")
    if require_phase and phase=="EARLY":reasons.append("phase EARLY: pré-sélection uniquement")
    score=60+120*(pe-.58)+4*(conf-6.5)+15*(q-.70)+2*min(refs,4)
    if alert=="WATCH":score-=6
    score=clamp(score,0,100)
    premium=(phase=="FINAL" and pe>=V1007_PREMIUM_EFFECTIVE and conf>=V1007_PREMIUM_CONF and q>=V1007_PREMIUM_QUALITY and refs>=V1007_PREMIUM_REFS and result.get("stability_alert")=="OK" and result["ctx"]["home_lineup"].get("count",0)>=8 and result["ctx"]["away_lineup"].get("count",0)>=8 and v1007_starters_ok(result["ctx"]))
    return {"eligible":not reasons,"reasons":reasons,"score":score,"units":2 if premium else 1,"profile":v1011_profile(rec),"result":result,"rec":rec,"price":price,"minimum":num(rec.get("min_price_effective"),0),"premium":premium}


def v1011_build_slate(results,require_phase=True):
    pool=[]
    for r in results:
        for rec in v1011_iter_options(r):
            c=v1011_candidate(r,rec,require_phase)
            if c["eligible"]:pool.append(c)
    pool.sort(key=lambda c:(c["score"],num(c["rec"].get("p_effective"),.5),num(c["rec"].get("confidence"))),reverse=True)
    unique=[];seen=set()
    for c in pool:
        gid=str(c["result"]["game_pk"])
        if gid in seen:continue
        unique.append(c);seen.add(gid)
    top=unique[:V1007_MAX_OFFICIAL_BETS];slate_score=mean([c["score"] for c in top]) if top else 0.0
    thresholds=(70,72,74);max_bets=0
    for i,c in enumerate(top):
        if c["score"]>=thresholds[i]:max_bets=i+1
        else:break
    grade="FORT" if slate_score>=82 else "BON" if slate_score>=76 else "MOYEN" if slate_score>=70 else "FAIBLE"
    return {"pool":pool,"unique":unique,"score":round(slate_score,1),"grade":grade,"max_bets":max_bets}


def allocate_portfolio(results):
    global _V10_LAST_PORTFOLIO,_V1007_LAST_SLATE
    for r in results:
        for e in r.get("evals",[]):e.update({"selected":False,"units":0.0,"stake_eur":0.0,"official_selected":False,"official_units":0,"official_preview_units":0})
        for rec in v1011_iter_options(r):
            e=rec.get("winamax_eval") or {}
            if e:e.update({"official_v1011":True,"official_selected":False,"official_units":0,"official_preview_units":0,"official_reason":"hors plan officiel","price_gate_enabled":False,"price_informational":True})
    slate=v1011_build_slate(results,True);preview=v1011_build_slate(results,False);chosen=[];used_games=set();profiles={};units_used=0;thresholds=(70,72,74)
    for c in slate["pool"]:
        if len(chosen)>=slate["max_bets"] or len(chosen)>=V1007_MAX_OFFICIAL_BETS:break
        if c["score"]<thresholds[len(chosen)]:break
        gid=str(c["result"]["game_pk"]);profile=c["profile"]
        if gid in used_games:continue
        e=c["rec"].get("winamax_eval") or {}
        if profiles.get(profile,0)>=2:
            e["official_reason"]="corrélation: déjà 2 paris du même profil";continue
        units=c["units"]
        if units_used+units>V1007_MAX_DAILY_UNITS:
            if units==2 and units_used+1<=V1007_MAX_DAILY_UNITS:units=1
            else:e["official_reason"]="plafond quotidien 4u";continue
        if not e:continue
        e.update({"selected":True,"official_selected":True,"official_units":units,"units":float(units),"stake_eur":round(units*UNIT,2),
                  "qualified":True,"model_recommended":True,"reason":"OK V10.0.11","portfolio_reason":"PARI OFFICIEL V10.0.11",
                  "official_reason":"retenu dans le plan officiel","candidate_units":float(units),"candidate_stake_eur":round(units*UNIT,2)})
        chosen.append(c);used_games.add(gid);profiles[profile]=profiles.get(profile,0)+1;units_used+=units
    chosen_ids={id(c["rec"]) for c in chosen}
    for c in slate["pool"]:
        e=c["rec"].get("winamax_eval") or {}
        if id(c["rec"]) not in chosen_ids and e.get("official_reason")=="hors plan officiel":e["official_reason"]="option intéressante non retenue par le Slate Score / limite 0-3"
    early_preview=[];seen=set()
    for c in preview["pool"]:
        if str(c["result"].get("phase")).upper()!="EARLY" or c["score"]<70:continue
        gid=str(c["result"]["game_pk"])
        if gid in seen:continue
        e=c["rec"].get("winamax_eval") or {}
        if e:e["official_preview_units"]=1
        early_preview.append(c);seen.add(gid)
        if len(early_preview)>=3:break
    allocated=round(units_used*UNIT,2);cap=round(V1007_MAX_DAILY_UNITS*UNIT,2)
    _V1007_LAST_SLATE={"score":slate["score"],"grade":slate["grade"],"max_bets":slate["max_bets"],"official_count":len(chosen),"units":units_used,"preview_count":len(early_preview)}
    _V10_LAST_PORTFOLIO={"daily_cap":cap,"allocated":allocated,"remaining":round(cap-allocated,2),"game_cap":round(2*UNIT,2),"slate_score":slate["score"],"slate_grade":slate["grade"],"official_count":len(chosen),"official_units":units_used}
    for r in results:r["slate_score"]=slate["score"];r["slate_grade"]=slate["grade"]
    logging.info("V10.0.11 OPEN SLATE | score=%.1f grade=%s max=%d selected=%d units=%du/%du | Winamax price gate=OFF",slate["score"],slate["grade"],slate["max_bets"],len(chosen),units_used,V1007_MAX_DAILY_UNITS)
    return _V10_LAST_PORTFOLIO


def v1011_selected_items(results):
    out=[]
    for r in results:
        for rec in v1011_iter_options(r):
            e=rec.get("winamax_eval") or {}
            if e.get("official_selected"):out.append({"result":r,"rec":rec,"score":num(rec.get("p_effective"),.5)*100+num(rec.get("confidence"))})
    return sorted(out,key=lambda x:x["score"],reverse=True)


def v1007_selected_items(results):
    return v1011_selected_items(results)


def v1011_market_label(rec):
    if not rec:return "—"
    if rec.get("market")=="ML":return f"{rec.get('name','—')} ML"
    if rec.get("market")=="RUNLINE":return f"{rec.get('name','—')} {num(rec.get('point')):+g}"
    side="Over" if str(rec.get("name","")).lower()=="over" else "Under"
    return f"{side} {num(rec.get('point')):g}"


def v1011_option_status(result,rec):
    e=rec.get("winamax_eval") or {};price=num(e.get("price"),0)
    if e.get("official_selected"):return f"✅ OFFICIEL {int(num(e.get('official_units'),1))}u"
    c=v1011_candidate(result,rec,False)
    if c["eligible"]:
        return "👀 INTÉRESSANT — attendre LATE/FINAL" if str(result.get("phase")).upper()=="EARLY" else "🟢 OPTION INTÉRESSANTE"
    if price<=1:return "⏳ Winamax indisponible"
    return "⚪ Option analysée"


def v1011_option_line(result,rec):
    if not rec:return "—"
    e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "—"
    return f"{v1011_option_status(result,rec)} • **{v1011_market_label(rec)}**\nChance prudente **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • Winamax **{price_txt}** *(info)*"


def send_game(result,snap,portfolio):
    ctx=result["ctx"];opts=v1011_iter_options(result);phase=v1009_phase_text(result.get("phase"));raw=num(result.get("p_model"),.5);side=ctx["home"] if raw>=.5 else ctx["away"];raw_side=max(raw,1-raw);con=result.get("con") or {}
    market_side=ctx["home"] if num(con.get("p"),.5)>=.5 else ctx["away"]
    market_p=max(num(con.get("p"),.5),1-num(con.get("p"),.5)) if con.get("p") is not None else None
    brief=f"{phase}\nModèle brut : **{side} {pct(raw_side)}**\nMarché réf. : **{market_side} {pct(market_p)}** ({int(num(con.get('n'),0))} books)\nScore projeté : **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**"
    teams=f"{ctx['away']} : {v1009_lineup_text(ctx.get('away_lineup'))} • starter **{ctx.get('away_sp','—')}**\n{ctx['home']} : {v1009_lineup_text(ctx.get('home_lineup'))} • starter **{ctx.get('home_sp','—')}**"
    ml=[x for x in opts if x.get("market")=="ML"];rl=[x for x in opts if x.get("market")=="RUNLINE"];tot=[x for x in opts if x.get("market")=="TOTAL"]
    official=[x for x in opts if (x.get("winamax_eval") or {}).get("official_selected")]
    decision="\n".join(f"• ✅ **{v1011_market_label(x)} — {int(num((x.get('winamax_eval') or {}).get('official_units'),1))}u**" for x in official)
    if not decision:decision="**Aucun pari officiel sur ce match.** Les options ci-dessus restent visibles pour comparaison."
    fields=[("🧭 En bref",brief),("👥 Équipes",teams),
            ("🏆 Vainqueur — les 2 côtés","\n\n".join(v1011_option_line(result,x) for x in ml) or "—"),
            ("⚾ Handicap ±1,5 — les 2 côtés","\n\n".join(v1011_option_line(result,x) for x in rl) or "—"),
            ("📊 Total — meilleur Over + meilleur Under","\n\n".join(v1011_option_line(result,x) for x in tot) or "—"),
            ("✅ Décision du bot",decision),
            ("ℹ️ Lecture","La **cote Winamax est informative** : son niveau ne bloque plus une option et n'entre plus dans le Slate Score. L'absence du marché exact empêche seulement de l'exécuter. Les lignes alternatives de Total sont recherchées en FINAL quand l'API les fournit.")]
    return send_embed(f"⚾ MLB V{VERSION} • {ctx['away']} @ {ctx['home']}",fields,5763719)


def v1011_plan_pick_text(item,index=None):
    r=item["result"];rec=item["rec"];e=rec.get("winamax_eval") or {};u=int(num(e.get("official_units"),0));price=num(e.get("price"),0);prefix=f"**#{index}** " if index is not None else "• "
    return f"{prefix}✅ **{v1011_market_label(rec)} — {u}u = {u*UNIT:.2f} €**\n{r['ctx']['away']} @ {r['ctx']['home']} • {r['phase']} • chance prudente **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • Winamax **{price:.2f}** *(info)*"


def plan_pick_text(item,index=None):return v1011_plan_pick_text(item,index)


def send_daily_plan(results):
    official=v1011_selected_items(results)
    plan="\n\n".join(v1011_plan_pick_text(x,i+1) for i,x in enumerate(official)) if official else "**AUCUN PARI OFFICIEL SUR CE RUN.**"
    others=[];official_ids={id(x["rec"]) for x in official}
    for c in v1011_build_slate(results,False)["pool"]:
        if id(c["rec"]) in official_ids:continue
        e=c["rec"].get("winamax_eval") or {};price=num(e.get("price"),0)
        others.append(f"• **{v1011_market_label(c['rec'])}** • {c['result']['ctx']['away']} @ {c['result']['ctx']['home']} • {pct(c['rec'].get('p_effective'))} • conf {num(c['rec'].get('confidence')):.1f}/10 • Winamax {price:.2f} *(info)*")
        if len(others)>=5:break
    other_txt="\n".join(others) if others else "Aucune autre option ne passe actuellement les filtres statistiques."
    slate=_V1007_LAST_SLATE or {};status=f"Qualité de la journée : **{slate.get('grade','FAIBLE')} ({num(slate.get('score')):.0f}/100)**\nParis officiels : **{int(num(slate.get('official_count'),len(official)))}/3** • exposition : **{int(num(slate.get('units'),0))}/4u**"
    return send_embed("🎟️ PLAN OFFICIEL",[("✅ À jouer selon le bot",plan),("🟢 Autres options intéressantes",other_txt),("📊 Journée",status),("ℹ️ Règle","Le Plan Officiel reste limité à **3 paris / 4u / 1 pari par match**. La cote Winamax est affichée pour information mais **n'est plus un filtre de sélection**.")],5763719)


def send_top_messages(results,state):
    ok=True
    groups=(("ML","🏆 TOP 3 — VAINQUEUR (informatif)"),("RUNLINE","⚾ TOP 3 — HANDICAP (informatif)"),("TOTAL","📈 TOP 3 — TOTAL (informatif)"))
    for market,title in groups:
        pool=[]
        for r in results:
            for rec in v1011_iter_options(r):
                if rec.get("market")!=market:continue
                c=v1011_candidate(r,rec,False);pool.append((c["eligible"],c["score"],r,rec))
        pool.sort(key=lambda z:(z[0],z[1],num(z[3].get("p_effective"),.5)),reverse=True)
        blocks=[];seen=set()
        for _,_,r,rec in pool:
            gid=str(r.get("game_pk"))
            if gid in seen:continue
            seen.add(gid);blocks.append(f"**#{len(blocks)+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{v1011_option_line(r,rec)}")
            if len(blocks)>=3:break
        ok=send_embed(title,[("ℹ️ Classement d'options — seul le PLAN OFFICIEL est officiel","\n\n".join(blocks) if blocks else "Aucune option disponible.")],16766720) and ok
    return ok


def build_snapshot(result,rec):
    snap=_V1010_BUILD_SNAPSHOT_011(result,rec)
    snap["selection_version"]=SELECTION_VERSION
    snap["open_market_options"]=[dict(model_rec_payload(x),winamax_price=num((x.get("winamax_eval") or {}).get("price"),0) or None,option_role=x.get("option_role")) for x in v1011_iter_options(result)]
    return snap


def v1010_make_run_rows(results,run_id=None,analyzed_at=None):
    analyzed_at=analyzed_at or NOW.isoformat();run_id=run_id or hashlib.sha1(f"{analyzed_at}|{TARGET_DATE}|{VERSION}".encode()).hexdigest()[:16];out=[]
    for r in results:
        ctx=r.get("ctx") or {};phase=r.get("phase","EARLY")
        for rec in v1011_iter_options(r):
            if not rec:continue
            market=rec.get("market");e=rec.get("winamax_eval") or {};c=v1011_candidate(r,rec,True);c_no_phase=v1011_candidate(r,rec,False);point=rec.get("point")
            jid_src=f"{run_id}|{r.get('game_pk')}|{market}|{norm_name(rec.get('name'))}|{point}|{rec.get('option_role','')}";journal_id=hashlib.sha1(jid_src.encode()).hexdigest();price=num(e.get("price"),0)
            official=bool(e.get("official_selected"));preview=bool(e.get("official_preview_units"));official_units=int(num(e.get("official_units",e.get("units",0)),0)) if official else 0;official_stake=round(official_units*UNIT,2)
            official_reason=e.get("official_reason") or ("retenu dans le plan officiel" if official else "non retenu");reasons=list(c.get("reasons") or [])
            if not official and official_reason and official_reason not in reasons:reasons.append(str(official_reason))
            status="OFFICIAL" if official else "PREVIEW" if preview else "INTERESTING" if c_no_phase.get("eligible") else "ANALYZED"
            out.append({"journal_version":JOURNAL_VERSION,"journal_id":journal_id,"run_id":run_id,"bot_version":VERSION,"analyzed_at":analyzed_at,"target_date":TARGET_DATE,
                "game_pk":r.get("game_pk"),"game_date":(r.get("game") or {}).get("gameDate"),"home":ctx.get("home"),"away":ctx.get("away"),"phase":phase,"seconds_to_game":round(num(r.get("seconds"),0),1),
                "market":market,"pick":rec.get("name"),"point":point,"option_role":rec.get("option_role"),"model_proposed":True,"p_model_raw":round(num(rec.get("p_model"),.5),6),"p_effective":round(num(rec.get("p_effective",rec.get("p_model")),.5),6),
                "confidence":round(num(rec.get("confidence"),0),3),"quality":round(num(r.get("quality"),0),4),"refs":int(num(rec.get("refs"),0)),"p_market":round(num(rec.get("p_market"),0),6) if rec.get("p_market") is not None else None,
                "market_gap":round(num(rec.get("market_gap"),0),6) if rec.get("market_gap") is not None else None,"fair_raw":round(num(rec.get("fair"),0),4) if rec.get("fair") is not None else None,
                "fair_effective":round(num(rec.get("fair_effective",rec.get("fair")),0),4) if rec.get("fair_effective",rec.get("fair")) is not None else None,"min_price_raw":round(num(rec.get("min_price"),0),4) if rec.get("min_price") is not None else None,
                "min_price_effective":round(num(rec.get("min_price_effective",rec.get("min_price")),0),4) if rec.get("min_price_effective",rec.get("min_price")) is not None else None,"winamax_price":round(price,4) if price>1 else None,
                "winamax_price_informational":True,"winamax_price_gate_enabled":False,"edge_effective":round(num(e.get("edge"),0),6) if price>1 and e.get("edge") is not None else None,"ev_effective":round(num(e.get("ev"),0),6) if price>1 and e.get("ev") is not None else None,
                "eligible_before_slate":bool(c.get("eligible")),"interesting_without_phase":bool(c_no_phase.get("eligible")),"candidate_score":round(num(c.get("score"),0),2),"risk_profile":c.get("profile"),"official_selected":official,
                "official_units":official_units,"official_stake_eur":official_stake,"official_reason":official_reason,"preview_selected":preview,"rejection_reasons":reasons,"selection_status":status,
                "slate_score":round(num(r.get("slate_score"),0),2),"slate_grade":r.get("slate_grade"),"stability_alert":r.get("stability_alert"),"stability_delta":round(num(r.get("stability_delta"),0),6),"p_structural_raw":round(num(r.get("p_structural_raw"),.5),6),
                "home_lineup_confirmed":bool((ctx.get("home_lineup") or {}).get("confirmed")),"home_lineup_count":int(num((ctx.get("home_lineup") or {}).get("count"),0)),"away_lineup_confirmed":bool((ctx.get("away_lineup") or {}).get("confirmed")),"away_lineup_count":int(num((ctx.get("away_lineup") or {}).get("count"),0)),
                "home_starter":ctx.get("home_sp"),"away_starter":ctx.get("away_sp"),"unit_eur":round(UNIT,4),"result_status":"PENDING","result":None,"home_score":None,"away_score":None,"settled_at":None,"hypothetical_profit_1u_eur":None,"official_profit_eur":None})
    return out


def v1010_log_journal(journal,added=0,settled_now=0):
    m=v1010_journal_metrics(journal)
    logging.info("V%s LIVE JOURNAL | rows=%d +%d | settled=%d (+%d) | priced=%d hypROI=%s | official_settled=%d officialROI=%s",VERSION,m["rows"],added,m["settled"],settled_now,m["priced"],pct(m["hyp_roi"]) if m["hyp_roi"] is not None else "-",m["official_settled"],pct(m["official_roi"]) if m["official_roi"] is not None else "-")


def v10_self_test():
    global VERSION
    current=VERSION;VERSION="10.0.10"
    try:_V1010_SELF_TEST_011()
    finally:VERSION=current
    assert VERSION=="10.0.11"
    assert v1011_effective_probability(.40,"ML","FINAL")<.50 and v1011_effective_probability(.60,"ML","FINAL")>.50
    fake={"phase":"FINAL","quality":.85,"stability_alert":"OK","game_pk":77,"ctx":{"home":"H","away":"A","home_sp":"Starter H","away_sp":"Starter A","home_lineup":{"count":9},"away_lineup":{"count":9}}}
    rec_low={"market":"ML","name":"H","point":None,"p_model":.70,"p_effective":.63,"p_push":0,"confidence":8.0,"refs":3,"p_market":.58,"min_price_effective":1.75,"winamax_eval":{"price":1.45}}
    rec_high=dict(rec_low);rec_high["winamax_eval"]={"price":2.10}
    c1=v1011_candidate(fake,rec_low,True);c2=v1011_candidate(fake,rec_high,True)
    assert c1["eligible"] and c2["eligible"] and abs(c1["score"]-c2["score"])<1e-9
    rec_none=dict(rec_low);rec_none["winamax_eval"]={};c3=v1011_candidate(fake,rec_none,True);assert not c3["eligible"] and any("indisponible" in x for x in c3["reasons"])
    assert "info" in v1011_option_line(fake,rec_low).lower()
    print("SELF-TEST MLB BETTING BOT V10.0.11 OK")

'''

path.write_text(text.replace(marker,layer+marker,1),encoding='utf-8')
print('Applied V10.0.11 layer')
