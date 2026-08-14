from __future__ import annotations
import json
import math
from .config import MODEL_FILE, MODEL_VERSION, VERSION

DEFAULT_MODEL = {
    "version": MODEL_VERSION,
    "trained_through": "2026-08-12",
    "window_games": 400,
    "l2": 3.333,
    "decision_threshold": 0.5,
    "features": ["lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff", "lineup_x_uncertainty", "lineup_available"],
    "means": {"lineup_relative": -0.00223125, "regular_overlap": -0.015703125, "lineup_abs": -0.017934375, "lineup_cov_diff": 0.0, "lineup_x_uncertainty": -0.0028245662561229784, "lineup_available": 1.0},
    "stds": {"lineup_relative": 0.31243396496049763, "regular_overlap": 0.34877941429216314, "lineup_abs": 0.447148145095235, "lineup_cov_diff": 1.0, "lineup_x_uncertainty": 0.2717101855670158, "lineup_available": 1.0},
    "beta": [0.08480752116865005, -0.1289723019635723, -0.023497525218618854, -0.1084445530804969, 0.0, 0.35530824359040025, 0.0],
    "v11_2_params": {"intercept": 0.045, "relative_lineup_coef": 0.05, "regular_overlap_coef": -0.25},
    "validation": {"method": "rolling recent-400; Eastern-day frozen", "holdout_n": 451, "wins": 271, "accuracy": 271 / 451, "note": "historical rolling evidence; live confirmation required"},
    "challengers": {
        "RUNLINE": {"active": False, "intercept": 0.0, "run_diff_coef": 0.0},
        "TOTAL": {"active": False, "intercept": 0.0, "total_residual_coef": 0.0},
    },
}

def clamp(x, lo=.001, hi=.999):
    try: return max(lo, min(hi, float(x)))
    except Exception: return .5

def logit(p):
    p = clamp(p); return math.log(p / (1 - p))

def sigmoid(z):
    z = max(-30.0, min(30.0, float(z))); return 1 / (1 + math.exp(-z))

def load_model():
    if MODEL_FILE.exists():
        try:
            m = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
            if m.get("version") == MODEL_VERSION:
                merged = dict(DEFAULT_MODEL); merged.update(m); return merged
        except Exception: pass
    return dict(DEFAULT_MODEL)

def v11_2_probability(base_p_home, features, model):
    p = model.get("v11_2_params") or DEFAULT_MODEL["v11_2_params"]
    z = logit(base_p_home)
    z += float(p.get("intercept", 0) or 0)
    z += float(p.get("relative_lineup_coef", 0) or 0) * float(features.get("lineup_relative", 0) or 0)
    z += float(p.get("regular_overlap_coef", 0) or 0) * float(features.get("regular_overlap", 0) or 0)
    return clamp(sigmoid(z))

def v11_3_direction_probability(base_p_home, features, model):
    beta = model.get("beta") or []; z = logit(base_p_home) + float(beta[0] if beta else 0)
    for i, name in enumerate(model.get("features") or [], 1):
        if i >= len(beta): break
        sd = max(1e-9, abs(float((model.get("stds") or {}).get(name, 1) or 1)))
        mean = float((model.get("means") or {}).get(name, 0) or 0); value = float(features.get(name, 0) or 0)
        z += float(beta[i] or 0) * ((value - mean) / sd)
    return clamp(sigmoid(z))

def apply_ml_heads(result, features, model):
    ctx = result["ctx"]; base = clamp(result.get("p_model", .5)); p112 = v11_2_probability(base, features, model); p113 = v11_3_direction_probability(base, features, model)
    home_pick = p113 >= float(model.get("decision_threshold", .5) or .5); pick = ctx["home"] if home_pick else ctx["away"]
    p112_pick = p112 if home_pick else 1-p112; p113_pick = p113 if home_pick else 1-p113; v10_pick = ctx["home"] if base >= .5 else ctx["away"]
    p112_side = ctx["home"] if p112 >= .5 else ctx["away"]; agreement = pick == p112_side
    grade = "FORT" if agreement and p112_pick >= .58 and features.get("lineup_both_available") else "BON" if agreement and p112_pick >= .55 else "PRUDENCE" if agreement and p112_pick >= .52 else "FAIBLE"
    rank_score = 100 * (.55 * abs(p113-.5)*2 + .30 * abs(p112-.5)*2 + .10 * max(0.0,min(1.0,float(result.get("quality",0) or 0))) + .05 * (1.0 if agreement else 0.0))
    if not features.get("lineup_both_available"): rank_score -= 5
    out = {"model_version": VERSION, "direction_model_version": model.get("version"), "trained_through": model.get("trained_through"), "game_pk": result.get("game_pk"), "game_date": (result.get("game") or {}).get("gameDate"), "home": ctx["home"], "away": ctx["away"], "phase": result.get("phase"), "base_v10_p_home": round(base,6), "base_v10_pick": v10_pick, "base_v10_probability_for_pick": round(base if v10_pick == ctx["home"] else 1-base,6), "v11_2_p_home": round(p112,6), "v11_3_direction_p_home": round(p113,6), "v11_3_pick": pick, "v11_3_direction_score": round(p113_pick,6), "v11_2_probability_for_pick": round(p112_pick,6), "heads_agree": agreement, "v10_v11_same_pick": v10_pick == pick, "grade": grade, "rank_score": round(max(0.0,min(100.0,rank_score)),2), "quality": round(float(result.get("quality",0) or 0),4), "features": features, "official_effect": True, "result_status": "PENDING"}
    result["v11_3"] = out; result["p_model"] = p112 if agreement else (.5001 if home_pick else .4999); return out

def patch_ml_options(core, result):
    x = result["v11_3"]; pick = str(x["v11_3_pick"]); p_pick = clamp(x["v11_2_probability_for_pick"]) if x["heads_agree"] else .5001; options = core.v1011_iter_options(result)
    for rec in options:
        if str(rec.get("market") or "").upper() != "ML": continue
        rec["p_model"] = p_pick if str(rec.get("name") or "") == pick else 1-p_pick; core.v1011_apply_effective(rec, result)
    ml = (result.get("model_recs") or {}).get("ML")
    if ml and str(ml.get("name") or "") != pick:
        replacement = next((r for r in options if r.get("market") == "ML" and str(r.get("name")) == pick), None)
        if replacement is not None: result["model_recs"]["ML"] = replacement

def attach_market_challengers(core, result, feature_snapshot, model):
    challengers = model.get("challengers") or {}; out = {}
    for rec in core.v1011_iter_options(result):
        market = str(rec.get("market") or "").upper()
        if market not in {"RUNLINE", "TOTAL"}: continue
        base = clamp(rec.get("p_effective", rec.get("p_model", .5))); cfg = challengers.get(market) or {}
        if market == "RUNLINE": residual = float(feature_snapshot.get("projected_run_diff_home",0) or 0); z = logit(base)+float(cfg.get("intercept",0) or 0)+float(cfg.get("run_diff_coef",0) or 0)*residual
        else: residual = float(feature_snapshot.get("projected_total_residual",0) or 0); z = logit(base)+float(cfg.get("intercept",0) or 0)+float(cfg.get("total_residual_coef",0) or 0)*residual
        p = clamp(sigmoid(z)); key = f"{market}:{rec.get('name')}:{rec.get('point')}"; active = bool(cfg.get("active",False))
        out[key] = {"market":market,"pick":rec.get("name"),"point":rec.get("point"),"base_v10_probability":round(base,6),"challenger_probability":round(p,6),"official_effect":active,"status":"ACTIVE" if active else "SHADOW_UNVALIDATED"}
        if active: rec["p_model"] = p; core.v1011_apply_effective(rec,result)
    result["v11_market_challengers"] = out; return out
