from __future__ import annotations
from . import core

def _label(rec):
    if rec.get("market")=="ML":return f"{rec.get('name')} ML"
    if rec.get("market")=="RUNLINE":return f"{rec.get('name')} {core.num(rec.get('point')):+g}"
    return f"{str(rec.get('name')).title()} {core.num(rec.get('point')):g}"

def _status(rec):
    e=rec.get("winamax_eval") or {};gate=e.get("v11_price_gate") or {}
    if e.get("official_selected"):return f"✅ OFFICIEL {core.num(e.get('official_units'),1):g}u"
    if gate.get("ok"):return "🟢 OPTION INTÉRESSANTE"
    if not gate.get("price"):return "⏳ Winamax indisponible"
    return "⚪ Valeur insuffisante"

def _line(rec):
    e=rec.get("winamax_eval") or {};gate=e.get("v11_price_gate") or {};price=gate.get("price") or e.get("price");ptxt=f"{core.num(price):.2f}" if price else "—";mini=gate.get("required_price");mt=f" • mini V11 **{core.num(mini):.2f}**" if mini else ""
    return f"{_status(rec)} • **{_label(rec)}**\nChance V11 **{core.pct(rec.get('p_effective'))}** • conf. **{2*core.num(rec.get('confidence')):.1f}/20** • sharp **{core.pct(rec.get('p_market'))}** ({int(core.num(rec.get('refs')))} refs) • Winamax **{ptxt}**{mt}"

def send_game(result,portfolio):
    ctx=result["ctx"];opts=result.get("options") or [];con=result.get("con") or {};market_side=ctx["home"] if core.num(con.get("p"),.5)>=.5 else ctx["away"]
    market_prob=max(core.num(con.get("p"),.5),1-core.num(con.get("p"),.5)) if con.get("p") is not None else None
    brief=f"Phase **{result.get('phase')}**\nMoteur V11 : **{ctx['home']} {core.pct(result.get('p_home'))}**\nMarché sharp : **{market_side} {core.pct(market_prob)}** ({int(core.num(con.get('n')))} refs)\nScore projeté : **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**"
    teams=f"{ctx['away']} : {core.lineup_text(ctx.get('away_lineup'))} • starter **{ctx.get('away_sp') or '—'}**\n{ctx['home']} : {core.lineup_text(ctx.get('home_lineup'))} • starter **{ctx.get('home_sp') or '—'}**"
    groups={"ML":[],"RUNLINE":[],"TOTAL":[]}
    for x in opts:groups.get(x.get("market"),[]).append(x)
    official=[x for x in opts if (x.get("winamax_eval") or {}).get("official_selected")];decision="\n".join(f"• ✅ **{_label(x)} — {core.num((x.get('winamax_eval') or {}).get('official_units'),1):g}u**" for x in official) or "**Aucun pari officiel sur ce match.**"
    fields=[("🧭 En bref",brief),("👥 Équipes",teams),("🏆 Vainqueur — les 2 côtés","\n\n".join(_line(x) for x in groups["ML"]) or "—"),("⚾ Handicap — les 2 côtés","\n\n".join(_line(x) for x in groups["RUNLINE"]) or "—"),("📊 Total — Over / Under","\n\n".join(_line(x) for x in groups["TOTAL"]) or "—"),("✅ Décision du bot",decision),("ℹ️ Lecture","**Toutes les probabilités affichées sont V11** : ML, Run Line et Total. Le consensus sharp est un benchmark/blend contrôlé, jamais une vérité. Une option n'est officielle que si la cote Winamax passe le value gate V11.")]
    return core.send_embed(f"⚾ MLB V11 • {ctx['away']} @ {ctx['home']}",fields,5763719)

def send_top(results):
    for market,title in (("ML","🏆 TOP 3 — VAINQUEUR V11"),("RUNLINE","⚾ TOP 3 — HANDICAP V11"),("TOTAL","📈 TOP 3 — TOTAL V11")):
        pool=[]
        for r in results:
            for rec in r.get("options") or []:
                if rec.get("market")==market:pool.append((core.num(rec.get("selection_score")),core.num(rec.get("p_effective")),r,rec))
        pool.sort(reverse=True,key=lambda x:(x[0],x[1]));blocks=[];seen=set()
        for _,_,r,rec in pool:
            gid=str(r.get("game_pk"))
            if gid in seen:continue
            seen.add(gid);blocks.append(f"**#{len(blocks)+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{_line(rec)}")
            if len(blocks)>=3:break
        core.send_embed(title,[("Classement V11","\n\n".join(blocks) if blocks else "Aucune option.")],16766720)

def _combo_text(combo):
    if not combo or not combo.get("available"):return "**Aucun combiné V11.**"
    lines=[]
    for i,c in enumerate(combo.get("legs") or [],1):
        r,rec=c["result"],c["rec"];lines.append(f"**{i}. {_label(rec)}** — {r['ctx']['away']} @ {r['ctx']['home']} • {core.pct(rec.get('p_effective'))} • cote {core.num((rec.get('winamax_eval') or {}).get('price')):.2f}")
    tail=f"\n\n✅ **COMBINÉ OFFICIEL — {core.num(combo.get('units')):g}u** • proba {core.pct(combo.get('probability'))} • cote {core.num(combo.get('winamax_price')):.2f} • EV {100*core.num(combo.get('ev')):+.1f}%" if combo.get("official") else f"\n\n⚪ Non joué — {combo.get('reason')}"
    return "\n\n".join(lines)+tail

def send_plan(chosen,combo,portfolio,pool):
    plan="\n\n".join(f"**#{i+1} ✅ {_label(c['rec'])} — {core.num((c['rec'].get('winamax_eval') or {}).get('official_units')):g}u**\n{c['result']['ctx']['away']} @ {c['result']['ctx']['home']} • chance {core.pct(c['rec'].get('p_effective'))} • score {core.num(c['score']):.0f}/100 • Winamax {core.num(c['gate'].get('price')):.2f}" for i,c in enumerate(chosen)) or "**AUCUN PARI SIMPLE OFFICIEL.**"
    others=[];chosen_ids={id(c["rec"]) for c in chosen}
    for c in pool:
        if id(c["rec"]) in chosen_ids:continue
        others.append(f"• **{_label(c['rec'])}** • {core.pct(c['rec'].get('p_effective'))} • score {core.num(c['score']):.0f}/100")
        if len(others)>=5:break
    status=f"Simples : **{portfolio.get('official_count',0)}/3** • exposition : **{core.num(portfolio.get('official_units'))+core.num(portfolio.get('combo_units')):g}/4u**"
    return core.send_embed("🎟️ PLAN OFFICIEL V11",[("✅ Paris simples",plan),("🔗 Combiné V11",_combo_text(combo)),("🟢 Autres options","\n".join(others) if others else "Aucune."),("📊 Journée",status),("ℹ️ Règle","V11 est le seul moteur de sélection : ML, Run Line, Total et combiné. Price gate Winamax obligatoire.")],5763719)
