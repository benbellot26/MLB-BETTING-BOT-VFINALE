from pathlib import Path

p=Path('bot.py')
s=p.read_text(encoding='utf-8')
marker='if __name__=="__main__":\n'
if marker not in s:
    raise SystemExit('main marker not found')
if 'V10.0.12 PHASE-OPEN OFFICIAL PLAN' in s:
    print('V10.0.12 already applied')
    raise SystemExit(0)

layer=r'''

# ==================== V10.0.12 PHASE-OPEN OFFICIAL PLAN =====================
# Selection-only layer:
# - official bets are allowed in EARLY, LATE and FINAL
# - phase is always displayed clearly; EARLY/LATE should be rechecked later
# - Winamax price AND Winamax market availability are informational only
# - statistical quality gates remain active; no forced weak pick fallback
_V1011_SELF_TEST_012=v10_self_test

VERSION="10.0.12"
SELECTION_VERSION="phase-open-winamax-info-v3"


def v1012_phase_badge(phase):
    phase=str(phase or "EARLY").upper()
    if phase=="FINAL":return "🟢 FINAL"
    if phase=="LATE":return "🟠 LATE — à reconfirmer en FINAL"
    return "🟡 EARLY — à reconfirmer en LATE/FINAL"


def v1012_ensure_execution(rec):
    e=rec.get("winamax_eval")
    if not isinstance(e,dict) or not e:
        e={"price":0.0,"synthetic_execution":True,"winamax_available":False}
        rec["winamax_eval"]=e
    else:
        e["winamax_available"]=num(e.get("price"),0)>1
    e["price_gate_enabled"]=False
    e["price_informational"]=True
    e["availability_gate_enabled"]=False
    return e


def v1011_candidate(result,rec,require_phase=True):
    # `require_phase` is intentionally ignored in V10.0.12: EARLY/LATE/FINAL
    # can all produce official bets. The phase remains visible to the user.
    reasons=[];phase=str(result.get("phase","EARLY")).upper();market=rec.get("market");pe=num(rec.get("p_effective"),.5)
    conf=num(rec.get("confidence"),0);q=num(result.get("quality"),0);refs=int(num(rec.get("refs"),0));alert=result.get("stability_alert","OK")
    e=v1012_ensure_execution(rec);price=num(e.get("price"),0)
    if pe<V1007_MIN_EFFECTIVE.get(market,.60):reasons.append(f"proba effective {pe*100:.1f}% trop faible")
    if conf<V1007_MIN_CONF:reasons.append(f"confiance {conf:.1f}< {V1007_MIN_CONF:.1f}")
    if q<V1007_MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10 insuffisante")
    if refs<V1007_MIN_REFS:reasons.append(f"seulement {refs} book(s) référence")
    if alert in ("HIGH","FLIP"):reasons.append(f"instabilité modèle {alert}")
    score=60+120*(pe-.58)+4*(conf-6.5)+15*(q-.70)+2*min(refs,4)
    if alert=="WATCH":score-=6
    score=clamp(score,0,100)
    # 2u remains FINAL-only: EARLY/LATE can be official, but stay at 1u.
    premium=(phase=="FINAL" and pe>=V1007_PREMIUM_EFFECTIVE and conf>=V1007_PREMIUM_CONF and q>=V1007_PREMIUM_QUALITY and refs>=V1007_PREMIUM_REFS and result.get("stability_alert")=="OK" and result["ctx"]["home_lineup"].get("count",0)>=8 and result["ctx"]["away_lineup"].get("count",0)>=8 and v1007_starters_ok(result["ctx"]))
    return {"eligible":not reasons,"reasons":reasons,"score":score,"units":2 if premium else 1,"profile":v1011_profile(rec),"result":result,"rec":rec,"price":price,"minimum":num(rec.get("min_price_effective"),0),"premium":premium}


def allocate_portfolio(results):
    global _V10_LAST_PORTFOLIO,_V1007_LAST_SLATE
    if not results or not all(("option_recs" in r or "model_recs" in r) for r in results):
        return _V1010_ALLOCATE_011(results)
    for r in results:
        for e in r.get("evals",[]):
            e.update({"selected":False,"units":0.0,"stake_eur":0.0,"official_selected":False,"official_units":0,"official_preview_units":0})
        for rec in v1011_iter_options(r):
            e=v1012_ensure_execution(rec)
            e.update({"official_v1012":True,"official_selected":False,"official_units":0,"official_preview_units":0,
                      "official_reason":"hors plan officiel","price_gate_enabled":False,"price_informational":True,
                      "availability_gate_enabled":False})
    slate=v1011_build_slate(results,True);chosen=[];used_games=set();profiles={};units_used=0;thresholds=(70,72,74)
    for c in slate["pool"]:
        if len(chosen)>=slate["max_bets"] or len(chosen)>=V1007_MAX_OFFICIAL_BETS:break
        if c["score"]<thresholds[len(chosen)]:break
        gid=str(c["result"]["game_pk"]);profile=c["profile"]
        if gid in used_games:continue
        e=v1012_ensure_execution(c["rec"])
        if profiles.get(profile,0)>=2:
            e["official_reason"]="corrélation: déjà 2 paris du même profil";continue
        units=c["units"]
        if units_used+units>V1007_MAX_DAILY_UNITS:
            if units==2 and units_used+1<=V1007_MAX_DAILY_UNITS:units=1
            else:e["official_reason"]="plafond quotidien 4u";continue
        e.update({"selected":True,"official_selected":True,"official_units":units,"units":float(units),"stake_eur":round(units*UNIT,2),
                  "qualified":True,"model_recommended":True,"reason":"OK V10.0.12","portfolio_reason":"PARI OFFICIEL V10.0.12",
                  "official_reason":f"retenu dans le plan officiel ({str(c['result'].get('phase','EARLY')).upper()})",
                  "candidate_units":float(units),"candidate_stake_eur":round(units*UNIT,2)})
        chosen.append(c);used_games.add(gid);profiles[profile]=profiles.get(profile,0)+1;units_used+=units
    chosen_ids={id(c["rec"]) for c in chosen}
    for c in slate["pool"]:
        e=v1012_ensure_execution(c["rec"])
        if id(c["rec"]) not in chosen_ids and e.get("official_reason")=="hors plan officiel":
            e["official_reason"]="option intéressante non retenue par le Slate Score / limite 0-3"
    allocated=round(units_used*UNIT,2);cap=round(V1007_MAX_DAILY_UNITS*UNIT,2)
    _V1007_LAST_SLATE={"score":slate["score"],"grade":slate["grade"],"max_bets":slate["max_bets"],"official_count":len(chosen),"units":units_used,"preview_count":0}
    _V10_LAST_PORTFOLIO={"daily_cap":cap,"allocated":allocated,"remaining":round(cap-allocated,2),"game_cap":round(2*UNIT,2),"slate_score":slate["score"],"slate_grade":slate["grade"],"official_count":len(chosen),"official_units":units_used}
    for r in results:r["slate_score"]=slate["score"];r["slate_grade"]=slate["grade"]
    logging.info("V10.0.12 PHASE-OPEN SLATE | score=%.1f grade=%s max=%d selected=%d units=%du/%du | phase gate=OFF | Winamax gates=OFF",slate["score"],slate["grade"],slate["max_bets"],len(chosen),units_used,V1007_MAX_DAILY_UNITS)
    return _V10_LAST_PORTFOLIO


def v1011_plan_pick_text(item,index=None):
    r=item["result"];rec=item["rec"];e=v1012_ensure_execution(rec);u=int(num(e.get("official_units"),0));price=num(e.get("price"),0);prefix=f"**#{index}** " if index is not None else "• "
    price_txt=f"{price:.2f}" if price>1 else "non récupérée"
    return f"{prefix}✅ **{v1011_market_label(rec)} — {u}u = {u*UNIT:.2f} €**\n{r['ctx']['away']} @ {r['ctx']['home']} • **{v1012_phase_badge(r.get('phase'))}**\nChance prudente **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • Winamax **{price_txt}** *(info)*"


def plan_pick_text(item,index=None):return v1011_plan_pick_text(item,index)


def send_daily_plan(results):
    official=v1011_selected_items(results)
    plan="\n\n".join(v1011_plan_pick_text(x,i+1) for i,x in enumerate(official)) if official else "**AUCUN PARI OFFICIEL SUR CE RUN.** Aucun candidat ne passe actuellement les seuils statistiques minimums."
    others=[];official_ids={id(x["rec"]) for x in official}
    for c in v1011_build_slate(results,False)["pool"]:
        if id(c["rec"]) in official_ids:continue
        e=v1012_ensure_execution(c["rec"]);price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "—"
        others.append(f"• **{v1011_market_label(c['rec'])}** • {c['result']['ctx']['away']} @ {c['result']['ctx']['home']} • **{v1012_phase_badge(c['result'].get('phase'))}** • {pct(c['rec'].get('p_effective'))} • conf {num(c['rec'].get('confidence')):.1f}/10 • Winamax {price_txt} *(info)*")
        if len(others)>=5:break
    other_txt="\n".join(others) if others else "Aucune autre option ne passe actuellement les filtres statistiques."
    slate=_V1007_LAST_SLATE or {};status=f"Qualité de la journée : **{slate.get('grade','FAIBLE')} ({num(slate.get('score')):.0f}/100)**\nParis officiels : **{int(num(slate.get('official_count'),len(official)))}/3** • exposition : **{int(num(slate.get('units'),0))}/4u**"
    rule="Le Plan Officiel peut maintenant contenir des paris **EARLY, LATE ou FINAL**. Un pari EARLY/LATE reste officiel pour le run courant mais doit idéalement être **recontrôlé sur un run plus proche du match**. Winamax est 100 % informatif : ni le niveau de cote ni l'absence de cote dans le flux ne bloquent la sélection."
    return send_embed("🎟️ PLAN OFFICIEL",[("✅ À jouer selon le bot",plan),("🟢 Autres options intéressantes",other_txt),("📊 Journée",status),("ℹ️ Règle",rule)],5763719)


def v10_self_test():
    global VERSION
    current=VERSION;VERSION="10.0.11"
    try:_V1011_SELF_TEST_012()
    finally:VERSION=current
    assert VERSION=="10.0.12"
    fake={"phase":"EARLY","quality":.90,"stability_alert":"OK","game_pk":88,"ctx":{"home":"H","away":"A","home_sp":"Starter H","away_sp":"Starter A","home_lineup":{"count":0},"away_lineup":{"count":0}}}
    rec={"market":"ML","name":"H","point":None,"p_model":.74,"p_effective":.625,"p_push":0,"confidence":8.0,"refs":4,"p_market":.60,"min_price_effective":1.70,"winamax_eval":None}
    c=v1011_candidate(fake,rec,True)
    assert c["eligible"] and c["units"]==1 and rec.get("winamax_eval") is not None
    assert rec["winamax_eval"].get("availability_gate_enabled") is False
    assert "EARLY" in v1012_phase_badge("EARLY") and "FINAL" in v1012_phase_badge("FINAL")
    print("SELF-TEST MLB BETTING BOT V10.0.12 OK")

'''

s=s.replace(marker,layer+marker,1)
p.write_text(s,encoding='utf-8')
print('Applied V10.0.12 layer')
