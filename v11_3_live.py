#!/usr/bin/env python3
"""V11.3 live winner head for MLB.

Production intent (ML only):
- V10.0.15 remains the live baseball/base-probability engine.
- V11.2 remains the calibrated probability head (fair probability / EV context).
- V11.3 is a directional head trained on the most recent 400 historical games,
  with a same-Eastern-day-freeze rolling validation of 271/451 (60.09%).

Run Line and Total are inherited from the frozen V10.0.15 engine; V11.3 does not
pretend to have validated directional improvements on those markets.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import bot as core

VERSION = "11.3-live-direction-v1"
MODEL_FILE = Path(os.getenv("V11_3_MODEL_FILE", "data/v11_3_direction_model.json"))
LIVE_FILE = Path(os.getenv("V11_3_LIVE_FILE", "data/v11_3_live.jsonl"))
REPORT_FILE = Path(os.getenv("V11_3_LIVE_REPORT", "data/v11_3_live_report.json"))

DEFAULT_MODEL = {
    "version": "11.3-directional-recent400-v1",
    "trained_through": "2026-08-12",
    "window_games": 400,
    "l2": 3.333,
    "decision_threshold": 0.5,
    "features": [
        "lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff",
        "lineup_x_uncertainty", "lineup_available",
    ],
    "means": {
        "lineup_relative": -0.00223125,
        "regular_overlap": -0.015703125,
        "lineup_abs": -0.017934375,
        "lineup_cov_diff": 0.0,
        "lineup_x_uncertainty": -0.0028245662561229784,
        "lineup_available": 1.0,
    },
    "stds": {
        "lineup_relative": 0.31243396496049763,
        "regular_overlap": 0.34877941429216314,
        "lineup_abs": 0.447148145095235,
        "lineup_cov_diff": 1.0,
        "lineup_x_uncertainty": 0.2717101855670158,
        "lineup_available": 1.0,
    },
    "beta": [
        0.08480752116865005,
        -0.1289723019635723,
        -0.023497525218618854,
        -0.1084445530804969,
        0.0,
        0.35530824359040025,
        0.0,
    ],
    "v11_2_params": {
        "intercept": 0.045,
        "relative_lineup_coef": 0.05,
        "regular_overlap_coef": -0.25,
    },
    "validation": {
        "method": "rolling recent-400; predict all games on an Eastern date before adding that date",
        "holdout_n": 451,
        "wins": 271,
        "accuracy": 0.6008869179600886,
        "note": "historical validation only; live confirmation still required",
    },
}


def clamp(x, lo=.001, hi=.999):
    return max(lo, min(hi, float(x)))


def logit(p):
    p = clamp(p)
    return math.log(p / (1.0 - p))


def sigmoid(z):
    z = max(-30.0, min(30.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def load_model():
    if MODEL_FILE.exists():
        try:
            model = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
            if model.get("version") == DEFAULT_MODEL["version"]:
                return model
        except Exception:
            pass
    return dict(DEFAULT_MODEL)


def _lineup_ops(ctx, side, regular_ops):
    lu = ctx.get(f"{side}_lineup") or {}
    value = lu.get("weighted_ops")
    count = int(core.num(lu.get("count"), 0))
    if value is None or core.num(value, 0) <= .2 or count < 5:
        return float(regular_ops), False, count
    return float(value), True, count


def live_features(result):
    ctx = result.get("ctx") or {}
    lg_ops = core.num(core.league_baselines().get("ops"), .710)
    hhit = core.season_stats(ctx.get("home_id"), "hitting") or {}
    ahit = core.season_stats(ctx.get("away_id"), "hitting") or {}
    hreg = core.num(hhit.get("ops"), lg_ops)
    areg = core.num(ahit.get("ops"), lg_ops)
    hlu, hok, hc = _lineup_ops(ctx, "home", hreg)
    alu, aok, ac = _lineup_ops(ctx, "away", areg)
    lineup_ok = bool(hok and aok)

    if lineup_ok:
        relative = ((hlu-hreg) - (alu-areg)) / .08
        regular_overlap = (hreg-areg) / .08
        lineup_abs = (hlu-alu) / .08
    else:
        relative = regular_overlap = lineup_abs = 0.0

    base = clamp(result.get("p_model", .5))
    strength = min(abs(logit(base)), 2.5) / 2.5
    return {
        "lineup_relative": relative,
        "regular_overlap": regular_overlap,
        "lineup_abs": lineup_abs,
        "lineup_cov_diff": 0.0,
        "lineup_x_uncertainty": relative * (1.0-strength),
        "lineup_available": 1.0 if lineup_ok else 0.0,
        "home_lineup_ops": hlu,
        "away_lineup_ops": alu,
        "home_regular_ops": hreg,
        "away_regular_ops": areg,
        "home_lineup_count": hc,
        "away_lineup_count": ac,
        "lineup_both_available": lineup_ok,
    }


def v11_2_probability(base_p_home, features, model):
    p = model.get("v11_2_params") or DEFAULT_MODEL["v11_2_params"]
    z = logit(base_p_home)
    z += core.num(p.get("intercept"), 0)
    z += core.num(p.get("relative_lineup_coef"), 0) * features["lineup_relative"]
    z += core.num(p.get("regular_overlap_coef"), 0) * features["regular_overlap"]
    return clamp(sigmoid(z))


def v11_3_direction_probability(base_p_home, features, model):
    names = model["features"]
    means = model["means"]
    stds = model["stds"]
    beta = model["beta"]
    z = logit(base_p_home) + core.num(beta[0], 0)
    for i, name in enumerate(names, 1):
        sd = max(1e-9, abs(core.num(stds.get(name), 1)))
        z += core.num(beta[i], 0) * ((core.num(features.get(name), 0)-core.num(means.get(name), 0))/sd)
    return clamp(sigmoid(z))


def apply_heads(result, model):
    ctx = result["ctx"]
    base = clamp(result.get("p_model", .5))
    f = live_features(result)
    p112 = v11_2_probability(base, f, model)
    p113 = v11_3_direction_probability(base, f, model)
    threshold = core.num(model.get("decision_threshold"), .5)
    home_pick = p113 >= threshold
    pick = ctx["home"] if home_pick else ctx["away"]
    p112_pick = p112 if home_pick else 1-p112
    p113_pick = p113 if home_pick else 1-p113
    p112_side = ctx["home"] if p112 >= .5 else ctx["away"]
    agreement = pick == p112_side

    rank_score = 100 * (
        .55 * abs(p113-.5)*2
        + .30 * abs(p112-.5)*2
        + .10 * core.clamp(core.num(result.get("quality"), 0), 0, 1)
        + .05 * (1.0 if agreement else 0.0)
    )
    if not f["lineup_both_available"]:
        rank_score -= 5
    rank_score = max(0.0, min(100.0, rank_score))

    if agreement and p112_pick >= .58 and f["lineup_both_available"]:
        grade = "FORT"
    elif agreement and p112_pick >= .55:
        grade = "BON"
    elif agreement and p112_pick >= .52:
        grade = "PRUDENCE"
    else:
        grade = "FAIBLE"

    out = {
        "model_version": VERSION,
        "direction_model_version": model.get("version"),
        "trained_through": model.get("trained_through"),
        "game_pk": result.get("game_pk"),
        "game_date": (result.get("game") or {}).get("gameDate"),
        "target_date": core.TARGET_DATE,
        "home": ctx["home"],
        "away": ctx["away"],
        "phase": result.get("phase"),
        "base_v10_p_home": round(base, 6),
        "v11_2_p_home": round(p112, 6),
        "v11_3_direction_p_home": round(p113, 6),
        "v11_3_pick": pick,
        "v11_3_direction_score": round(p113_pick, 6),
        "v11_2_probability_for_pick": round(p112_pick, 6),
        "heads_agree": agreement,
        "grade": grade,
        "rank_score": round(rank_score, 2),
        "quality": round(core.num(result.get("quality"), 0), 4),
        "lineup_both_available": f["lineup_both_available"],
        "home_lineup_count": f["home_lineup_count"],
        "away_lineup_count": f["away_lineup_count"],
        "features": {k: round(core.num(v), 6) if isinstance(v, (int,float)) else v for k,v in f.items()},
        "starter_home": ctx.get("home_sp"),
        "starter_away": ctx.get("away_sp"),
        "runline_inherited_from": "V10.0.15",
        "total_inherited_from": "V10.0.15",
        "official_effect": True,
        "result_status": "PENDING",
        "result": None,
    }
    result["v11_3"] = out
    return out


def _market_label(rec):
    if not rec:
        return "—"
    market = rec.get("market")
    if market == "RUNLINE":
        return f"{rec.get('name')} {core.num(rec.get('point')):+g}"
    if market == "TOTAL":
        return f"{rec.get('name')} {core.num(rec.get('point')):g}"
    return str(rec.get("name") or "—")


def _best_inherited(result, market):
    candidates=[]
    try:
        for rec in core.v1011_iter_options(result):
            if rec and rec.get("market") == market:
                candidates.append(rec)
    except Exception:
        rec=(result.get("model_recs") or {}).get(market)
        if rec:
            candidates=[rec]
    if not candidates:
        return None
    return max(candidates, key=lambda r:(core.num(r.get("p_effective",r.get("p_model")),.5), core.num(r.get("confidence"),0)))


def send_embed(title, fields, color=5763719):
    if not core.DISCORD_URL:
        return False
    fs=[{"name":n[:256],"value":v[:1024],"inline":False} for n,v in fields if v]
    payload={
        "username":"MLB Betting Bot V11.3",
        "allowed_mentions":{"parse":[]},
        "embeds":[{
            "title":title[:256],"color":color,"fields":fs,
            "footer":{"text":"MLB V11.3 • winner head V11.3 + probability head V11.2 • aucune garantie de gain"},
        }],
    }
    status,_=core.discord_request("POST", payload)
    return status in (200,204)


def send_game(result):
    x=result["v11_3"];ctx=result["ctx"]
    agree="✅ CONVERGENCE" if x["heads_agree"] else "⚠️ DÉSACCORD"
    lineup="✅ lineups utilisables" if x["lineup_both_available"] else "🟠 lineup partielle / indisponible"
    main=(
        f"**PRONOSTIC V11.3 : {x['v11_3_pick']}**\n"
        f"Tête directionnelle : **{100*x['v11_3_direction_score']:.1f}%** *(score de classification, pas une proba de pari)*\n"
        f"Tête probabilité V11.2 sur ce côté : **{100*x['v11_2_probability_for_pick']:.1f}%**\n"
        f"{agree} • grade **{x['grade']}** • ranking **{x['rank_score']:.0f}/100**"
    )
    data=(
        f"Phase **{x['phase']}** • qualité données **{10*x['quality']:.1f}/10** • {lineup}\n"
        f"Lineups H/A : **{x['home_lineup_count']}/9 – {x['away_lineup_count']}/9**\n"
        f"Starters : **{ctx.get('away_sp','—')} / {ctx.get('home_sp','—')}**\n"
        f"V10 base domicile {100*x['base_v10_p_home']:.1f}% → V11.2 {100*x['v11_2_p_home']:.1f}%"
    )
    rl=_best_inherited(result,"RUNLINE");tot=_best_inherited(result,"TOTAL")
    inherited=(
        f"RL : **{_market_label(rl)}** • chance prudente {100*core.num((rl or {}).get('p_effective',(rl or {}).get('p_model',.5)),.5):.1f}%\n"
        f"Total : **{_market_label(tot)}** • chance prudente {100*core.num((tot or {}).get('p_effective',(tot or {}).get('p_model',.5)),.5):.1f}%\n"
        f"*RL/Total restent issus de V10.0.15 ; la V11.3 est validée ici uniquement pour le vainqueur ML.*"
    )
    return send_embed(f"⚾ V11.3 • {ctx['away']} @ {ctx['home']}",[("🏆 Vainqueur",main),("🧪 Données",data),("⚾ Marchés secondaires",inherited)])


def send_top(results):
    ranked=sorted((r for r in results if r.get("v11_3")), key=lambda r:r["v11_3"]["rank_score"], reverse=True)
    blocks=[]
    for i,r in enumerate(ranked[:5],1):
        x=r["v11_3"]
        flag="✅" if x["heads_agree"] else "⚠️"
        blocks.append(
            f"**#{i} {x['v11_3_pick']}** — {x['away']} @ {x['home']}\n"
            f"{flag} {x['grade']} • V11.2 **{100*x['v11_2_probability_for_pick']:.1f}%** • direction **{100*x['v11_3_direction_score']:.1f}%** • rank {x['rank_score']:.0f}/100"
        )
    text="\n\n".join(blocks) if blocks else "Aucun match restant à analyser."
    return send_embed("🏆 V11.3 — PRONOSTICS VAINQUEUR À UTILISER",[("Classement de ce run",text),("Règle","Priorité aux lignes avec **convergence V11.3/V11.2** et lineup disponible. Un désaccord entre les deux têtes est un signal de prudence, pas un pari à forcer.")],16766720)


def write_rows(new_rows):
    old=[]
    if LIVE_FILE.exists():
        for line in LIVE_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try: old.append(json.loads(line))
            except Exception: pass
    old.extend(new_rows)
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIVE_FILE.write_text("\n".join(json.dumps(r,ensure_ascii=False,separators=(",",":")) for r in old)+("\n" if old else ""), encoding="utf-8")


def self_test():
    model=load_model()
    f={"lineup_relative":.5,"regular_overlap":.2,"lineup_abs":.7,"lineup_cov_diff":0.0,"lineup_x_uncertainty":.4,"lineup_available":1.0}
    p112=v11_2_probability(.55,f,model);p113=v11_3_direction_probability(.55,f,model)
    assert 0<p112<1 and 0<p113<1
    assert model["validation"]["wins"]==271 and model["validation"]["holdout_n"]==451
    print("SELF-TEST V11.3 LIVE OK")


def main():
    model=load_model()
    if not core.ODDS_KEY:
        raise SystemExit("ODDS_API_KEY absente")
    discord_ok=core.discord_test()
    hist=core.load_history()
    core.settle_history(hist)
    run_state=core.run_model_state(hist)
    disp_state=core.dispersion_state(hist)
    engine="learned-runs" if run_state.get("active") else "base-runs"
    cal_state=core.calibration_state(hist,engine)
    skill=core.skill_state(hist,engine)
    states=(run_state,disp_state,cal_state,skill)
    core.savant_league()
    games=core.mlb_schedule(core.TARGET_DATE)
    events=core.odds_api()
    matches=core.match_odds_events(games,events)
    results=[]
    now=core.NOW
    for g in games:
        if core.parse_dt(g["gameDate"]) <= now:
            continue
        pair=matches.get(str(g["gamePk"]))
        if not pair:
            continue
        try:
            r=core.analyze_base(g,pair[0],pair[1],states,hist)
            r["disp_state"]=disp_state
            core.attach_model_recommendations(r)
            apply_heads(r,model)
            results.append(r)
        except Exception:
            core.logging.exception("V11.3 analyse impossible pour gamePk=%s",g.get("gamePk"))

    analyzed_at=datetime.now(timezone.utc).isoformat()
    run_id=hashlib.sha1(f"{analyzed_at}|{core.TARGET_DATE}|{VERSION}".encode()).hexdigest()[:16]
    rows=[]
    for r in results:
        row=dict(r["v11_3"])
        row.update({"run_id":run_id,"analyzed_at":analyzed_at})
        rows.append(row)
    write_rows(rows)

    if discord_ok:
        for r in results:
            send_game(r)
        send_top(results)

    ranked=sorted(rows,key=lambda r:r["rank_score"],reverse=True)
    report={
        "version":VERSION,"run_id":run_id,"analyzed_at":analyzed_at,"target_date":core.TARGET_DATE,
        "model":model,"remaining_games_analyzed":len(rows),
        "top_picks":[{k:r.get(k) for k in ("game_pk","away","home","v11_3_pick","v11_3_direction_score","v11_2_probability_for_pick","heads_agree","grade","rank_score","phase")} for r in ranked[:5]],
        "methodology":{
            "winner_direction":"V11.3 recent-400 residual head",
            "probability_head":"V11.2 lineup-calibrated head",
            "runline_total":"V10.0.15 inherited",
            "tonight_model_trained_through":"2026-08-12",
            "important_note":"The 60.09% evidence comes from rolling day-frozen evaluation. Live confirmation remains required.",
        },
    }
    REPORT_FILE.parent.mkdir(parents=True,exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    core.logging.info("V11.3 LIVE terminé | matchs restants=%d | top=%s",len(rows),", ".join(r["v11_3_pick"] for r in ranked[:3]) or "-")


if __name__=="__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
