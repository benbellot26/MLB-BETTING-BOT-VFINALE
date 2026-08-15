from __future__ import annotations

from . import core

VERSION_LABEL = "V12.3.2"


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
    ref_price = g.get("price")
    winamax_price = g.get("winamax_price") or e.get("price")
    mini, ev = g.get("required_price"), g.get("ev_at_price")
    min_conf = g.get("min_confidence")
    state = "✅ RECOMMANDÉ" if e.get("official_selected") else "🟢 QUALIFIÉ" if g.get("ok") and dq.get("eligible") else "⚪ NON RETENU"
    source = r.get("line_source") or "—"
    execution = "oui" if r.get("execution_available") else "non"
    ref_source = str(g.get("price_source") or "—").replace("sharp_", "")
    ref_count = int(core.num(g.get("reference_quote_count")))
    return (
        f"{state} • **{_label(r)}**\n"
        f"p {VERSION_LABEL} **{core.pct(r.get('p_effective'))}**"
        +(f" • seuil **{core.pct(min_conf)}**" if min_conf is not None else "")+
        f" • prudent **{core.pct(g.get('p_conservative'))}** • incert. **{core.pct(r.get('model_uncertainty'))}** • DQ **{100*core.num(dq.get('score')):.0f}/100**\n"
        f"sharp **{core.pct(r.get('p_market'))}** ({int(core.num(r.get('refs')))} refs) • "
        f"ligne **{source}** • exécution Winamax **{execution}**\n"
        f"cote réf. sharp **{_price_text(ref_price)}** ({ref_source}, {ref_count} quote{'s' if ref_count != 1 else ''}) • "
        f"Winamax **{_price_text(winamax_price)}**"
        +(f" • mini value **{core.num(mini):.2f}**" if mini else "")
        +(f" • EV prudent **{100*core.num(ev):+.1f}%**" if ev is not None else "")
    )


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
    weather = f.get("weather") or {}
    wt = "indisponible"
    if weather.get("available"):
        wt = f"{core.num(weather.get('temperature_c')):.0f}°C • vent {core.num(weather.get('wind_kph')):.0f} km/h • humidité {core.num(weather.get('humidity_pct')):.0f}%"
    fields = [
        ("🧭 En bref", brief), ("🌦️ Contexte", wt),
        ("🏆 Moneyline", "\n\n".join(_line(x) for x in groups["ML"]) or "—"),
        ("⚾ Run Line", "\n\n".join(_line(x) for x in groups["RUNLINE"][:6]) or "—"),
        ("📊 Totals", "\n\n".join(_line(x) for x in groups["TOTAL"][:6]) or "—"),
    ]
    return core.send_embed(f"⚾ MLB {VERSION_LABEL} • {ctx['away']} @ {ctx['home']}", fields, 5763719)


def send_top(results):
    ok = True
    for m, title in (("ML", f"🏆 TOP 3 ML {VERSION_LABEL}"), ("RUNLINE", f"⚾ TOP 3 RUN LINE {VERSION_LABEL}"), ("TOTAL", f"📈 TOP 3 TOTAL {VERSION_LABEL}")):
        pool = []
        for r in results:
            for o in r.get("options") or []:
                if o.get("market") == m:
                    pool.append((core.num(o.get("selection_score")), r, o))
        pool.sort(key=lambda x: x[0], reverse=True)
        seen, out = set(), []
        for _, r, o in pool:
            if str(r.get("game_pk")) in seen:
                continue
            seen.add(str(r.get("game_pk")))
            out.append(f"**#{len(out)+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{_line(o)}")
            if len(out) == 3:
                break
        ok = core.send_embed(title, [("Classement", "\n\n".join(out) if out else "Aucune option.")], 16766720) and ok
    return ok


def send_plan(chosen, combo, portfolio, pool):
    simple = "\n\n".join(
        f"**#{i+1} {_label(c['rec'])} — {core.num((c['rec'].get('winamax_eval') or {}).get('official_units')):g}u recommandées**\n"
        f"Réf. sharp {_price_text(c['gate'].get('price'))} • EV prudent {100*core.num(c['gate'].get('ev_at_price')):+.1f}% • "
        f"DQ {100*core.num(c['dq'].get('score')):.0f}/100"
        for i, c in enumerate(chosen)
    ) or "**AUCUNE RECOMMANDATION SIMPLE.**"
    ctext = f"⚪ Combinés officiels désactivés en {VERSION_LABEL} tant que la dépendance n'est pas validée."
    status = (f"Bankroll référence **{core.num(portfolio.get('bankroll_eur')):.2f}€** • exposition recommandée "
              f"**{core.num(portfolio.get('allocated')):.2f}€** • staking **{portfolio.get('staking')}**")
    return core.send_embed(f"🎟️ RECOMMANDATIONS {VERSION_LABEL}", [("✅ Simples", simple), ("🔗 Combiné", ctext), ("📊 Portfolio", status)], 5763719,
                           description="Sélection informative basée sur modèle + EV/edge + DQ + cote sharp de référence. Winamax n'est qu'une cote d'exécution éventuelle; le ledger ne considère une mise réelle qu'après confirmation.")


def send_health(h):
    sharp, win = h.get("sharp_coverage") or {}, h.get("winamax_coverage") or {}
    txt = (
        f"Planifiés **{h.get('scheduled_games',0)}** • appariés **{h.get('matched_events',0)}** • analysés **{h.get('analyzed_games',0)}**\n"
        f"Starters confirmés/utilisables **{h.get('confirmed_starters',0)}/{h.get('usable_starters',0)}** • "
        f"lineups complètes/utilisables **{h.get('confirmed_lineups',0)}/{h.get('usable_lineups',0)}** • DQ moyenne **{100*core.num(h.get('mean_data_quality')):.0f}/100**\n"
        f"Sharp ML/RL/T **{sharp.get('ML',0)}/{sharp.get('RUNLINE',0)}/{sharp.get('TOTAL',0)}** • "
        f"Winamax **{win.get('ML',0)}/{win.get('RUNLINE',0)}/{win.get('TOTAL',0)}**"
    )
    return core.send_embed(f"🩺 DATA HEALTH {VERSION_LABEL}", [("Couverture", txt)], 5763719)


def _research_pct(value):
    return "—" if value is None else f"{100*core.num(value):.1f}%"


def _research_num(value, digits=4, signed=False):
    if value is None:
        return "—"
    fmt = f"{{:{'+' if signed else ''}.{digits}f}}"
    return fmt.format(core.num(value))


def _research_variant_line(label, metrics):
    metrics = metrics or {}
    return (
        f"**{label}** • B {_research_num(metrics.get('brier'))} • LL {_research_num(metrics.get('logloss'))} • "
        f">55 **{_research_pct(metrics.get('gt55_hit_rate'))}** ({int(core.num(metrics.get('gt55_n')))})"
    )


def send_research_monitor(monitor):
    progress = monitor.get("progress") or {}
    variants = monitor.get("variants") or {}
    settled = int(core.num(progress.get("settled_games")))
    minimum = max(1, int(core.num(progress.get("minimum_games"), 75)))
    remaining = max(0, int(core.num(progress.get("remaining_to_minimum"))))
    active = "ACTIVE" if progress.get("optimized_shadow_active") else "OFF jusqu'au seuil"
    head = (
        f"Évidence canonique **{settled}/{minimum} matchs** • reste **{remaining}** • statut **{progress.get('status') or 'COLLECTING'}**\n"
        f"V12.4 optimized **{active}** • 1 gamePk = 1 observation • dernier snapshot pré-match"
    )

    variant_lines = []
    labels = {
        "baseline_v1232": "V12.3.2",
        "all_core": "V12.4 all_core",
        "optimized": "V12.4 optimized",
        "ensemble": "V12.4 ensemble",
    }
    for name in ("baseline_v1232", "all_core", "optimized", "ensemble"):
        if name in variants:
            variant_lines.append(_research_variant_line(labels[name], variants[name]))
    if not variant_lines:
        variant_lines.append("Aucun match V12.4 réglé pour l'instant.")

    ablation_lines = []
    for item in (monitor.get("ablations") or {}).values():
        ablation_lines.append(
            f"**{item.get('label')}** • w {core.num(item.get('weight')):.2f} • **{item.get('verdict') or 'WATCH'}** • "
            f"ΔB {_research_num(item.get('brier_improvement'), signed=True)} • ΔLL {_research_num(item.get('logloss_improvement'), signed=True)}"
        )
    if not ablation_lines:
        ablation_lines.append("Diagnostics modules en attente.")

    evolution = monitor.get("evolution") or {}
    if evolution.get("has_previous"):
        evo_lines = [f"Nouveaux matchs réglés depuis le rapport précédent : **{int(core.num(evolution.get('settled_games_delta'))):+d}**"]
        for name in ("all_core", "optimized"):
            change = (evolution.get("variants") or {}).get(name)
            if change:
                evo_lines.append(
                    f"{labels[name]} • ΔB {_research_num(change.get('brier'), signed=True)} • ΔLL {_research_num(change.get('logloss'), signed=True)}"
                )
        evolution_text = "\n".join(evo_lines)
    else:
        evolution_text = "Premier rapport comparable du Research Monitor."

    disagreements = []
    for item in monitor.get("current_run_disagreements") or []:
        point = "" if item.get("point") is None else f" {core.num(item.get('point')):+g}"
        flag = " 🔄55" if item.get("crosses_55") else ""
        disagreements.append(
            f"**{item.get('game')}** • {item.get('market')} {item.get('name')}{point} • "
            f"{_research_pct(item.get('baseline_p'))} → **{_research_pct(item.get('v124_p'))}** "
            f"({_research_pct(abs(core.num(item.get('gap'))))} écart){flag}"
        )
    disagreement_text = "\n".join(disagreements[:6]) or "Aucun écart ≥5 pp ni franchissement du seuil 55% sur ce run."

    v115 = monitor.get("v115") or {}
    v115_text = (
        f"Matchs réglés **{int(core.num(v115.get('settled_games')))}** • consensus >55 **{_research_pct(v115.get('consensus_gt55_hit_rate'))}** "
        f"({int(core.num(v115.get('consensus_gt55_n')))}) • désaccords forts **{int(core.num(v115.get('strong_disagreement_n')))}**"
    )

    fields = [
        ("🧪 Progression", head),
        ("📐 V12.3.2 vs V12.4", "\n".join(variant_lines)),
        ("🧩 Ablations / poids", "\n".join(ablation_lines)),
        ("📈 Évolution", evolution_text),
        ("⚡ Désaccords du run", disagreement_text),
        ("👻 V11.5 shadow", v115_text),
        ("🔒 Garde-fou", "**RESEARCH ONLY** • selector/Kelly/staking/Discord picks inchangés • aucune promotion automatique."),
    ]
    return core.send_embed(
        "🧪 V12.4 RESEARCH MONITOR",
        fields,
        10181046,
        description="Suivi expérimental des challengers. Ce message n'est pas une recommandation de pari et ne peut pas bloquer la publication V12.3.2.",
    )
