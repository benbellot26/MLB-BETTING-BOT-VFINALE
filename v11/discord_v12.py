from __future__ import annotations
from . import core


def _label(r):
    if r.get("market")=="ML":return f"{r.get('name')} ML"
    if r.get("market")=="RUNLINE":return f"{r.get('name')} {core.num(r.get('point')):+g}"
    return f"{str(r.get('name')).title()} {core.num(r.get('point')):g}"


def _line(r):
    e=r.get("winamax_eval") or {}; g=e.get("v11_price_gate") or {}; dq=r.get("data_quality") or {}
    price=g.get("price") or e.get("price"); mini=g.get("required_price"); ev=g.get("ev_at_price")
    state="✅ OFFICIEL" if e.get("official_selected") else "🟢 QUALIFIÉ" if g.get("ok") and dq.get("eligible") else "⚪ NON RETENU"
    return (f"{state} • **{_label(r)}**\n"
            f"p V12 **{core.pct(r.get('p_effective'))}** • prudent **{core.pct(g.get('p_conservative'))}** • "
            f"incert. **{core.pct(r.get('model_uncertainty'))}** • DQ **{100*core.num(dq.get('score')):.0f}/100**\n"
            f"sharp **{core.pct(r.get('p_market'))}** ({int(core.num(r.get('refs')))} refs) • Winamax **{core.num(price):.2f}**"
            +(f" • mini **{core.num(mini):.2f}**" if mini else "")+(f" • EV prudent **{100*core.num(ev):+.1f}%**" if ev is not None else ""))


def send_game(result,portfolio):
    ctx=result["ctx"]; groups={"ML":[],"RUNLINE":[],"TOTAL":[]}
    for r in result.get("options") or []:groups.setdefault(r.get("market"),[]).append(r)
    model=result.get("model") or {}; con=result.get("con") or {}; f=result.get("features") or {}
    brief=(f"Phase **{result.get('phase')}** • modèle **{model.get('version') or 'structural-only'}**\n"
           f"Projection **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**\n"
           f"Sharp ML refs **{int(core.num(con.get('n')))}** • dispersion runs **{core.num(model.get('dispersion')):.2f}**")
    weather=f.get("weather") or {}; wt="indisponible"
    if weather.get("available"):wt=f"{core.num(weather.get('temperature_c')):.0f}°C • vent {core.num(weather.get('wind_kph')):.0f} km/h • humidité {core.num(weather.get('humidity_pct')):.0f}%"
    fields=[("🧭 En bref",brief),("🌦️ Contexte",wt),
            ("🏆 Moneyline","\n\n".join(_line(x) for x in groups["ML"]) or "—"),
            ("⚾ Run Line","\n\n".join(_line(x) for x in groups["RUNLINE"][:6]) or "—"),
            ("📊 Totals","\n\n".join(_line(x) for x in groups["TOTAL"][:6]) or "—")]
    return core.send_embed(f"⚾ MLB V12 • {ctx['away']} @ {ctx['home']}",fields,5763719)


def send_top(results):
    for m,title in (("ML","🏆 TOP 3 ML V12"),("RUNLINE","⚾ TOP 3 RUN LINE V12"),("TOTAL","📈 TOP 3 TOTAL V12")):
        pool=[]
        for r in results:
            for o in r.get("options") or []:
                if o.get("market")==m:pool.append((core.num(o.get("selection_score")),r,o))
        pool.sort(key=lambda x:x[0],reverse=True); seen=set(); out=[]
        for _,r,o in pool:
            if str(r.get("game_pk")) in seen:continue
            seen.add(str(r.get("game_pk"))); out.append(f"**#{len(out)+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{_line(o)}")
            if len(out)==3:break
        core.send_embed(title,[("Classement","\n\n".join(out) if out else "Aucune option.")],16766720)


def send_plan(chosen,combo,portfolio,pool):
    simple="\n\n".join(f"**#{i+1} {_label(c['rec'])} — {core.num((c['rec'].get('winamax_eval') or {}).get('official_units')):g}u**\nEV prudent {100*core.num(c['gate'].get('ev_at_price')):+.1f}% • DQ {100*core.num(c['dq'].get('score')):.0f}/100" for i,c in enumerate(chosen)) or "**AUCUN PARI SIMPLE OFFICIEL.**"
    if combo and combo.get("official"):
        legs=" + ".join(_label(c["rec"]) for c in combo.get("legs") or []); ctext=f"✅ **{legs}** • {core.num(combo.get('units')):g}u • EV {100*core.num(combo.get('ev')):+.1f}%"
    else:ctext="⚪ Aucun combiné officiel."
    status=f"Bankroll **{core.num(portfolio.get('bankroll_eur')):.2f}€** • exposition **{core.num(portfolio.get('allocated')):.2f}€** • staking **{portfolio.get('staking')}**"
    return core.send_embed("🎟️ PLAN OFFICIEL V12",[("✅ Simples",simple),("🔗 Combiné",ctext),("📊 Portfolio",status)],5763719)


def send_health(h):
    sharp=h.get("sharp_coverage") or {}; win=h.get("winamax_coverage") or {}
    txt=(f"Planifiés **{h.get('scheduled_games',0)}** • appariés **{h.get('matched_events',0)}** • analysés **{h.get('analyzed_games',0)}**\n"
         f"Starters **{h.get('confirmed_starters',0)}** • lineups complètes **{h.get('confirmed_lineups',0)}** • DQ moyenne **{100*core.num(h.get('mean_data_quality')):.0f}/100**\n"
         f"Sharp ML/RL/T **{sharp.get('ML',0)}/{sharp.get('RUNLINE',0)}/{sharp.get('TOTAL',0)}** • Winamax **{win.get('ML',0)}/{win.get('RUNLINE',0)}/{win.get('TOTAL',0)}**")
    return core.send_embed("🩺 DATA HEALTH V12",[("Couverture",txt)],5763719)
