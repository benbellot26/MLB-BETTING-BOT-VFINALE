from __future__ import annotations

import os

from . import core
from . import discord_v123 as base
from . import v13_discord_delivery as delivery

VERSION_LABEL = "V13.6 EVIDENCE ANALYTICS"
base.VERSION_LABEL = VERSION_LABEL


def _label(r):
    if r.get("market") == "ML":
        return f"{r.get('name')} ML"
    if r.get("market") == "RUNLINE":
        return f"{r.get('name')} {core.num(r.get('point')):+g}"
    return f"{str(r.get('name')).title()} {core.num(r.get('point')):g}"


def _price_text(value):
    return "—" if value is None or core.num(value) <= 1 else f"{core.num(value):.2f}"


def _fair_odds(p):
    p=core.num(p,0)
    return "—" if p <= 0 or p >= 1 else f"{1/p:.2f}"


def _line(r):
    e = r.get("winamax_eval") or {}
    g = e.get("v11_price_gate") or {}
    dq = r.get("data_quality") or {}
    gap = r.get("model_market_gap")
    gap_txt = "—" if gap is None else f"{100*core.num(gap):+.1f} pp"
    lo, hi = r.get("probability_interval_low"), r.get("probability_interval_high")
    interval = "—" if lo is None or hi is None else f"{core.pct(lo)}–{core.pct(hi)}"
    push = r.get("p_push")
    push_txt = "" if not push else f" • push {core.pct(push)}"
    ref_price = g.get("price")
    winamax_price = g.get("winamax_price") or e.get("price")
    cal_source = str(r.get("calibration_source_v13") or "identity")
    cal_status = "COLLECTING" if cal_source == "identity" else "ACTIVE"
    phase_n = int(core.num(r.get("calibration_phase_n_v13")))
    market_n = int(core.num(r.get("calibration_market_n_v13")))
    unc = r.get("probability_uncertainty_v13") or {}
    market_disp = unc.get("market_disagreement_sigma")
    market_disp_txt = "—" if market_disp is None else f"{100*core.num(market_disp):.1f} pp"
    primary = r.get("p_predictive_final")
    if primary is None:
        primary = r.get("p_baseball_calibrated")
    market = r.get("p_market")
    posterior = r.get("p_posterior")
    posterior_txt = "—" if posterior is None else core.pct(posterior)
    posterior_weight = 100*core.num(r.get("posterior_weight_v13"))
    weight_source = str(r.get("posterior_weight_source_v13") or "BASEBALL_ONLY")
    return (
        f"🎯 **{_label(r)}**\n"
        f"**MODEL {core.pct(primary)} | MARKET {core.pct(market)} | GAP {gap_txt}**\n"
        f"Probabilité principale **{core.pct(primary)}** • ensemble candidat **{posterior_txt}** (shadow)\n"
        f"Fair modèle **{_fair_odds(primary)}** • fair marché **{_fair_odds(market)}** • réf. **{_price_text(ref_price)}** • Winamax **{_price_text(winamax_price)}**\n"
        f"Bande modèle **{interval}**{push_txt} • DQ modèle **{100*core.num(dq.get('model_input_score')):.0f}/100**\n"
        f"Calibration **{cal_status} / {cal_source}** • n phase **{phase_n}** • n marché **{market_n}**\n"
        f"Brut **{core.pct(r.get('p_baseball_raw'))}** • posterior shadow **{posterior_txt}** (Sharp appris {posterior_weight:.0f}%, {weight_source})\n"
        f"Désaccord books **{market_disp_txt}** • DQ globale **{100*core.num(dq.get('score')):.0f}/100**"
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
    gid=result.get("game_pk")
    final_only=str(os.getenv("V13_DISCORD_FINAL_ONLY","0")).lower() in {"1","true","yes"}
    if final_only and str(result.get("phase") or "").upper()!="FINAL":
        core.logging.info("Discord V13 scheduled mode: phase %s supprimée gamePk=%s",result.get("phase"),gid)
        return True
    force=str(os.getenv("V13_FORCE_DISCORD_RESEND","0")).lower() in {"1","true","yes"}
    if not force and delivery.sent(gid):
        core.logging.info("Discord V13 déjà livré gamePk=%s; doublon inter-run supprimé",gid)
        return True
    ctx = result["ctx"]
    groups = {"ML": [], "RUNLINE": [], "TOTAL": []}
    for r in result.get("options") or []:
        groups.setdefault(r.get("market"), []).append(r)
    model, con, f = result.get("model") or {}, result.get("con") or {}, result.get("features") or {}
    bootstrap = model.get("historical_bootstrap") or {}
    dq=result.get("data_quality") or {}
    brief = (
        f"Phase **{result.get('phase')}** • modèle **{model.get('version') or 'structural-only'}**\n"
        f"Projection **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**\n"
        f"Produit principal **baseball calibré** • marché et posterior **comparateurs/shadow uniquement**\n"
        f"DQ modèle **{100*core.num(dq.get('model_input_score')):.0f}/100** • Sharp ML refs **{int(core.num(con.get('n')))}**\n"
        f"Dispersion **{core.num(model.get('dispersion')):.2f}** • env σ **{core.num(model.get('environment_sigma')):.3f}** • bootstrap **{bootstrap.get('status') or '—'}**"
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
    ok=core.send_embed(f"⚾ MLB {VERSION_LABEL} • {ctx['away']} @ {ctx['home']}", fields, 5763719)
    if ok:
        delivery.mark_sent(gid,phase=result.get("phase"),model_generation=result.get("model_generation"))
    return ok


def send_top(results):
    """Predictive analytics mode deliberately emits no ranking/recommendation card."""
    return True


def send_plan(chosen, combo, portfolio, pool):
    """Predictive analytics mode deliberately emits no betting-plan card."""
    return True


def send_health(health):
    """Per-game analytics mode keeps Discord to one message per game."""
    return True


base._line = _line
base._label = _label
base._price_text = _price_text

send_research_monitor = base.send_research_monitor
