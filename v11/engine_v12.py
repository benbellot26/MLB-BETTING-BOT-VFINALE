from __future__ import annotations
import math
from . import core, config, market, context, pro_model
from . import engine as legacy

_PRIOR = {}


def _n(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _nb_pmf(mu, k, dispersion):
    r = max(.5, _n(dispersion, config.RUN_DISPERSION))
    p = r/(r+max(.01, _n(mu)))
    return math.exp(math.lgamma(k+r)-math.lgamma(r)-math.lgamma(k+1)+r*math.log(p)+k*math.log1p(-p))


def _required_max_runs(mu, dispersion, minimum=None):
    minimum = int(minimum or config.MAX_RUNS_MATRIX)
    cdf = 0.0
    for k in range(config.MAX_RUNS_HARD+1):
        cdf += _nb_pmf(mu, k, dispersion)
        if k >= minimum and 1-cdf <= config.SCORE_TAIL_TOLERANCE:
            return k
    return config.MAX_RUNS_HARD


def _env_nodes(sigma):
    sigma = max(0.0, min(.30, _n(sigma, config.RUN_ENV_SIGMA)))
    if sigma <= 1e-9:
        return [(1.0, 1.0)]
    d = math.sqrt(3.0)*sigma
    return [(max(.45, 1-d), 1/6), (1.0, 2/3), (1+d, 1/6)]


def joint_score_matrix(home_mu, away_mu, max_runs=None, dispersion=None, env_sigma=None):
    d = config.RUN_DISPERSION if dispersion is None else dispersion
    env = config.RUN_ENV_SIGMA if env_sigma is None else env_sigma
    nodes = _env_nodes(env)
    max_factor = max(f for f, _ in nodes)
    mx = max(_required_max_runs(home_mu*max_factor, d, max_runs), _required_max_runs(away_mu*max_factor, d, max_runs))
    joint = [[0.0]*(mx+1) for _ in range(mx+1)]
    for factor, weight in nodes:
        hp = [_nb_pmf(home_mu*factor, k, d) for k in range(mx+1)]
        ap = [_nb_pmf(away_mu*factor, k, d) for k in range(mx+1)]
        hs, aps = sum(hp), sum(ap)
        hp = [x/max(1e-15, hs) for x in hp]
        ap = [x/max(1e-15, aps) for x in ap]
        for h, ph in enumerate(hp):
            for a, pa in enumerate(ap):
                joint[h][a] += weight*ph*pa
    total = sum(sum(row) for row in joint)
    return [[x/max(1e-15, total) for x in row] for row in joint]


def score_matrix(home_mu, away_mu, max_runs=None, dispersion=None, env_sigma=None):
    joint = joint_score_matrix(home_mu, away_mu, max_runs, dispersion, env_sigma)
    hp = [sum(row) for row in joint]
    ap = [sum(joint[h][a] for h in range(len(joint))) for a in range(len(joint))]
    return hp, ap


def prob_home_win(home_mu, away_mu, dispersion=None, env_sigma=None):
    joint = joint_score_matrix(home_mu, away_mu, dispersion=dispersion, env_sigma=env_sigma)
    win = tie = 0.0
    for h, row in enumerate(joint):
        for a, p in enumerate(row):
            if h > a:
                win += p
            elif h == a:
                tie += p
    return core.clamp(win+tie*.52)


def prob_cover_parts(home_mu, away_mu, side, point, dispersion=None, env_sigma=None):
    joint = joint_score_matrix(home_mu, away_mu, dispersion=dispersion, env_sigma=env_sigma)
    win = push = 0.0
    for h, row in enumerate(joint):
        for a, p in enumerate(row):
            margin = h-a+point if side == "home" else a-h+point
            if margin > 1e-9:
                win += p
            elif abs(margin) <= 1e-9:
                push += p
    return max(0.0, min(1.0, win)), max(0.0, min(1.0, push))


def prob_total_parts(home_mu, away_mu, side, point, dispersion=None, env_sigma=None):
    joint = joint_score_matrix(home_mu, away_mu, dispersion=dispersion, env_sigma=env_sigma)
    win = push = 0.0
    for h, row in enumerate(joint):
        for a, p in enumerate(row):
            delta = h+a-point
            if abs(delta) <= 1e-9:
                push += p
            elif side == "over" and delta > 0:
                win += p
            elif side == "under" and delta < 0:
                win += p
    return max(0.0, min(1.0, win)), max(0.0, min(1.0, push))


def _pitcher_prior(pid):
    if not pid:
        return {}
    key = (str(pid), core.SEASON)
    if key in _PRIOR:
        return _PRIOR[key]
    try:
        d = core.mlb(f"v1/people/{pid}/stats", {"stats": "yearByYear", "group": "pitching"}) or {}
        splits = (d.get("stats") or [{}])[0].get("splits") or []
    except Exception:
        splits = []
    by = {int(_n(x.get("season"))): x.get("stat") or {} for x in splits if _n(x.get("season"))}
    rows = []
    for back, weight in ((1, .65), (2, .35)):
        st = by.get(core.SEASON-back) or {}
        ip = _n(st.get("inningsPitched"))
        if ip > 0:
            rows.append((st, weight*min(1, ip/100)))
    if not rows:
        out = {}
    else:
        sw = sum(w for _, w in rows)
        def avg(k, default):
            return sum(_n(st.get(k), default)*w for st, w in rows)/sw
        out = {"era": avg("era", 4.35), "whip": avg("whip", 1.32),
               "k9": avg("strikeoutsPer9Inn", 8.5), "bb9": avg("walksPer9Inn", 3.2),
               "hr9": avg("homeRunsPer9", 1.15)}
    _PRIOR[key] = out
    return out


def _enhance_starter(st):
    st = dict(st or {})
    pid = st.get("id")
    current = core.player_stats(pid, "pitching") if pid else {}
    prior = _pitcher_prior(pid)
    ip = _n(current.get("inningsPitched"), _n(st.get("innings")))
    current_ok = bool(current and current.get("era") is not None and current.get("whip") is not None)
    prior_ok = bool(prior)
    w = max(0.0, min(1.0, ip/(ip+60.0))) if current_ok else 0.0
    defaults = {"era": 4.35, "whip": 1.32, "k9": 8.5, "bb9": 3.2, "hr9": 1.15}
    src = {"era": "era", "whip": "whip", "k9": "strikeoutsPer9Inn", "bb9": "walksPer9Inn", "hr9": "homeRunsPer9"}
    for dst, current_key in src.items():
        fallback = defaults[dst]
        cur = _n(current.get(current_key), fallback)
        old = _n(prior.get(dst), fallback)
        st[f"raw_{dst}"] = cur if current_ok else None
        st[dst] = w*cur+(1-w)*old if (current_ok or prior_ok) else fallback
    st["innings"] = ip
    st["sample_weight"] = w
    st["current_stats_available"] = current_ok
    st["prior_available"] = prior_ok
    return st


def _winamax_market(event, key):
    for b in event.get("bookmakers") or []:
        if b.get("key") == core.WINAMAX_KEY:
            return next((m for m in b.get("markets") or [] if m.get("key") == key), None)
    return None


def _winamax_points(event, key, home=None):
    m = _winamax_market(event, key)
    if not m:
        return []
    if key == "spreads":
        return sorted({round(_n(o.get("point")), 2) for o in m.get("outcomes") or []
                       if o.get("point") is not None and core.norm_name(o.get("name")) == core.norm_name(home)})
    return sorted({round(_n(o.get("point")), 2) for o in m.get("outcomes") or [] if o.get("point") is not None})


def _canonical_spread_point(event, home):
    points = _winamax_points(event, "spreads", home)
    return min(points, key=lambda p: abs(abs(p)-1.5)) if points else None


def _canonical_total_point(event):
    m = _winamax_market(event, "totals")
    if not m:
        return None
    pairs = {}
    for o in m.get("outcomes") or []:
        if o.get("point") is None or _n(o.get("price")) <= 1:
            continue
        pairs.setdefault(round(_n(o.get("point")), 2), {})[str(o.get("name") or "").lower()] = _n(o.get("price"))
    complete = [(p, d) for p, d in pairs.items() if d.get("over", 0) > 1 and d.get("under", 0) > 1]
    return min(complete, key=lambda x: abs(1/x[1]["over"]-1/x[1]["under"]))[0] if complete else None


def _project(game, phase):
    structural_hmu, structural_amu, ctx, features = legacy._project_runs(game)
    hs = _enhance_starter(ctx.get("home_starter") or {})
    aws = _enhance_starter(ctx.get("away_starter") or {})
    bph = context.bullpen_state(ctx.get("home_id"), core.TARGET_DATE)
    bpa = context.bullpen_state(ctx.get("away_id"), core.TARGET_DATE)
    weather = context.weather_for_game(game, ctx.get("home"))
    ctx["home_starter"], ctx["away_starter"] = hs, aws
    hh, ah = core.season_stats(ctx.get("home_id"), "hitting"), core.season_stats(ctx.get("away_id"), "hitting")
    hp, ap = core.season_stats(ctx.get("home_id"), "pitching"), core.season_stats(ctx.get("away_id"), "pitching")
    home_usable = sum(1 for p in (ctx.get("home_lineup") or {}).get("players") or [] if p.get("ops") is not None)
    away_usable = sum(1 for p in (ctx.get("away_lineup") or {}).get("players") or [] if p.get("ops") is not None)
    features = dict(features or {})
    features.update({"weather": weather,
                     "bullpen": {"home": bph, "away": bpa, "coverage": min(_n(bph.get("coverage")), _n(bpa.get("coverage")))},
                     "park_factor": core.PARK.get(ctx.get("home"), 1.0),
                     "structural_home_mu": structural_hmu, "structural_away_mu": structural_amu,
                     "source_quality": {"home_team_hitting": bool(hh), "away_team_hitting": bool(ah),
                                        "home_team_pitching": bool(hp), "away_team_pitching": bool(ap),
                                        "home_lineup_usable_ops": home_usable, "away_lineup_usable_ops": away_usable,
                                        "home_starter_current": bool(hs.get("current_stats_available")),
                                        "away_starter_current": bool(aws.get("current_stats_available")),
                                        "home_starter_prior": bool(hs.get("prior_available")),
                                        "away_starter_prior": bool(aws.get("prior_available"))}})
    result_like = {"features": features, "ctx": ctx, "phase": phase}
    champ = pro_model.load_model()
    home_mu, away_mu, learned = pro_model.apply_run_correction(structural_hmu, structural_amu, result_like, champ, phase)
    dispersion, dispersion_source = pro_model.model_dispersion(champ)
    env_sigma, env_source = pro_model.model_environment_sigma(champ)
    features.update({"home_mu": home_mu, "away_mu": away_mu, "learned_run_adjustment": learned,
                     "run_dispersion": dispersion, "dispersion_source": dispersion_source,
                     "run_environment_sigma": env_sigma, "run_environment_source": env_source,
                     "distribution": "correlated-negative-binomial-mixture"})
    return structural_hmu, structural_amu, home_mu, away_mu, ctx, features, champ, dispersion, env_sigma


def _blend(p, sharp):
    if sharp.get("p") is None:
        return p, 0.0
    w = market.blend_weight(sharp)
    return core.clamp((1-w)*p+w*core.clamp(sharp["p"])), w


def analyze(game, event, as_of=None):
    phase = core.phase_for_game(game, as_of)
    shmu, samu, hmu, amu, ctx, features, champ, dispersion, env_sigma = _project(game, phase)
    structural_home = prob_home_win(shmu, samu, config.RUN_DISPERSION, config.RUN_ENV_SIGMA)
    learned_home = prob_home_win(hmu, amu, dispersion, env_sigma)
    sharp_home = market.sharp_consensus(event, "ML", ctx["home"], as_of=as_of)
    options = []
    canonical_spread = _canonical_spread_point(event, ctx["home"])
    canonical_total = _canonical_total_point(event)
    lineup_count = int(_n(ctx.get("home_lineup", {}).get("count")))+int(_n(ctx.get("away_lineup", {}).get("count")))
    starter_ok = bool(ctx.get("home_sp") and ctx.get("away_sp"))
    quality = max(.2, min(.95, .45+min(sharp_home.get("n", 0), 4)*.05+
                            (.10 if phase == "FINAL" else .05 if phase == "LATE" else 0)+
                            (.12 if lineup_count >= 16 else 0)+(.08 if starter_ok else 0)))

    def pair(mkt, a_name, a_point, a_struct_win, a_struct_push, a_model_win, a_model_push,
             b_name, b_point, b_struct_win, b_struct_push, b_model_win, b_model_push, canonical=False):
        model_push = (a_model_push+b_model_push)/2
        a_ps = core.clamp(a_model_win/max(1e-9, 1-a_model_push))
        b_ps = core.clamp(b_model_win/max(1e-9, 1-b_model_push))
        total = max(1e-9, a_ps+b_ps)
        a_ps, b_ps = a_ps/total, b_ps/total
        sha = market.sharp_consensus(event, mkt, a_name, a_point, as_of=as_of)
        shb = market.sharp_consensus(event, mkt, b_name, b_point, as_of=as_of)
        a_pb, a_sw = _blend(a_ps, sha)
        b_pb, b_sw = _blend(b_ps, shb)
        total = max(1e-9, a_pb+b_pb)
        a_pb, b_pb = a_pb/total, b_pb/total
        a_pe, b_pe, calibrated_push, source = pro_model.calibrate_triplet(mkt, a_pb, b_pb, model_push, champ, phase)

        def append(name, point, s_win, s_push, m_win, m_push, pb, pe, sh, sw):
            s_cond = core.clamp(s_win/max(1e-9, 1-s_push))
            price = core.winamax_price(event, mkt, name, point)
            base_unc = pro_model.model_uncertainty(mkt, pe, phase, sh.get("dispersion"), 1.0, champ)
            options.append({"market": mkt, "name": name, "point": point, "is_canonical_line": bool(canonical),
                            "p_structural": round(s_cond, 6),
                            "p_learned": round(core.clamp(m_win/max(1e-9, 1-m_push)), 6),
                            "p_model": round(pb, 6), "p_effective": round(pe, 6),
                            "p_win": round(pe*max(1e-9, 1-calibrated_push), 6),
                            "p_push": round(calibrated_push, 6), "p_push_model": round(model_push, 6),
                            "p_market": round(sh["p"], 6) if sh.get("p") is not None else None,
                            "refs": sh.get("n", 0), "sharp_books": sh.get("books", []), "sharp_weight": round(sw, 6),
                            "sharp_dispersion": sh.get("dispersion"), "sharp_robustness": sh.get("robustness"),
                            "sharp_max_age_min": sh.get("max_age_min"), "sharp_effective_n": sh.get("effective_n"),
                            "quality": quality, "model_uncertainty": round(base_unc, 6),
                            "calibration_source": source, "phase_model": phase,
                            "winamax_eval": {"price": price, "official_selected": False, "official_units": 0}})

        append(a_name, a_point, a_struct_win, a_struct_push, a_model_win, a_model_push, a_pb, a_pe, sha, a_sw)
        append(b_name, b_point, b_struct_win, b_struct_push, b_model_win, b_model_push, b_pb, b_pe, shb, b_sw)

    pair("ML", ctx["home"], None, structural_home, 0.0, learned_home, 0.0,
         ctx["away"], None, 1-structural_home, 0.0, 1-learned_home, 0.0, canonical=True)
    for hp in _winamax_points(event, "spreads", ctx["home"]):
        ap = -hp
        shw, shp = prob_cover_parts(shmu, samu, "home", hp, config.RUN_DISPERSION, config.RUN_ENV_SIGMA)
        saw, sap = prob_cover_parts(shmu, samu, "away", ap, config.RUN_DISPERSION, config.RUN_ENV_SIGMA)
        mhw, mhp = prob_cover_parts(hmu, amu, "home", hp, dispersion, env_sigma)
        maw, mapush = prob_cover_parts(hmu, amu, "away", ap, dispersion, env_sigma)
        pair("RUNLINE", ctx["home"], hp, shw, shp, mhw, mhp, ctx["away"], ap, saw, sap, maw, mapush,
             canonical=canonical_spread is not None and abs(hp-canonical_spread) <= 1e-6)
    for t in _winamax_points(event, "totals"):
        sow, sop = prob_total_parts(shmu, samu, "over", t, config.RUN_DISPERSION, config.RUN_ENV_SIGMA)
        suw, sup = prob_total_parts(shmu, samu, "under", t, config.RUN_DISPERSION, config.RUN_ENV_SIGMA)
        mow, mop = prob_total_parts(hmu, amu, "over", t, dispersion, env_sigma)
        muw, mup = prob_total_parts(hmu, amu, "under", t, dispersion, env_sigma)
        pair("TOTAL", "Over", t, sow, sop, mow, mop, "Under", t, suw, sup, muw, mup,
             canonical=canonical_total is not None and abs(t-canonical_total) <= 1e-6)
    hm = next(o for o in options if o["market"] == "ML" and core.norm_name(o["name"]) == core.norm_name(ctx["home"]))
    return {"game_pk": game.get("gamePk"), "game": game, "event": event, "ctx": ctx, "phase": phase,
            "as_of": as_of, "structural_hmu": shmu, "structural_amu": samu, "hmu": hmu, "amu": amu,
            "p_home": hm["p_effective"], "con": sharp_home, "quality": quality, "features": features,
            "canonical_lines": {"RUNLINE": canonical_spread, "TOTAL": canonical_total}, "options": options,
            "model": {"version": champ.get("version", "structural-only"), "active": bool(champ.get("active")),
                      "artifact_status": champ.get("artifact_status"), "artifact_error": champ.get("artifact_error"),
                      "phase": phase, "dispersion": dispersion, "environment_sigma": env_sigma},
            "engine_version": config.VERSION}
