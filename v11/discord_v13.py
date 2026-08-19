from __future__ import annotations

import os

from . import core
from . import discord_v123 as base
from . import v13_discord_delivery as delivery
from . import v138_live_change

VERSION_LABEL = "V13.6 EVIDENCE ANALYTICS"
base.VERSION_LABEL = VERSION_LABEL

# Discord embed accent palette. The color is deterministic per game so adjacent
# matchup cards are visually distinct while a critical resend keeps the same
# identity as the original card.
_MATCH_COLORS = (
    ("🔵", 0x5865F2),
    ("🟣", 0x9B59B6),
    ("🟢", 0x2ECC71),
    ("🟠", 0xE67E22),
    ("🔴", 0xE74C3C),
    ("🟡", 0xF1C40F),
    ("🩵", 0x1ABC9C),
    ("🩷", 0xE91E63),
)


def _label(r):
    if r.get("market") == "ML":
        return f"{r.get('name')} ML"
    if r.get("market") == "RUNLINE":
        return f"{r.get('name')} {core.num(r.get('point')):+g}"
    return f"{str(r.get('name')).title()} {core.num(r.get('point')):g}"


def _price_text(value):
    return "—" if value is None or core.num(value) <= 1 else f"{core.num(value):.2f}"


def _fair_odds(p):
    p = core.num(p, 0)
    return "—" if p <= 0 or p >= 1 else f"{1 / p:.2f}"


def _primary_probability(option):
    if not isinstance(option, dict):
        return None
    for key in ("p_predictive_final", "p_baseball_calibrated", "p_baseball_raw"):
        value = option.get(key)
        if value is not None:
            p = core.num(value, -1)
            if 0 <= p <= 1:
                return p
    return None


def _probability_text(option):
    p = _primary_probability(option)
    return "**—**" if p is None else f"**{100 * p:.1f}%**"


def _line(r):
    """Compact compatibility renderer used by older Discord helpers."""
    return f"**{_label(r)}**  {_probability_text(r)}"


def _game_color(game_pk):
    token = str(game_pk or "0")
    try:
        index = int(token) % len(_MATCH_COLORS)
    except Exception:
        index = sum(ord(ch) for ch in token) % len(_MATCH_COLORS)
    return _MATCH_COLORS[index]


def _same_team(option, team):
    return core.norm_name(option.get("name")) == core.norm_name(team)


def _find_ml(options, team):
    return next(
        (
            option
            for option in options
            if str(option.get("market") or "").upper() == "ML" and _same_team(option, team)
        ),
        None,
    )


def _find_runline(options, team, point):
    return next(
        (
            option
            for option in options
            if str(option.get("market") or "").upper() == "RUNLINE"
            and _same_team(option, team)
            and abs(core.num(option.get("point"), 999) - float(point)) <= 1e-6
        ),
        None,
    )


def _total_pair(options, result):
    canonical = ((result.get("canonical_lines") or {}).get("TOTAL"))
    if canonical is not None:
        point = core.num(canonical)
        over = next(
            (
                o
                for o in options
                if str(o.get("market") or "").upper() == "TOTAL"
                and str(o.get("name") or "").lower() == "over"
                and abs(core.num(o.get("point"), 999) - point) <= 1e-6
            ),
            None,
        )
        under = next(
            (
                o
                for o in options
                if str(o.get("market") or "").upper() == "TOTAL"
                and str(o.get("name") or "").lower() == "under"
                and abs(core.num(o.get("point"), 999) - point) <= 1e-6
            ),
            None,
        )
        if over or under:
            return point, over, under

    by_point = {}
    for option in options:
        if str(option.get("market") or "").upper() != "TOTAL" or option.get("point") is None:
            continue
        point = core.num(option.get("point"))
        side = str(option.get("name") or "").lower()
        if side in {"over", "under"}:
            by_point.setdefault(point, {})[side] = option
    complete = [(point, sides) for point, sides in by_point.items() if {"over", "under"} <= set(sides)]
    if complete:
        # Prefer the line closest to the middle of the available total surface.
        points = sorted(point for point, _ in complete)
        target = points[len(points) // 2]
        sides = dict(complete)[target]
        return target, sides.get("over"), sides.get("under")
    if by_point:
        point = sorted(by_point)[0]
        sides = by_point[point]
        return point, sides.get("over"), sides.get("under")
    return None, None, None


def _lineup_status(lineup):
    lineup = lineup or {}
    count = int(core.num(lineup.get("count")))
    if count >= 9:
        return "✅ 9/9"
    if count > 0:
        return f"🟡 {count}/9"
    return "⚪ —"


def _starter_status(name):
    return f"✅ {name}" if name else "⚪ —"


def _scoreboard_fields(result):
    ctx = result["ctx"]
    options = list(result.get("options") or [])
    away, home = ctx["away"], ctx["home"]

    away_ml = _find_ml(options, away)
    home_ml = _find_ml(options, home)
    away_plus = _find_runline(options, away, +1.5)
    away_minus = _find_runline(options, away, -1.5)
    home_plus = _find_runline(options, home, +1.5)
    home_minus = _find_runline(options, home, -1.5)
    total_point, over, under = _total_pair(options, result)

    ml = (
        f"✈️ **{away}**  ·  {_probability_text(away_ml)}\n"
        f"🏠 **{home}**  ·  {_probability_text(home_ml)}"
    )
    runline = (
        f"✈️ **{away}**   `+1.5` {_probability_text(away_plus)}   │   `-1.5` {_probability_text(away_minus)}\n"
        f"🏠 **{home}**   `+1.5` {_probability_text(home_plus)}   │   `-1.5` {_probability_text(home_minus)}"
    )
    total_label = "TOTAL" if total_point is None else f"TOTAL {total_point:g}"
    totals = f"📈 **OVER**  {_probability_text(over)}    │    📉 **UNDER**  {_probability_text(under)}"

    dq = result.get("data_quality") or {}
    model = result.get("model") or {}
    projection = f"{away} **{core.num(result.get('amu')):.1f}**  —  **{core.num(result.get('hmu')):.1f}** {home}"
    snapshot = (
        f"🎯 Projection  {projection}\n"
        f"🧠 DQ **{100 * core.num(dq.get('model_input_score')):.0f}/100**  •  "
        f"Phase **{str(result.get('phase') or '—').upper()}**  •  "
        f"Model **{model.get('version') or 'structural'}**"
    )

    features = result.get("features") or {}
    weather = features.get("weather") or {}
    weather_txt = "🌦️ météo —"
    if weather.get("available"):
        weather_txt = (
            f"🌦️ {core.num(weather.get('temperature_c')):.0f}°C  •  "
            f"vent {core.num(weather.get('wind_kph')):.0f} km/h  •  "
            f"hum. {core.num(weather.get('humidity_pct')):.0f}%"
        )
    personnel = (
        f"✈️ {_lineup_status(ctx.get('away_lineup'))}  •  SP {_starter_status(ctx.get('away_sp'))}\n"
        f"🏠 {_lineup_status(ctx.get('home_lineup'))}  •  SP {_starter_status(ctx.get('home_sp'))}\n"
        f"{weather_txt}"
    )

    return [
        ("🏆 MONEYLINE", ml),
        ("⚾ RUN LINE ±1.5", runline),
        (f"📊 {total_label}", totals),
        ("🧭 GAME SNAPSHOT", snapshot),
        ("👥 STATUS", personnel),
    ]


def send_game(result, portfolio):
    gid = result.get("game_pk")
    final_only = str(os.getenv("V13_DISCORD_FINAL_ONLY", "0")).lower() in {"1", "true", "yes"}
    if final_only and str(result.get("phase") or "").upper() != "FINAL":
        core.logging.info("Discord V13 scheduled mode: phase %s supprimée gamePk=%s", result.get("phase"), gid)
        return True
    force = str(os.getenv("V13_FORCE_DISCORD_RESEND", "0")).lower() in {"1", "true", "yes"}
    decision = {"send": True, "reason": "FORCED" if force else "NOT_SENT", "critical_change": False}
    if not force:
        decision = delivery.delivery_decision(gid, result)
        if not decision.get("send"):
            core.logging.info("Discord V13 livraison supprimée gamePk=%s reason=%s", gid, decision.get("reason"))
            return True

    ctx = result["ctx"]
    color_dot, embed_color = _game_color(gid)
    fields = _scoreboard_fields(result)
    if decision.get("critical_change"):
        fields.insert(0, ("🔄 MISE À JOUR CRITIQUE", str(decision.get("reason") or "personnel / données modifiés")))

    title = f"{color_dot} ⚾ {ctx['away']} @ {ctx['home']}  •  {str(result.get('phase') or '').upper()}"
    ok = core.send_embed(title, fields, embed_color)
    if ok:
        delivery.mark_sent(
            gid,
            phase=result.get("phase"),
            model_generation=result.get("model_generation"),
            analysis_signature=v138_live_change.signature(result),
            personnel_state=v138_live_change.personnel_state(result),
            delivery_reason=str(decision.get("reason") or "NORMAL"),
        )
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
