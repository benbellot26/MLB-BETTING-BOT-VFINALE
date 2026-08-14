from __future__ import annotations
import math
from collections import Counter
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


def score_matrix(home_mu, away_mu, max_runs=None, dispersion=None):
    mx = int(max_runs or config.MAX_RUNS_MATRIX)
    d = config.RUN_DISPERSION if dispersion is None else dispersion
    hp = [_nb_pmf(home_mu, k, d) for k in range(mx+1)]
    ap = [_nb_pmf(away_mu, k, d) for k in range(mx+1)]
    hs, aps = sum(hp), sum(ap)
    return [x/hs for x in hp], [x/aps for x in ap]


def prob_home_win(home_mu, away_mu, dispersion=None):
    hp, ap = score_matrix(home_mu, away_mu, dispersion=dispersion)
    win = tie = 0.0
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            if h > a:
                win += ph*pa
            elif h == a:
                tie += ph*pa
    return core.clamp(win+tie*.52)


def prob_cover_parts(home_mu, away_mu, side, point, dispersion=None):
    hp, ap = score_matrix(home_mu, away_mu, dispersion=dispersion)
    win = push = 0.0
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            margin = h-a+point if side == "home" else a-h+point
            if margin > 1e-9:
                win += ph*pa
            elif abs(margin) <= 1e-9:
                push += ph*pa
    return max(0.0, min(1.0, win)), max(0.0, min(1.0, push))


def prob_total_parts(home_mu, away_mu, side, point, dispersion=None):
    hp, ap = score_matrix(home_mu, away_mu, dispersion=dispersion)
    win = push = 0.0
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            d = h+a-point
            if abs(d) <= 1e-9:
                push += ph*pa
            elif side == "over" and d > 0:
                win += ph*pa
            elif side == "under" and d < 0:
                win += ph*pa
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
        def avg(k, d):
            return sum(_n(st.get(k), d)*w for st, w in rows)/sw
        out = {
            "era": avg("era", 4.35), "whip": avg("whip", 1.32),
            "k9": avg("strikeoutsPer9Inn", 8.5), "bb9": avg("walksPer9Inn", 3.2),
            "hr9": avg("homeRunsPer9", 1.15),
        }
    _PRIOR[key] = out
    return out


def _enhance_starter(st):
    st = dict(st or {})
    prior = _pitcher_prior(st.get("id"))
    w = max(0, min(1, _n(st.get("innings"))/90))
    for dst, src, fallback in (
        ("era", "era", 4.35), ("whip", "whip", 1.32), ("k9", "k9", 8.5),
        ("bb9", "bb9", 3.2), ("hr9", "hr9", 1.15),
    ):
        cur, old = _n(st.get(dst), fallback), _n(prior.get(src), fallback)
        st[dst] = w*cur+(1-w)*old
    st["sample_weight"] = w
    st["prior_available"] = bool(prior)
    return st


def _winamax_points(event, key, home=None):
    for b in event.get("bookmakers") or []:
        if b.get("key") != core.WINAMAX_KEY:
            continue
        m = next((x for x in b.get("markets") or [] if x.get("key") == key), None)
        if not m:
            return []
        if key == "spreads":
            return sorted({
                round(_n(o.get("point")), 2) for o in m.get("outcomes") or []
                if o.get("point") is not None and core.norm_name(o.get("name")) == core.norm_name(home)
            })
        return sorted({round(_n(o.get("point")), 2) for o in m.get("outcomes") or [] if o.get("point") is not None})
    return []


def _modal(event, key, home=None):
    vals = []
    for b in event.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") != key:
                continue
            for o in m.get("outcomes") or []:
                if o.get("point") is None:
                    continue
                if key == "spreads" and core.norm_name(o.get("name")) != core.norm_name(home):
                    continue
                vals.append(round(_n(o.get("point")), 2))
    return Counter(vals).most_common(1)[0][0] if vals else (-1.5 if key == "spreads" else None)


def _project(game):
    # Keep one immutable structural baseline. V12 context enrichments feed the validated
    # residual layer instead of applying a second hand-tuned starter/bullpen overlay.
    structural_hmu, structural_amu, ctx, features = legacy._project_runs(game)
    hs = _enhance_starter(ctx.get("home_starter") or {})
    aws = _enhance_starter(ctx.get("away_starter") or {})
    bph = context.bullpen_state(ctx.get("home_id"), core.TARGET_DATE)
    bpa = context.bullpen_state(ctx.get("away_id"), core.TARGET_DATE)
    weather = context.weather_for_game(game, ctx.get("home"))
    ctx["home_starter"], ctx["away_starter"] = hs, aws

    features = dict(features or {})
    features.update({
        "weather": weather,
        "bullpen": {"home": bph, "away": bpa, "coverage": min(_n(bph.get("coverage")), _n(bpa.get("coverage")))},
        "park_factor": core.PARK.get(ctx.get("home"), 1.0),
        "structural_home_mu": structural_hmu,
        "structural_away_mu": structural_amu,
    })
    result_like = {"features": features, "ctx": ctx}
    champ = pro_model.load_model()
    home_mu, away_mu, learned = pro_model.apply_run_correction(structural_hmu, structural_amu, result_like, champ)
    dispersion, dispersion_source = pro_model.model_dispersion(champ)
    features.update({
        "home_mu": home_mu, "away_mu": away_mu,
        "learned_run_adjustment": learned,
        "run_dispersion": dispersion,
        "dispersion_source": dispersion_source,
        "distribution": "negative-binomial",
    })
    return structural_hmu, structural_amu, home_mu, away_mu, ctx, features, champ, dispersion


def _blend(p, sharp):
    if sharp.get("p") is None:
        return p, 0.0
    w = market.blend_weight(sharp)
    return core.clamp((1-w)*p+w*core.clamp(sharp["p"])), w


def analyze(game, event):
    shmu, samu, hmu, amu, ctx, features, champ, dispersion = _project(game)
    phase = core.phase_for_game(game)
    structural_home = prob_home_win(shmu, samu, config.RUN_DISPERSION)
    learned_home = prob_home_win(hmu, amu, dispersion)
    sharp_home = market.sharp_consensus(event, "ML", ctx["home"])
    options = []

    lineup_count = int(_n(ctx.get("home_lineup", {}).get("count"))+_n(ctx.get("away_lineup", {}).get("count")))
    starter_ok = bool(ctx.get("home_sp") and ctx.get("away_sp"))
    quality = max(.2, min(.95, .45+min(sharp_home.get("n", 0), 4)*.05+
                            (.10 if phase == "FINAL" else .05 if phase == "LATE" else 0)+
                            (.12 if lineup_count >= 16 else 0)+(.08 if starter_ok else 0)))

    def pair(mkt, a_name, a_point, a_struct_win, a_struct_push, a_model_win, a_model_push,
             b_name, b_point, b_struct_win, b_struct_push, b_model_win, b_model_push):
        a_non = max(1e-9, 1-a_model_push)
        b_non = max(1e-9, 1-b_model_push)
        a_ps = core.clamp(a_model_win/a_non)
        b_ps = core.clamp(b_model_win/b_non)
        total = max(1e-9, a_ps+b_ps)
        a_ps, b_ps = a_ps/total, b_ps/total

        sha = market.sharp_consensus(event, mkt, a_name, a_point)
        shb = market.sharp_consensus(event, mkt, b_name, b_point)
        a_pb, a_sw = _blend(a_ps, sha)
        b_pb, b_sw = _blend(b_ps, shb)
        total = max(1e-9, a_pb+b_pb)
        a_pb, b_pb = a_pb/total, b_pb/total
        a_pe, b_pe, unc, source = pro_model.calibrate_pair(mkt, a_pb, b_pb, champ)

        def append(name, point, s_win, s_push, m_win, m_push, pb, pe, sh, sw):
            s_non = max(1e-9, 1-s_push)
            s_cond = core.clamp(s_win/s_non)
            price = core.winamax_price(event, mkt, name, point)
            options.append({
                "market": mkt, "name": name, "point": point,
                "p_structural": round(s_cond, 6),
                "p_learned": round(core.clamp(m_win/max(1e-9, 1-m_push)), 6),
                "p_model": round(pb, 6),
                "p_effective": round(pe, 6),
                "p_win": round(pe*max(1e-9, 1-m_push), 6),
                "p_push": round(m_push, 6),
                "p_market": round(sh["p"], 6) if sh.get("p") is not None else None,
                "refs": sh.get("n", 0), "sharp_books": sh.get("books", []),
                "sharp_weight": round(sw, 6), "sharp_dispersion": sh.get("dispersion"),
                "sharp_robustness": sh.get("robustness"), "sharp_max_age_min": sh.get("max_age_min"),
                "sharp_effective_n": sh.get("effective_n"), "quality": quality,
                "confidence": round(max(0, min(10, 3+1.4*abs(pe-.5)/max(.01, unc))), 3),
                "model_uncertainty": round(unc, 6), "calibration_source": source,
                "winamax_eval": {"price": price, "official_selected": False, "official_units": 0},
            })

        append(a_name, a_point, a_struct_win, a_struct_push, a_model_win, a_model_push, a_pb, a_pe, sha, a_sw)
        append(b_name, b_point, b_struct_win, b_struct_push, b_model_win, b_model_push, b_pb, b_pe, shb, b_sw)

    pair("ML", ctx["home"], None, structural_home, 0.0, learned_home, 0.0,
         ctx["away"], None, 1-structural_home, 0.0, 1-learned_home, 0.0)

    points = _winamax_points(event, "spreads", ctx["home"]) or [_modal(event, "spreads", ctx["home"])]
    for hp in points:
        ap = -hp
        shw, shp = prob_cover_parts(shmu, samu, "home", hp, config.RUN_DISPERSION)
        saw, sap = prob_cover_parts(shmu, samu, "away", ap, config.RUN_DISPERSION)
        mhw, mhp = prob_cover_parts(hmu, amu, "home", hp, dispersion)
        maw, mapush = prob_cover_parts(hmu, amu, "away", ap, dispersion)
        pair("RUNLINE", ctx["home"], hp, shw, shp, mhw, mhp,
             ctx["away"], ap, saw, sap, maw, mapush)

    totals = _winamax_points(event, "totals") or (lambda x: [x] if x is not None else [])(_modal(event, "totals"))
    for t in totals:
        sow, sop = prob_total_parts(shmu, samu, "over", t, config.RUN_DISPERSION)
        suw, sup = prob_total_parts(shmu, samu, "under", t, config.RUN_DISPERSION)
        mow, mop = prob_total_parts(hmu, amu, "over", t, dispersion)
        muw, mup = prob_total_parts(hmu, amu, "under", t, dispersion)
        pair("TOTAL", "Over", t, sow, sop, mow, mop,
             "Under", t, suw, sup, muw, mup)

    hm = next(o for o in options if o["market"] == "ML" and core.norm_name(o["name"]) == core.norm_name(ctx["home"]))
    return {
        "game_pk": game.get("gamePk"), "game": game, "event": event, "ctx": ctx, "phase": phase,
        "structural_hmu": shmu, "structural_amu": samu, "hmu": hmu, "amu": amu,
        "p_home": hm["p_effective"], "con": sharp_home, "quality": quality, "features": features,
        "options": options,
        "model": {
            "version": champ.get("version", "structural-only"), "active": bool(champ.get("active")),
            "residual_active": bool((champ.get("residual") or {}).get("active")),
            "dispersion_active": bool((champ.get("dispersion") or {}).get("active")),
            "dispersion": dispersion,
        },
        "engine_version": config.VERSION,
    }
