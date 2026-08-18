from __future__ import annotations

from . import core
from . import discord_v123 as base

VERSION_LABEL = "V13.5"
base.VERSION_LABEL = VERSION_LABEL


def _label(r):
    if r.get("market") == "ML":
        return f"{r.get('name')} ML"
    if r.get("market") == "RUNLINE":
        return f"{r.get('name')} {core.num(r.get('point')):+g}"
    return f"{str(r.get('name')).title()} {core.num(r.get('point')):g}"


def _price_text(value):
    return "—" if value is None or core.num(value) <= 1 else f"{core.num(value):.2f}"


def _line(r):
    e = r.get("winamax_eval") or {}
    g = e.get("v11_price_gate") or {}
    dq = r.get("data_quality") or {}
    state = "✅ RECOMMANDÉ" if e.get("official_selected") else "🟢 QUALIFIÉ" if g.get("ok") and dq.get("eligible") else "⚪ NON RETENU"
    gap = r.get("model_market_gap")
    gap_txt = "—" if gap is None else f"{100*core.num(gap):+.1f} pp"
    lo, hi = r.get("probability_interval_low"), r.get("probability_interval_high")
    interval = "—" if lo is None or hi is None else f"{core.pct(lo)}–{core.pct(hi)}"
    push = r.get("p_push")
    push_txt = "" if not push else f" • push **{core.pct(push)}**"
    ref_price = g.get("price")
    winamax_price = g.get("winamax_price") or e.get("price")
    cal_source = str(r.get("calibration_source_v13") or "identity")
    prob_label = "Baseball estimé" if cal_source == "identity" else "Baseball calibré"
    phase_n = int(core.num(r.get("calibration_phase_n_v13")))
    market_n = int(core.num(r.get("calibration_market_n_v13")))
    unc = r.get("probability_uncertainty_v13") or {}
    market_disp = unc.get("market_disagreement_sigma")
    market_disp_txt = "—" if market_disp is None else f"{100*core.num(market_disp):.1f} pp"
    return (
        f"{state} • **{_label(r)}**\n"
        f"{prob_label} **{core.pct(r.get('p_baseball_calibrated'))}** • brut **{core.pct(r.get('p_baseball_raw'))}**"
        f" • intervalle modèle 90% **{interval}**{push_txt}\n"
        f"Sharp **{core.pct(r.get('p_market'))}** • gap modèle/marché **{gap_txt}** • désaccord books **{market_disp_txt}**\n"
        f"Calibration **{cal_source}** • n phase **{phase_n}** • n marché **{market_n}**\n"
        f"Posterior forecast-only **{core.pct(r.get('p_posterior'))}** • DQ modèle **{100*core.num(dq.get('model_input_score')):.0f}/100** • DQ exécution **{100*core.num(dq.get('score')):.0f}/100**\n"
        f"Cote réf. **{_price_text(ref_price)}** • Winamax **{_price_text(winamax_price)}**"
        +(f" • EV prudent **{100*core.num(g.get('ev_at_price')):+.1f}%**" if g.get("ev_at_price") is not None else "")
    )


def _lineup_status(lineup):
    lineup = lineup or {}
    count = int(core.num(lineup.get("count")))
    if count >= 9:
        return f"✅ **CONFIRMÉE {min(count, 9)}/9**"
    if count > 0:
        return f"🟡 **PARTIELLE {count}/9**"
    return "⚪ **NON PUBLIÉE**"


def _starter_status(name):
    return f"🟡 **PROBABLE/ANNONCÉ** — {name}" if name else "⚪ **NON ANNONCÉ**"


def send_game(result, portfolio):
    ctx = result["ctx"]
    groups = {"ML": [], "RUNLINE": [], "TOTAL": []}
    for r in result.get("options") or []:
        groups.setdefault(r.get("market"), []).append(r)
    model, con, f = result.get("model") or {}, result.get("con") or {}, result.get("features") or {}
    bootstrap = model.get("historical_bootstrap") or {}
    brief = (
        f"Phase **{result.get('phase')}** • modèle **{model.get('version') or 'structural-only'}**\n"
        f"Projection **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**\n"
        f"Sharp ML refs **{int(core.num(con.get('n')))}** • dispersion **{core.num(model.get('dispersion')):.2f}** • "
        f"env σ **{core.num(model.get('environment_sigma')):.3f}** • bootstrap **{bootstrap.get('status') or '—'}**"
    )
    personnel = (
        f"**{ctx['away']}** • lineup {_lineup_status(ctx.get('away_lineup'))}\n"
        f"Starter {_starter_status(ctx.get('away_sp'))}\n"
        f"**{ctx['home']}** • lineup {_lineup_status(ctx.get('home_lineup'))}\n"
        f"Starter {_starter_status(ctx.get('home_sp'))}"
    )
    weather = f.get("weather") or {}
    wt = "indisponible"
    if weather.get("available"):
        wt = f"{core.num(weather.get('temperature_c')):.0f}°C • vent {core.num(weather.get('wind_kph')):.0f} km/h • humidité {core.num(weather.get('humidity_pct')):.0f}%"
    fields = [
        ("🧭 En bref", brief),
        ("👥 Lineups & starters", personnel),
        ("🌦️ Contexte", wt),
        ("🏆 Moneyline", "\n\n".join(_line(x) for x in groups["ML"]) or "—"),
        ("⚾ Run Line", "\n\n".join(_line(x) for x in groups["RUNLINE"][:6]) or "—"),
        ("📊 Totals", "\n\n".join(_line(x) for x in groups["TOTAL"][:6]) or "—"),
    ]
    return core.send_embed(f"⚾ MLB {VERSION_LABEL} • {ctx['away']} @ {ctx['home']}", fields, 5763719)


base._line = _line
base._label = _label
base._price_text = _price_text

send_top = base.send_top
send_plan = base.send_plan
send_health = base.send_health
send_research_monitor = base.send_research_monitor
