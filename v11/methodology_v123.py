from __future__ import annotations

import math
import os
from datetime import datetime, timezone

_INSTALLED = False
_core = _market = _context = _config = _pro = _selector = _storage = _engine = _bootstrap = None
_ORIGINALS = {}


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _parse_dt(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def strict_match_odds_events(games, events):
    """Match MLB games to odds events by teams AND start time, fail closed on ambiguity/stale identity."""
    buckets = {}
    for event in events or []:
        key = (_norm(event.get("home_team")), _norm(event.get("away_team")))
        buckets.setdefault(key, []).append(event)
    out = {}
    tolerance = float(getattr(_config, "V123_EVENT_MATCH_MAX_MIN", 120.0))
    for game in games or []:
        teams = game.get("teams") or {}
        home = (((teams.get("home") or {}).get("team") or {}).get("name") or "")
        away = (((teams.get("away") or {}).get("team") or {}).get("name") or "")
        game_dt = _parse_dt(game.get("gameDate"))
        if game_dt is None:
            continue
        candidates = []
        for event in buckets.get((_norm(home), _norm(away)), []):
            event_dt = _parse_dt(event.get("commence_time"))
            if event_dt is None:
                continue
            delta = abs((event_dt-game_dt).total_seconds())/60.0
            if delta <= tolerance:
                candidates.append((delta, event_dt, event))
        if not candidates:
            continue
        candidates.sort(key=lambda x: (x[0], x[1]))
        # A true tie is unsafe (e.g. malformed duplicate event feed): do not guess.
        if len(candidates) > 1 and abs(candidates[0][0]-candidates[1][0]) < 1e-6:
            continue
        out[str(game.get("gamePk"))] = candidates[0][2]
    return out


def fresh_winamax_price(event, market_name, name, point=None):
    """Return an execution price only when Winamax timestamp is present and fresh."""
    market_key = {"ML": "h2h", "RUNLINE": "spreads", "TOTAL": "totals"}[market_name]
    now = _parse_dt(_core.replay_as_of()) if _core.replay_as_of() else datetime.now(timezone.utc)
    max_age = float(getattr(_config, "V123_MAX_WINAMAX_AGE_MIN", 15.0))
    for book in event.get("bookmakers") or []:
        if book.get("key") != _core.WINAMAX_KEY:
            continue
        mkt = next((m for m in book.get("markets") or [] if m.get("key") == market_key), None)
        if not mkt:
            return None
        stamp = mkt.get("last_update") or mkt.get("lastUpdate") or book.get("last_update") or book.get("lastUpdate")
        updated = _parse_dt(stamp)
        if updated is None:
            return None
        age = max(0.0, (now-updated).total_seconds()/60.0)
        if age > max_age:
            return None
        for outcome in mkt.get("outcomes") or []:
            if _norm(outcome.get("name")) != _norm(name):
                continue
            if point is not None and abs(_num(outcome.get("point"), 999)-_num(point)) > 1e-6:
                continue
            price = _num(outcome.get("price"), 0)
            return price if price > 1 else None
        return None
    return None


def _ratio(x, baseline, lo=.75, hi=1.28):
    return max(lo, min(hi, _num(x, baseline)/max(1e-9, _num(baseline, 1.0))))


def _starter_quality(starter, league_era, league_whip):
    starter = starter or {}
    return .68*_ratio(starter.get("era"), league_era)+.32*_ratio(starter.get("whip"), league_whip)


def _rescale_structural_for_v123_starters(home_mu, away_mu, ctx, enhanced_home, enhanced_away, home_pitch, away_pitch):
    lg = _core.league_baselines()
    lgera, lgwhip = _num(lg.get("era"), 4.35), _num(lg.get("whip"), 1.32)
    old_home, old_away = ctx.get("home_starter") or {}, ctx.get("away_starter") or {}
    home_team_era = _num(home_pitch.get("era"), lgera)
    away_team_era = _num(away_pitch.get("era"), lgera)

    old_home_opp = .52*_ratio(away_team_era, lgera)+.48*_starter_quality(old_away, lgera, lgwhip)
    new_home_opp = .52*_ratio(away_team_era, lgera)+.48*_starter_quality(enhanced_away, lgera, lgwhip)
    old_away_opp = .52*_ratio(home_team_era, lgera)+.48*_starter_quality(old_home, lgera, lgwhip)
    new_away_opp = .52*_ratio(home_team_era, lgera)+.48*_starter_quality(enhanced_home, lgera, lgwhip)

    new_h = max(1.8, min(7.5, _num(home_mu)*new_home_opp/max(1e-9, old_home_opp)))
    new_a = max(1.8, min(7.5, _num(away_mu)*new_away_opp/max(1e-9, old_away_opp)))
    return new_h, new_a, {
        "baseline_schema": "v12.3-structural-v1",
        "home_delta": new_h-_num(home_mu), "away_delta": new_a-_num(away_mu),
        "home_old_opponent_factor": old_home_opp, "home_new_opponent_factor": new_home_opp,
        "away_old_opponent_factor": old_away_opp, "away_new_opponent_factor": new_away_opp,
        "starter_model": "current-season + N-1/N-2 prior shrinkage",
    }


def bootstrap_prior_v123(structural_hmu, structural_amu, champ, phase):
    bootstrap = _bootstrap.load_model()
    phase_name = str(phase or "EARLY").upper()
    phase_model = ((champ.get("phase_models") or {}).get(phase_name) or {})
    champion_residual_active = bool(champ.get("active") and (phase_model.get("residual") or {}).get("active"))
    prior_hmu, prior_amu = structural_hmu, structural_amu
    info = {"active": False, "source": "none", "home_delta": 0.0, "away_delta": 0.0}
    if phase_name == "FINAL" and not champion_residual_active and bootstrap.get("eligible_for_final_prior"):
        prior_hmu, prior_amu, info = _bootstrap.apply_final_run_prior(structural_hmu, structural_amu, bootstrap, phase_name)

    dispersion, d_source = _pro.model_dispersion(champ)
    env_sigma, e_source = _pro.model_environment_sigma(champ)
    bd, be = _bootstrap.distribution_defaults(bootstrap)
    if phase_name == "FINAL" and bootstrap.get("eligible_for_final_prior"):
        if d_source == "fixed" and (bootstrap.get("dispersion") or {}).get("active"):
            dispersion, d_source = bd, "v12.3-native-historical-bootstrap"
        if e_source == "fixed" and (bootstrap.get("environment") or {}).get("active"):
            env_sigma, e_source = be, "v12.3-native-historical-bootstrap"
    return prior_hmu, prior_amu, info, bootstrap, dispersion, d_source, env_sigma, e_source


def compose_runtime(structural_hmu, structural_amu, result_like, champ, phase):
    prior_h, prior_a, binfo, bootstrap, dispersion, d_source, env_sigma, e_source = bootstrap_prior_v123(
        structural_hmu, structural_amu, champ, phase
    )
    home_mu, away_mu, learned = _pro.apply_run_correction(prior_h, prior_a, result_like, champ, phase)
    return {
        "home_mu": home_mu, "away_mu": away_mu, "learned": learned,
        "prior_home_mu": prior_h, "prior_away_mu": prior_a,
        "bootstrap_run": binfo, "bootstrap": bootstrap,
        "dispersion": dispersion, "dispersion_source": d_source,
        "environment_sigma": env_sigma, "environment_source": e_source,
    }


def project_v123(game, phase):
    structural_hmu, structural_amu, ctx, features = _engine.legacy._project_runs(game)
    old_home_starter, old_away_starter = dict(ctx.get("home_starter") or {}), dict(ctx.get("away_starter") or {})
    enhanced_home = _engine._enhance_starter(old_home_starter)
    enhanced_away = _engine._enhance_starter(old_away_starter)
    bph = _context.bullpen_state(ctx.get("home_id"), _core.TARGET_DATE)
    bpa = _context.bullpen_state(ctx.get("away_id"), _core.TARGET_DATE)
    weather = _context.weather_for_game(game, ctx.get("home"))
    hh, ah = _core.season_stats(ctx.get("home_id"), "hitting"), _core.season_stats(ctx.get("away_id"), "hitting")
    hp, ap = _core.season_stats(ctx.get("home_id"), "pitching"), _core.season_stats(ctx.get("away_id"), "pitching")

    # V12.3 correction: the enhanced starter model now changes the structural run means themselves.
    structural_hmu, structural_amu, starter_adj = _rescale_structural_for_v123_starters(
        structural_hmu, structural_amu,
        {**ctx, "home_starter": old_home_starter, "away_starter": old_away_starter},
        enhanced_home, enhanced_away, hp, ap,
    )
    ctx["home_starter"], ctx["away_starter"] = enhanced_home, enhanced_away
    home_usable = sum(1 for p in (ctx.get("home_lineup") or {}).get("players") or [] if p.get("ops") is not None)
    away_usable = sum(1 for p in (ctx.get("away_lineup") or {}).get("players") or [] if p.get("ops") is not None)
    features = dict(features or {})
    features.update({
        "weather": weather,
        "bullpen": {"home": bph, "away": bpa, "coverage": min(_num(bph.get("coverage")), _num(bpa.get("coverage")))},
        "park_factor": _core.PARK.get(ctx.get("home"), 1.0),
        "structural_home_mu": structural_hmu, "structural_away_mu": structural_amu,
        "structural_baseline_schema": "v12.3-structural-v1",
        "starter_structural_adjustment": starter_adj,
        "source_quality": {
            "home_team_hitting": bool(hh), "away_team_hitting": bool(ah),
            "home_team_pitching": bool(hp), "away_team_pitching": bool(ap),
            "home_lineup_usable_ops": home_usable, "away_lineup_usable_ops": away_usable,
            "home_starter_current": bool(enhanced_home.get("current_stats_available")),
            "away_starter_current": bool(enhanced_away.get("current_stats_available")),
            "home_starter_prior": bool(enhanced_home.get("prior_available")),
            "away_starter_prior": bool(enhanced_away.get("prior_available")),
        },
    })
    result_like = {"features": features, "ctx": ctx, "phase": phase}
    champ = _pro.load_model()
    stack = compose_runtime(structural_hmu, structural_amu, result_like, champ, phase)
    features.update({
        "historical_bootstrap": {
            "active": bool(stack["bootstrap"].get("active")),
            "eligible_for_final_prior": bool(stack["bootstrap"].get("eligible_for_final_prior")),
            "status": stack["bootstrap"].get("status"), "version": stack["bootstrap"].get("version"),
            "run_prior": stack["bootstrap_run"], "prior_home_mu": stack["prior_home_mu"],
            "prior_away_mu": stack["prior_away_mu"],
        },
        "home_mu": stack["home_mu"], "away_mu": stack["away_mu"],
        "learned_run_adjustment": stack["learned"],
        "run_dispersion": stack["dispersion"], "dispersion_source": stack["dispersion_source"],
        "run_environment_sigma": stack["environment_sigma"], "run_environment_source": stack["environment_source"],
        "distribution": "correlated-negative-binomial-mixture",
    })
    return (structural_hmu, structural_amu, stack["home_mu"], stack["away_mu"], ctx, features,
            champ, stack["dispersion"], stack["environment_sigma"])


def canonical_market_pair_strict(row, market_name):
    opts = [o for o in row.get("options") or [] if o.get("market") == market_name]
    if market_name == "ML":
        home, away = str(row.get("home") or ""), str(row.get("away") or "")
        a = next((o for o in opts if _norm(o.get("name")) == _norm(home)), None)
        b = next((o for o in opts if _norm(o.get("name")) == _norm(away)), None)
        return (a, b) if a and b else (None, None)

    def executable_canonical(o):
        if not o.get("is_canonical_line"):
            return False
        price = _num((o.get("winamax_eval") or {}).get("price"), 0)
        if price <= 1:
            return False
        source = o.get("line_source")
        return source in {None, "winamax"}

    marked = [o for o in opts if executable_canonical(o)]
    if not marked:
        return None, None
    a = marked[0]
    if market_name == "RUNLINE":
        b = next((o for o in marked if _norm(o.get("name")) != _norm(a.get("name"))
                  and o.get("point") is not None and abs(_num(o.get("point"))+_num(a.get("point"))) <= 1e-6), None)
    else:
        b = next((o for o in marked if str(o.get("name") or "").lower() != str(a.get("name") or "").lower()
                  and o.get("point") is not None and abs(_num(o.get("point"))-_num(a.get("point"))) <= 1e-6), None)
    return (a, b) if b else (None, None)


def predict_market_triplet_v123(row, market_name, model):
    bh, ba = _pro.base_runs(row)
    if bh is None or ba is None:
        return None
    phase = str(row.get("phase") or "EARLY").upper()
    stack = compose_runtime(bh, ba, row, model, phase)
    hmu, amu = stack["home_mu"], stack["away_mu"]
    dispersion, env_sigma = stack["dispersion"], stack["environment_sigma"]
    a, b = canonical_market_pair_strict(row, market_name)
    if not a or not b:
        return None
    if market_name == "ML":
        p1 = _engine.prob_home_win(hmu, amu, dispersion, env_sigma)
        p2, push = 1-p1, 0.0
    elif market_name == "RUNLINE":
        p1w, push = _engine.prob_cover_parts(hmu, amu, "home", _num(a.get("point")), dispersion, env_sigma)
        p2w, push2 = _engine.prob_cover_parts(hmu, amu, "away", _num(b.get("point")), dispersion, env_sigma)
        push = (push+push2)/2
        p1, p2 = p1w/max(1e-9, 1-push), p2w/max(1e-9, 1-push)
    else:
        p1w, push = _engine.prob_total_parts(hmu, amu, "over", _num(a.get("point")), dispersion, env_sigma)
        p2w, push2 = _engine.prob_total_parts(hmu, amu, "under", _num(b.get("point")), dispersion, env_sigma)
        push = (push+push2)/2
        p1, p2 = p1w/max(1e-9, 1-push), p2w/max(1e-9, 1-push)
    total = max(1e-9, p1+p2)
    p1, p2 = p1/total, p2/total
    p1, p2 = _pro._blend_saved(p1, a), _pro._blend_saved(p2, b)
    total = max(1e-9, p1+p2)
    p1, p2 = p1/total, p2/total
    q1, q2, qpush, _ = _pro.calibrate_triplet(market_name, p1, p2, push, model, phase)
    return {"win": q1*(1-qpush), "push": qpush, "loss": q2*(1-qpush), "conditional": q1}


def production_evidence_gate_v123(summary):
    settled = int(_num(summary.get("settled_singles")))+int(_num(summary.get("settled_combos")))
    clv_n = int(_num(summary.get("close_candidate_clv_n")))
    mean_clv = summary.get("mean_close_candidate_clv_pct")
    positive_clv = summary.get("positive_close_candidate_clv_rate")
    roi = summary.get("roi")
    volume_ready = settled >= _config.MIN_PROD_SETTLED_BETS and clv_n >= _config.MIN_PROD_CLV_OBSERVATIONS
    clv_safe = mean_clv is not None and _num(mean_clv) >= 0.0 and positive_clv is not None and _num(positive_clv) >= .50
    roi_guard = roi is not None and _num(roi) >= -0.10

    performance = {}
    perf_ready = perf_safe = False
    try:
        from . import journal
        performance = journal.metrics(journal.load_rows())
        qualified = []
        for market_name, m in (performance.get("by_market") or {}).items():
            if int(_num(m.get("n"))) < 50 or m.get("sharp_brier") is None or m.get("sharp_logloss") is None:
                continue
            safe = (_num(m.get("brier"), 9) <= _num(m.get("sharp_brier"), 9)+.005
                    and _num(m.get("logloss"), 9) <= _num(m.get("sharp_logloss"), 9)+.01)
            qualified.append({"market": market_name, "n": m.get("n"), "safe": safe,
                              "brier": m.get("brier"), "sharp_brier": m.get("sharp_brier"),
                              "logloss": m.get("logloss"), "sharp_logloss": m.get("sharp_logloss")})
        perf_ready = bool(qualified)
        perf_safe = perf_ready and all(x["safe"] for x in qualified)
        performance = {"qualified_markets": qualified, "ready": perf_ready, "safe": perf_safe}
    except Exception as exc:
        performance = {"ready": False, "safe": False, "error": type(exc).__name__}

    passes = bool(volume_ready and clv_safe and roi_guard and perf_ready and perf_safe)
    if passes:
        status = "VALIDATED"
    elif volume_ready and (not clv_safe or not roi_guard or (perf_ready and not perf_safe)):
        status = "EVIDENCE_REJECTED"
    else:
        status = "COLLECTING"
    return {
        "passes": passes, "settled_bets": settled, "required_settled_bets": _config.MIN_PROD_SETTLED_BETS,
        "clv_observations": clv_n, "required_clv_observations": _config.MIN_PROD_CLV_OBSERVATIONS,
        "mean_close_candidate_clv_pct": mean_clv, "positive_close_candidate_clv_rate": positive_clv,
        "roi": roi, "volume_ready": volume_ready, "clv_safe": clv_safe, "roi_guard": roi_guard,
        "predictive_quality": performance, "status": status,
        "claim": "live evidence gate; not a guarantee of future profitability",
    }


def selection_score_v123(rec, gate, dq):
    ev = max(-.20, min(.30, _num(gate.get("ev_at_price"), -.20)))
    price = _num(gate.get("price"), 0)
    push = max(0.0, min(.95, _num(gate.get("p_push"), 0)))
    pwin = max(0.0, min(1-push, _num(gate.get("p_win"), 0)))
    breakeven_win = (1-push)/price if price > 1 else 1.0
    # Symmetric value edge: no favorite/underdog bonus based on p > 50%.
    price_edge = max(0.0, pwin-breakeven_win)
    unc = max(0.0, _num(gate.get("uncertainty"), _config.FALLBACK_MODEL_UNCERTAINTY))
    return max(0.0, min(100.0, 45+165*max(0.0, ev)+90*price_edge+18*(dq["score"]-.65)-80*unc))


def allocate_v123(*args, **kwargs):
    portfolio, chosen, combo, pool = _ORIGINALS["selector.allocate"](*args, **kwargs)
    if str(os.getenv("V123_RESEARCH_ONLY", "0")).lower() not in {"1", "true", "yes"}:
        return portfolio, chosen, combo, pool
    # Research runs enrich every option but can never publish/record a recommendation.
    for item in pool:
        e = item["rec"].get("winamax_eval") or {}
        e.update({"official_selected": False, "selected": False, "official_units": 0, "units": 0.0,
                  "stake_eur": 0.0, "official_reason": "research-only V12.3 snapshot"})
    for item in chosen:
        e = item["rec"].get("winamax_eval") or {}
        e.update({"official_selected": False, "selected": False, "official_units": 0, "units": 0.0,
                  "stake_eur": 0.0, "official_reason": "research-only V12.3 snapshot"})
    portfolio = dict(portfolio)
    portfolio.update({"research_only": True, "new_allocated": 0.0, "new_official_count": 0, "new_official_units": 0.0})
    combo = dict(combo or {})
    combo.update({"official": False, "units": 0.0, "reason": "research-only V12.3 snapshot"})
    return portfolio, [], combo, pool


def update_clv_v123(results, analyzed_at=None):
    n = _ORIGINALS["storage.update_clv"](results, analyzed_at)
    # Record line migration explicitly instead of silently dropping the observation.
    state = _storage.open_recommendations()
    by_game = {str(r.get("game_pk")): r for r in results}
    extras = []
    observed_at = analyzed_at or datetime.now(timezone.utc).isoformat()
    for key, bet in state.items():
        if bet.get("bet_type") == "COMBO":
            continue
        result = by_game.get(str(bet.get("game_pk")))
        if not result:
            continue
        exact = next((o for o in result.get("options") or []
                      if _storage.bet_key(result.get("game_pk"), o.get("market"), o.get("name"), o.get("point")) == key), None)
        if exact:
            continue
        alternatives = [o for o in result.get("options") or []
                        if o.get("market") == bet.get("market") and _norm(o.get("name")) == _norm(bet.get("pick"))]
        if alternatives:
            extras.append({"schema": "v12-3-bet-ledger-v1", "event_type": "LINE_MIGRATION_OBSERVATION",
                           "bet_key": key, "status": bet.get("status"), "observed_at": observed_at,
                           "original_point": bet.get("point"),
                           "observed_points": sorted({o.get("point") for o in alternatives if o.get("point") is not None}),
                           "comparable_price_available": False})
    if extras:
        _storage._append_jsonl(_storage.BET_LEDGER_FILE, extras)
    return n+len(extras)


def install():
    global _INSTALLED, _core, _market, _context, _config, _pro, _selector, _storage, _engine, _bootstrap
    if _INSTALLED:
        return
    from . import config, core, market, context, pro_model, selector, storage
    from . import engine_v12
    from . import v123_bootstrap
    _config, _core, _market, _context = config, core, market, context
    _pro, _selector, _storage, _engine, _bootstrap = pro_model, selector, storage, engine_v12, v123_bootstrap

    # New generation: old V12.2 rows and model artifacts cannot silently train V12.3.
    config.VERSION = "12.3-methodology-audit-v1"
    config.SCHEMA_VERSION = "v12-3-professional-v1"
    config.FEATURE_SCHEMA_VERSION = "v12-3-features-v1"
    config.V123_EVENT_MATCH_MAX_MIN = float(os.getenv("V123_EVENT_MATCH_MAX_MIN", "120") or 120)
    config.V123_MAX_WINAMAX_AGE_MIN = float(os.getenv("V123_MAX_WINAMAX_AGE_MIN", "15") or 15)
    config.CLOSING_CANDIDATE_WINDOW_MIN = max(20.0, float(config.CLOSING_CANDIDATE_WINDOW_MIN))

    _ORIGINALS.update({
        "core.match_odds_events": core.match_odds_events,
        "core.winamax_price": core.winamax_price,
        "engine._project": engine_v12._project,
        "pro.canonical_market_pair": pro_model.canonical_market_pair,
        "pro.predict_market_triplet": pro_model.predict_market_triplet,
        "pro.production_evidence_gate": pro_model.production_evidence_gate,
        "selector._score": selector._score,
        "selector.allocate": selector.allocate,
        "storage.update_clv": storage.update_clv,
    })

    core.match_odds_events = strict_match_odds_events
    core.winamax_price = fresh_winamax_price
    engine_v12.historical_bootstrap = v123_bootstrap
    engine_v12._bootstrap_prior = bootstrap_prior_v123
    engine_v12._project = project_v123
    pro_model.compose_runtime = compose_runtime
    pro_model.canonical_market_pair = canonical_market_pair_strict
    pro_model.canonical_market_option = lambda row, market_name: canonical_market_pair_strict(row, market_name)[0]
    pro_model.predict_market_triplet = predict_market_triplet_v123
    pro_model.production_evidence_gate = production_evidence_gate_v123
    selector._score = selection_score_v123
    selector.allocate = allocate_v123
    storage.update_clv = update_clv_v123
    _INSTALLED = True


def installed():
    return _INSTALLED
