from pathlib import Path

p=Path('bot.py')
text=p.read_text(encoding='utf-8')
tag='# ==================== V10.0.9 DISCORD SIMPLE ====================='
if tag in text:
    raise SystemExit(0)
marker='\nif __name__=="__main__":\n'
if marker not in text:
    raise SystemExit('final __main__ marker not found')

block=r'''
# ==================== V10.0.9 DISCORD SIMPLE =====================
# Presentation-only layer for a beginner-friendly Discord UX.
# All advanced stats remain in the model/history but are hidden from Discord.
_V1008_SELF_TEST_009=v10_self_test

VERSION="10.0.9"

def v1009_phase_text(phase):
    phase=str(phase or "EARLY").upper()
    return {
        "EARLY":"🟡 EARLY — aperçu, pas de pari officiel",
        "LATE":"🟠 LATE — analyse affinée avant match",
        "FINAL":"🟢 FINAL — version la plus fiable avant match",
    }.get(phase,phase)

def v1009_lineup_text(lineup):
    lineup=lineup or {};count=int(num(lineup.get("count"),0))
    if bool(lineup.get("confirmed")) and count>=8:return f"✅ confirmée ({count}/9)"
    return f"🟠 projetée / non confirmée ({count}/9)"

def v1009_market_label(rec):
    if not rec:return "—"
    market=rec.get("market")
    if market=="ML":return f"Vainqueur : {rec.get('name','—')}"
    if market=="RUNLINE":return f"Handicap : {rec.get('name','—')} {num(rec.get('point')):+g}"
    if market=="TOTAL":
        side="Plus de" if str(rec.get("name","")).lower()=="over" else "Moins de"
        return f"Total : {side} {num(rec.get('point')):g} runs"
    return str(rec.get("name","—"))

def v1009_pick_status(rec,phase):
    if not rec:return "⚪ Pas de recommandation"
    e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);minimum=num(rec.get("min_price_effective",rec.get("min_price")),0)
    if e.get("official_selected"):
        units=int(num(e.get("official_units",e.get("units",1)),1));return f"✅ PARI OFFICIEL — {units}u"
    if str(phase).upper()=="EARLY":return "👀 À SURVEILLER — attendre LATE/FINAL"
    if price<=1:return "⏳ Cote Winamax absente"
    if minimum>1 and price+1e-9<minimum:return "❌ Cote Winamax trop basse"
    return "⚪ Non retenu dans le plan officiel"

def v1009_pick_text(rec,phase):
    if not rec:return "⚪ Aucune recommandation claire."
    pe=num(rec.get("p_effective",rec.get("p_model")),.5);conf=num(rec.get("confidence"),0);minimum=num(rec.get("min_price_effective",rec.get("min_price")),0);e=rec.get("winamax_eval") or {};price=num(e.get("price"),0)
    price_txt=f"{price:.2f}" if price>1 else "—"
    return f"**{v1009_market_label(rec)}**\nChance estimée **{pct(pe)}** • confiance **{conf:.1f}/10**\nCote mini **{minimum:.2f}** • Winamax **{price_txt}** • {v1009_pick_status(rec,phase)}"

def v1009_market_summary(result):
    ctx=result["ctx"];p=num(result.get("con",{}).get("p"),.5);n=int(num(result.get("con",{}).get("n"),0))
    if n<=0:return "Marché de référence indisponible"
    side=ctx["home"] if p>=.5 else ctx["away"];prob=p if p>=.5 else 1-p
    return f"Marché : **{side} {pct(prob)}** ({n} books)"

def v1009_ml_summary(result):
    rec=(result.get("model_recs") or {}).get("ML");ctx=result["ctx"]
    if rec:return f"Modèle : **{rec.get('name','—')} {pct(num(rec.get('p_effective',rec.get('p_model')),.5))}**"
    p=num(result.get("p_model"),.5);side=ctx["home"] if p>=.5 else ctx["away"];return f"Modèle : **{side} {pct(max(p,1-p))}**"

def send_game(result,snap,portfolio):
    ctx=result["ctx"];v=result["verdict"];_,_,color=confidence_band(v["confidence"]);recs=result.get("model_recs",{});phase=result.get("phase","EARLY")
    summary=(f"{v1009_phase_text(phase)}\n"
             f"{v1009_ml_summary(result)}\n"
             f"{v1009_market_summary(result)}\n"
             f"Score projeté : **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**")
    teams=(f"{ctx['away']} : {v1009_lineup_text(ctx.get('away_lineup'))}\n"
           f"{ctx['home']} : {v1009_lineup_text(ctx.get('home_lineup'))}\n"
           f"Lanceurs prévus : **{ctx['away_sp']}** / **{ctx['home_sp']}**")
    picks=(f"🏆 {v1009_pick_text(recs.get('ML'),phase)}\n\n"
           f"⚾ {v1009_pick_text(recs.get('RUNLINE'),phase)}\n\n"
           f"📈 {v1009_pick_text(recs.get('TOTAL'),phase)}")
    selected=[]
    for rec in recs.values():
        if not rec:continue
        e=rec.get("winamax_eval") or {}
        if e.get("official_selected"):selected.append(f"• **{v1009_market_label(rec)}** — {int(num(e.get('official_units',1),1))}u @ {num(e.get('price')):.2f}")
    verdict="\n".join(selected) if selected else ("**Aucun pari officiel.** Relancer en LATE/FINAL pour une décision plus fiable." if phase=="EARLY" else "**Aucun pari officiel sur ce match.**")
    help_txt="ML = vainqueur • Handicap/RL = avance ou retard en runs • Total = nombre total de runs. **Cote mini** = ne pas jouer en dessous."
    return send_embed(f"⚾ {ctx['away']} @ {ctx['home']} • {phase}",[("🧭 En bref",summary),("👥 Équipes",teams),("🎯 Paris possibles",picks),("✅ Décision du bot",verdict),("ℹ️ Repères",help_txt)],color)

def v1009_top_line(result,rec,index):
    phase=result.get("phase","EARLY");e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "—";pe=num(rec.get("p_effective",rec.get("p_model")),.5);minimum=num(rec.get("min_price_effective",rec.get("min_price")),0)
    return f"**#{index} {v1009_market_label(rec)}**\n{result['ctx']['away']} @ {result['ctx']['home']} • {phase}\nChance **{pct(pe)}** • conf. **{num(rec.get('confidence')):.1f}/10** • mini **{minimum:.2f}** • Winamax **{price_txt}**"

def send_top_messages(results,state):
    ok=True
    for market,title in (("ML","🏆 TOP 3 — VAINQUEUR (informatif)"),("RUNLINE","⚾ TOP 3 — HANDICAP (informatif)"),("TOTAL","📈 TOP 3 — TOTAL (informatif)")):
        xs=[(r,(r.get("model_recs") or {}).get(market)) for r in results if (r.get("model_recs") or {}).get(market)]
        xs=sorted(xs,key=lambda x:(num(x[1].get("p_effective",x[1].get("p_model")),.5),num(x[1].get("confidence"))),reverse=True)[:3]
        txt="\n\n".join(v1009_top_line(r,rec,i+1) for i,(r,rec) in enumerate(xs)) if xs else "Aucune recommandation claire."
        ok=send_embed(title,[("Classement du modèle",txt),("ℹ️ Important","Ce classement est informatif. **Seul le PLAN OFFICIEL est destiné à être joué.**")],16766720) and ok
    logging.info("Top 3 simplifiés envoyés");return ok

def send_daily_plan(results):
    official=[]
    for r in results:
        for rec in (r.get("model_recs") or {}).values():
            if not rec:continue
            e=rec.get("winamax_eval") or {}
            if e.get("official_selected"):
                official.append((r,rec,e))
    official.sort(key=lambda x:(num(x[1].get("p_effective",x[1].get("p_model")),.5),num(x[1].get("confidence"))),reverse=True)
    if official:
        lines=[]
        for i,(r,rec,e) in enumerate(official,1):
            lines.append(f"**#{i} {v1009_market_label(rec)}** — **{int(num(e.get('official_units',1),1))}u** @ **{num(e.get('price')):.2f}**\n{r['ctx']['away']} @ {r['ctx']['home']} • chance {pct(num(rec.get('p_effective',rec.get('p_model')),.5))} • conf. {num(rec.get('confidence')):.1f}/10")
        plan="\n\n".join(lines)
    else:
        phases=sorted({r.get("phase","EARLY") for r in results});plan="**AUCUN PARI OFFICIEL SUR CE RUN.**\n"+("Les matchs sont encore en EARLY : relancer plus près du début des rencontres." if phases==["EARLY"] else "Aucune sélection ne passe tous les filtres du bot.")
    slate=_V1007_LAST_SLATE or {};score=num(slate.get("score"),0);grade=slate.get("grade","FAIBLE");units=int(num(slate.get("units"),0));count=int(num(slate.get("official_count"),len(official)))
    status=f"Qualité de la journée : **{grade} ({score:.0f}/100)**\nParis officiels : **{count}/3** • exposition : **{units}/4u**"
    return send_embed("🎟️ PLAN OFFICIEL",[("✅ À jouer selon le bot",plan),("📊 Journée",status),("ℹ️ Règle","Les Top 3 sont des idées à surveiller. **Seuls les paris listés ici sont officiels.**")],5763719)

def v10_self_test():
    global VERSION
    current=VERSION;VERSION="10.0.8"
    try:_V1008_SELF_TEST_009()
    finally:VERSION=current
    assert VERSION=="10.0.9"
    assert "EARLY" in v1009_phase_text("EARLY")
    assert "confirmée" in v1009_lineup_text({"confirmed":True,"count":9})
    fake={"market":"ML","name":"Team A","p_effective":.61,"confidence":7.2,"min_price_effective":1.75,"winamax_eval":{"price":1.80,"official_selected":True,"official_units":1}}
    assert "PARI OFFICIEL" in v1009_pick_text(fake,"FINAL") and "Vainqueur" in v1009_market_label(fake)
    print("SELF-TEST MLB BETTING BOT V10.0.9 OK")
'''

head,tail=text.rsplit(marker,1)
p.write_text(head+'\n\n'+block+'\n'+marker+tail,encoding='utf-8')
