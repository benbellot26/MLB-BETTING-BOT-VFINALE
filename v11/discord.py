from __future__ import annotations

def send_game(core,result,portfolio):
    ctx=result["ctx"]; opts=core.v1011_iter_options(result); phase=core.v1009_phase_text(result.get("phase")); raw=core.num(result.get("p_model"),.5); side=ctx["home"] if raw>=.5 else ctx["away"]; raw_side=max(raw,1-raw); con=result.get("con") or {}; market_side=ctx["home"] if core.num(con.get("p"),.5)>=.5 else ctx["away"]; market_p=max(core.num(con.get("p"),.5),1-core.num(con.get("p"),.5)) if con.get("p") is not None else None
    brief=f"{phase}\nModèle brut : **{side} {core.pct(raw_side)}**\nMarché réf. : **{market_side} {core.pct(market_p)}** ({int(core.num(con.get('n'),0))} books)\nScore projeté : **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**"
    teams=f"{ctx['away']} : {core.v1009_lineup_text(ctx.get('away_lineup'))} • starter **{ctx.get('away_sp','—')}**\n{ctx['home']} : {core.v1009_lineup_text(ctx.get('home_lineup'))} • starter **{ctx.get('home_sp','—')}**"
    ml=[x for x in opts if x.get("market")=="ML"]; rl=[x for x in opts if x.get("market")=="RUNLINE"]; tot=[x for x in opts if x.get("market")=="TOTAL"]
    official=[x for x in opts if (x.get("winamax_eval") or {}).get("official_selected")]
    decision="\n".join(f"• ✅ **{core.v1011_market_label(x)} — {core.num((x.get('winamax_eval') or {}).get('official_units'),1):g}u**" for x in official) or "**Aucun pari officiel sur ce match.** Les options ci-dessus restent visibles pour comparaison."
    fields=[("🧭 En bref",brief),("👥 Équipes",teams),("🏆 Vainqueur — les 2 côtés","\n\n".join(core.v1011_option_line(result,x) for x in ml) or "—"),("⚾ Handicap ±1,5 — les 2 côtés","\n\n".join(core.v1011_option_line(result,x) for x in rl) or "—"),("📊 Total — meilleur Over + meilleur Under","\n\n".join(core.v1011_option_line(result,x) for x in tot) or "—"),("✅ Décision du bot",decision),("ℹ️ Lecture","V11 sépare **qualité du pronostic** et **valeur du pari**. Une option ne devient officielle que si la cote Winamax exacte est disponible et atteint le prix minimum V11 (EV + edge + marge de sécurité). RL/Total restent V10 tant que leurs challengers V11 ne sont pas validés.")]
    return core.send_embed(f"⚾ MLB V11 • {ctx['away']} @ {ctx['home']}",fields,5763719)

def _combo_text(core,combo):
    if not combo or not combo.get("available"):return "**Aucun combiné.** Il faut au moins 2 options value-gated sur 2 matchs différents."
    lines=[]
    for i,c in enumerate(combo.get("legs") or [],1):
        r=c["result"]; rec=c["rec"]; e=rec.get("winamax_eval") or {}; price=core.num(e.get("price"),0); gate=e.get("v11_price_gate") or {}; lines.append(f"**{i}. {core.v1011_market_label(rec)}** — {r['ctx']['away']} @ {r['ctx']['home']}\nChance **{core.pct(rec.get('p_effective'))}** • Winamax **{price:.2f}** • mini V11 **{core.num(gate.get('required_price'),0):.2f}**")
    if combo.get("official"):
        tail=f"\n\n✅ **COMBINÉ OFFICIEL — {core.num(combo.get('units'),0):g}u**\nProbabilité combinée ≈ **{core.pct(combo.get('probability'))}** • cote **{core.num(combo.get('winamax_price'),0):.2f}** • EV **{100*core.num(combo.get('ev'),0):+.1f}%**"
    else:tail=f"\n\n⚪ **Combiné non joué** — {combo.get('reason','non retenu')}"
    return "\n\n".join(lines)+tail

def send_daily_plan(core,results):
    official=core.v1011_selected_items(results); plan="\n\n".join(core.v1011_plan_pick_text(x,i+1) for i,x in enumerate(official)) if official else "**AUCUN PARI SIMPLE OFFICIEL SUR CE RUN.**"
    combo=getattr(core,"_V1013_LAST_COMBO",None) or {}; others=[]; official_ids={id(x["rec"]) for x in official}; combo_ids={id(c["rec"]) for c in (combo.get("legs") or [])}
    for c in core.v1011_build_slate(results,False)["pool"]:
        if id(c["rec"]) in official_ids or id(c["rec"]) in combo_ids:continue
        e=c["rec"].get("winamax_eval") or {}; price=core.num(e.get("price"),0); gate=e.get("v11_price_gate") or {}; status="✅ valeur OK" if gate.get("ok") else "⚪ valeur insuffisante"
        others.append(f"• **{core.v1011_market_label(c['rec'])}** • {c['result']['ctx']['away']} @ {c['result']['ctx']['home']} • {core.pct(c['rec'].get('p_effective'))} • Winamax {price:.2f} • {status}")
        if len(others)>=5:break
    slate=getattr(core,"_V1007_LAST_SLATE",{}) or {}; total_units=core.num(slate.get("units"),0)+(core.num(combo.get("units"),0) if combo.get("official") else 0)
    status=f"Qualité de la journée : **{slate.get('grade','FAIBLE')} ({core.num(slate.get('score')):.0f}/100)**\nParis simples : **{int(core.num(slate.get('official_count'),len(official)))}/3** • combiné : **{'OUI' if combo.get('official') else 'NON'}** • exposition totale : **{total_units:g}/4u**"
    rule="Le Plan Officiel V11 est **value-gated** : une cote Winamax trop basse bloque le pari même si le pronostic est fort. Limites : **3 simples + 1 combiné 2 legs**, **4u max**, **1 simple par match**. Les challengers RL/Total ne remplacent V10 qu'après validation chronologique + live."
    return core.send_embed("🎟️ PLAN OFFICIEL",[("✅ Paris simples",plan),("🔗 Combiné officiel — 2 sélections",_combo_text(core,combo)),("🟢 Autres options intéressantes", "\n".join(others) if others else "Aucune autre option."),("📊 Journée",status),("ℹ️ Règle",rule)],5763719)
