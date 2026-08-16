from __future__ import annotations

from . import core
from . import discord_v123 as base

VERSION_LABEL = "V13"
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
    return (
        f"{state} • **{_label(r)}**\n"
        f"Baseball calibré **{core.pct(r.get('p_baseball_calibrated'))}** • brut **{core.pct(r.get('p_baseball_raw'))}**"
        f" • intervalle 90% **{interval}**{push_txt}\n"
        f"Sharp **{core.pct(r.get('p_market'))}** • gap modèle/marché **{gap_txt}** • "
        f"calibration **{r.get('calibration_source_v13') or 'identity'}** (n={int(core.num(r.get('calibration_n_v13')))})\n"
        f"Posterior forecast-only **{core.pct(r.get('p_posterior'))}** • DQ **{100*core.num(dq.get('score')):.0f}/100**\n"
        f"Cote réf. **{_price_text(ref_price)}** • Winamax **{_price_text(winamax_price)}**"
        +(f" • EV prudent **{100*core.num(g.get('ev_at_price')):+.1f}%**" if g.get("ev_at_price") is not None else "")
    )


# Replace the formatter used by inherited send_game/send_top without duplicating
# the mature Discord transport/limit handling.
base._line = _line
base._label = _label
base._price_text = _price_text

send_game = base.send_game
send_top = base.send_top
send_plan = base.send_plan
send_health = base.send_health
send_research_monitor = base.send_research_monitor
