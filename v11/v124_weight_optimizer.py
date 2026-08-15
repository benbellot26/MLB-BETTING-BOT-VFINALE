from __future__ import annotations

import math
import os
import random

VERSION = "v12.4-weight-optimizer-v1"
SCHEMA = "v12-4-weight-optimizer-v1"
MODULES = ("platoon", "statcast", "bullpen_player", "lineup_player", "starter_ip", "weather_park")
MIN_GAMES = int(os.getenv("V124_OPTIMIZER_MIN_GAMES", "75") or 75)
WALK_FORWARD_READY_GAMES = int(os.getenv("V124_OPTIMIZER_WF_READY_GAMES", "150") or 150)
MATURE_GAMES = int(os.getenv("V124_OPTIMIZER_MATURE_GAMES", "250") or 250)
WF_TEST_GAMES = int(os.getenv("V124_OPTIMIZER_WF_TEST_GAMES", "25") or 25)
MAX_WEIGHT = float(os.getenv("V124_OPTIMIZER_MAX_WEIGHT", "1.25") or 1.25)
REGULARIZATION = float(os.getenv("V124_OPTIMIZER_L2", "0.0025") or .0025)
_BOOTSTRAPS = int(os.getenv("V124_OPTIMIZER_BOOTSTRAPS", "400") or 400)
_MODEL_CACHE = None
_INSTALLED = False


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _clip(p):
    return max(.001, min(.999, _num(p, .5)))


def _logit(p):
    p = _clip(p)
    return math.log(p/(1-p))


def _sigmoid(z):
    return 1.0/(1.0+math.exp(-max(-30.0, min(30.0, z))))


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _key(opt):
    point = opt.get("point")
    return (str(opt.get("market") or "").upper(), _norm(opt.get("name")), None if point is None else round(_num(point), 4))


def _coverage(module):
    status = str((module or {}).get("status") or "").upper()
    if status in {"DISABLED", "UNAVAILABLE", "ERROR", "NO_CUTOFF", "ROOF_NEUTRAL", "ROOF_UNKNOWN_NEUTRAL"}:
        return 0.0
    return max(0.0, min(1.0, _num((module or {}).get("coverage"), 0.0)))


def _example(row):
    shadow = row.get("shadow_v124") or {}
    if not shadow.get("enabled") or shadow.get("status") == "ERROR":
        return None
    variants = shadow.get("variants") or {}
    base = variants.get("baseline_v1232") or {}
    base_h = _num(base.get("home_mu"), _num(shadow.get("base_home_mu"), 0.0))
    base_a = _num(base.get("away_mu"), _num(shadow.get("base_away_mu"), 0.0))
    if base_h <= 0 or base_a <= 0:
        return None
    hs, aws = row.get("home_score"), row.get("away_score")
    if hs is None or aws is None:
        return None
    hs, aws = _num(hs, None), _num(aws, None)
    if hs is None or aws is None:
        return None

    result_map = {_key(o): o.get("result") for o in row.get("options") or [] if o.get("result") in {"WIN", "LOSS"}}
    base_options = {_key(o): o for o in base.get("options") or []}
    if not result_map or not base_options:
        return None

    module_maps = {}
    effects = {}
    modules = shadow.get("modules") or {}
    for name in MODULES:
        payload = variants.get(f"only_{name}") or {}
        cov = _coverage(modules.get(name) or {})
        hf = _num(payload.get("home_factor"), 0.0)
        af = _num(payload.get("away_factor"), 0.0)
        if hf <= 0:
            vh = _num(payload.get("home_mu"), base_h)
            hf = vh/base_h if base_h > 0 else 1.0
        if af <= 0:
            va = _num(payload.get("away_mu"), base_a)
            af = va/base_a if base_a > 0 else 1.0
        effects[name] = {
            "coverage": cov,
            "home_log_factor": math.log(max(.80, min(1.20, hf))),
            "away_log_factor": math.log(max(.80, min(1.20, af))),
        }
        module_maps[name] = {_key(o): o for o in payload.get("options") or []}

    options = []
    for k, outcome in result_map.items():
        b = base_options.get(k)
        if not b:
            continue
        p0 = _clip(b.get("p_effective"))
        deltas = {}
        for name in MODULES:
            other = module_maps[name].get(k)
            pm = _clip(other.get("p_effective")) if other else p0
            deltas[name] = _logit(pm)-_logit(p0)
        options.append({
            "market": k[0], "key": k, "y": 1.0 if outcome == "WIN" else 0.0,
            "p0": p0, "deltas": deltas,
        })
    if not options:
        return None
    return {
        "sort_key": str(row.get("game_date") or row.get("analyzed_at") or row.get("game_pk") or ""),
        "game_pk": row.get("game_pk"), "base_h": base_h, "base_a": base_a,
        "home_score": hs, "away_score": aws, "effects": effects, "options": options,
    }


def examples(rows):
    out = [x for x in (_example(r) for r in rows or []) if x]
    out.sort(key=lambda x: x["sort_key"])
    return out


def _weighted_runs(ex, weights):
    hlog = alog = 0.0
    for name in MODULES:
        e = ex["effects"].get(name) or {}
        w = max(0.0, min(MAX_WEIGHT, _num(weights.get(name), 0.0)))
        c = max(0.0, min(1.0, _num(e.get("coverage"), 0.0)))
        hlog += w*c*_num(e.get("home_log_factor"), 0.0)
        alog += w*c*_num(e.get("away_log_factor"), 0.0)
    hf = max(.88, min(1.12, math.exp(hlog)))
    af = max(.88, min(1.12, math.exp(alog)))
    return max(1.6, min(8.0, ex["base_h"]*hf)), max(1.6, min(8.0, ex["base_a"]*af)), hf, af


def _option_probability(ex, opt, weights):
    z = _logit(opt["p0"])
    for name in MODULES:
        effect = ex["effects"].get(name) or {}
        c = max(0.0, min(1.0, _num(effect.get("coverage"), 0.0)))
        w = max(0.0, min(MAX_WEIGHT, _num(weights.get(name), 0.0)))
        z += w*c*_num(opt["deltas"].get(name), 0.0)
    return _clip(_sigmoid(z))


def evaluate(exs, weights):
    if not exs:
        return {"games": 0, "options": 0}
    brier = logloss = 0.0
    option_n = 0
    market_acc = {}
    team_abs = total_abs = 0.0
    gt55_n = gt55_w = 0
    for ex in exs:
        h, a, _, _ = _weighted_runs(ex, weights)
        team_abs += abs(h-ex["home_score"])+abs(a-ex["away_score"])
        total_abs += abs((h+a)-(ex["home_score"]+ex["away_score"]))
        for opt in ex["options"]:
            p = _option_probability(ex, opt, weights)
            y = opt["y"]
            brier += (p-y)**2
            logloss += -(y*math.log(p)+(1-y)*math.log(1-p))
            option_n += 1
            m = market_acc.setdefault(opt["market"], {"n": 0, "brier": 0.0, "logloss": 0.0})
            m["n"] += 1
            m["brier"] += (p-y)**2
            m["logloss"] += -(y*math.log(p)+(1-y)*math.log(1-p))
            if p > .55:
                gt55_n += 1
                gt55_w += int(y == 1.0)
    by_market = {}
    for name, m in market_acc.items():
        by_market[name] = {
            "n": m["n"], "brier": m["brier"]/m["n"], "logloss": m["logloss"]/m["n"],
        }
    n = len(exs)
    return {
        "games": n, "options": option_n,
        "brier": brier/max(1, option_n), "logloss": logloss/max(1, option_n),
        "team_run_mae": team_abs/(2*n), "total_run_mae": total_abs/n,
        "gt55_n": gt55_n, "gt55_hit_rate": gt55_w/gt55_n if gt55_n else None,
        "by_market": by_market,
    }


def _objective(exs, weights, regularize=True):
    m = evaluate(exs, weights)
    if not m.get("games"):
        return 999.0
    # Proper probability scoring dominates. Run MAE is deliberately secondary.
    value = .50*m["logloss"] + .35*m["brier"] + .15*min(1.5, m["team_run_mae"]/5.0)
    if regularize:
        value += REGULARIZATION*sum(_num(weights.get(n), 0.0)**2 for n in MODULES)/len(MODULES)
    return value


def fit_weights(exs):
    if len(exs) < MIN_GAMES:
        return {name: 0.0 for name in MODULES}
    weights = {name: 0.0 for name in MODULES}
    coarse = [i/10.0 for i in range(int(MAX_WEIGHT*10)+1)]
    if MAX_WEIGHT not in coarse:
        coarse.append(MAX_WEIGHT)
    for _ in range(3):
        changed = False
        for name in MODULES:
            best_w = weights[name]
            best_obj = _objective(exs, weights)
            for candidate in coarse:
                trial = dict(weights)
                trial[name] = candidate
                obj = _objective(exs, trial)
                if obj < best_obj-1e-10:
                    best_obj, best_w = obj, candidate
            if abs(best_w-weights[name]) > 1e-12:
                weights[name] = best_w
                changed = True
        if not changed:
            break
    # Small local refinement after the stable coarse solution.
    for name in MODULES:
        center = weights[name]
        candidates = sorted({max(0.0, min(MAX_WEIGHT, center+d)) for d in (-.10, -.05, 0, .05, .10)})
        best_w, best_obj = center, _objective(exs, weights)
        for candidate in candidates:
            trial = dict(weights); trial[name] = candidate
            obj = _objective(exs, trial)
            if obj < best_obj-1e-10:
                best_obj, best_w = obj, candidate
        weights[name] = round(best_w, 4)
    return weights


def _game_loss(ex, weights):
    h, a, _, _ = _weighted_runs(ex, weights)
    probs = []
    for opt in ex["options"]:
        p, y = _option_probability(ex, opt, weights), opt["y"]
        probs.append(.50*(-(y*math.log(p)+(1-y)*math.log(1-p))) + .35*((p-y)**2))
    probability = sum(probs)/max(1, len(probs))
    runs = .15*min(1.5, ((abs(h-ex["home_score"])+abs(a-ex["away_score"]))/2)/5.0)
    return probability+runs


def _percentile(values, q):
    if not values:
        return None
    xs = sorted(values)
    pos = max(0.0, min(len(xs)-1, q*(len(xs)-1)))
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo]*(hi-pos)+xs[hi]*(pos-lo)


def _bootstrap_ci(deltas, seed):
    if len(deltas) < 8:
        return [None, None]
    rng = random.Random(seed)
    n = len(deltas)
    samples = []
    for _ in range(_BOOTSTRAPS):
        samples.append(sum(deltas[rng.randrange(n)] for _ in range(n))/n)
    return [_percentile(samples, .025), _percentile(samples, .975)]


def module_diagnostics(exs, learned_weights):
    zero = {name: 0.0 for name in MODULES}
    baseline = evaluate(exs, zero)
    out = {}
    for idx, name in enumerate(MODULES):
        one = dict(zero); one[name] = 1.0
        m = evaluate(exs, one)
        deltas = [_game_loss(ex, zero)-_game_loss(ex, one) for ex in exs]
        ci = _bootstrap_ci(deltas, 12400+idx)
        weight = _num(learned_weights.get(name), 0.0)
        lo, hi = ci
        if lo is not None and lo > 0 and weight >= .15:
            verdict = "KEEP"
        elif hi is not None and hi < 0 and weight <= .10:
            verdict = "REJECT"
        else:
            verdict = "WATCH"
        out[name] = {
            "learned_weight": weight,
            "brier_improvement": (baseline.get("brier") or 0)-(m.get("brier") or 0),
            "logloss_improvement": (baseline.get("logloss") or 0)-(m.get("logloss") or 0),
            "team_run_mae_improvement": (baseline.get("team_run_mae") or 0)-(m.get("team_run_mae") or 0),
            "paired_objective_improvement": sum(deltas)/len(deltas) if deltas else None,
            "paired_objective_ci95": ci,
            "verdict": verdict,
        }
    return out


def walk_forward(exs):
    if len(exs) < MIN_GAMES+WF_TEST_GAMES:
        return {"status": "COLLECTING", "windows": 0, "test_games": 0}
    baseline_all = []
    optimized_all = []
    windows = []
    start = MIN_GAMES
    while start < len(exs):
        test = exs[start:min(len(exs), start+WF_TEST_GAMES)]
        if not test:
            break
        train = exs[:start]
        weights = fit_weights(train)
        b = evaluate(test, {name: 0.0 for name in MODULES})
        o = evaluate(test, weights)
        windows.append({
            "train_games": len(train), "test_games": len(test), "weights": weights,
            "brier_improvement": (b.get("brier") or 0)-(o.get("brier") or 0),
            "logloss_improvement": (b.get("logloss") or 0)-(o.get("logloss") or 0),
            "team_run_mae_improvement": (b.get("team_run_mae") or 0)-(o.get("team_run_mae") or 0),
        })
        baseline_all.extend(test)
        optimized_all.append((test, weights))
        start += WF_TEST_GAMES
    # Aggregate frozen-window predictions without refitting on the test windows.
    brier_b = ll_b = brier_o = ll_o = 0.0
    nopt = 0
    team_b = team_o = total_b = total_o = 0.0
    ng = 0
    zero = {name: 0.0 for name in MODULES}
    for test, weights in optimized_all:
        for ex in test:
            hb, ab, _, _ = _weighted_runs(ex, zero)
            ho, ao, _, _ = _weighted_runs(ex, weights)
            team_b += abs(hb-ex["home_score"])+abs(ab-ex["away_score"])
            team_o += abs(ho-ex["home_score"])+abs(ao-ex["away_score"])
            total_b += abs((hb+ab)-(ex["home_score"]+ex["away_score"]))
            total_o += abs((ho+ao)-(ex["home_score"]+ex["away_score"]))
            ng += 1
            for opt in ex["options"]:
                pb, po, y = _option_probability(ex, opt, zero), _option_probability(ex, opt, weights), opt["y"]
                brier_b += (pb-y)**2; brier_o += (po-y)**2
                ll_b += -(y*math.log(pb)+(1-y)*math.log(1-pb))
                ll_o += -(y*math.log(po)+(1-y)*math.log(1-po))
                nopt += 1
    return {
        "status": "ACTIVE", "windows": len(windows), "test_games": ng,
        "baseline": {
            "brier": brier_b/max(1, nopt), "logloss": ll_b/max(1, nopt),
            "team_run_mae": team_b/max(1, 2*ng), "total_run_mae": total_b/max(1, ng),
        },
        "optimized": {
            "brier": brier_o/max(1, nopt), "logloss": ll_o/max(1, nopt),
            "team_run_mae": team_o/max(1, 2*ng), "total_run_mae": total_o/max(1, ng),
        },
        "windows_detail": windows[-6:],
    }


def build_model(rows):
    exs = examples(rows)
    n = len(exs)
    if n < MIN_GAMES:
        stage, status = "COLLECT", "COLLECTING"
    elif n < WALK_FORWARD_READY_GAMES:
        stage, status = "EXPERIMENTAL", "EXPERIMENTAL_SHADOW"
    elif n < MATURE_GAMES:
        stage, status = "WALK_FORWARD", "WALK_FORWARD_READY"
    else:
        stage, status = "MATURE_RESEARCH", "MATURE_RESEARCH"
    weights = fit_weights(exs)
    zero = {name: 0.0 for name in MODULES}
    baseline = evaluate(exs, zero)
    optimized = evaluate(exs, weights) if n >= MIN_GAMES else baseline
    model = {
        "schema": SCHEMA, "version": VERSION, "status": status, "stage": stage,
        "settled_games": n, "minimum_games": MIN_GAMES,
        "walk_forward_ready_games": WALK_FORWARD_READY_GAMES, "mature_games": MATURE_GAMES,
        "weights": weights,
        "active_for_v124_shadow": n >= MIN_GAMES,
        "research_only": True, "affects_v12_selection": False,
        "objective": {
            "probability": "0.50 LogLoss + 0.35 Brier", "runs": "0.15 scaled team-run MAE",
            "regularization": REGULARIZATION, "weight_bounds": [0.0, MAX_WEIGHT],
            "coverage_adjusted": True, "roi_used_for_training": False,
        },
        "in_sample_diagnostic": {"baseline": baseline, "optimized": optimized},
        "modules": module_diagnostics(exs, weights) if n else {},
        "walk_forward": walk_forward(exs),
        "promotion": {
            "automatic": False,
            "note": "No learned weight can affect V12.3.2. Promotion requires durable out-of-sample evidence and an explicit future production change.",
        },
    }
    return model


def _model_summary(model):
    return {
        "schema": model.get("schema"), "version": model.get("version"), "status": model.get("status"),
        "stage": model.get("stage"), "settled_games": model.get("settled_games"),
        "minimum_games": model.get("minimum_games"), "weights": model.get("weights"),
        "active_for_v124_shadow": bool(model.get("active_for_v124_shadow")),
        "research_only": True, "affects_v12_selection": False,
    }


def current_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    try:
        from . import journal
        _MODEL_CACHE = build_model(journal.load_rows())
    except Exception as exc:
        _MODEL_CACHE = {
            "schema": SCHEMA, "version": VERSION, "status": "ERROR", "stage": "ERROR",
            "settled_games": 0, "weights": {name: 0.0 for name in MODULES},
            "active_for_v124_shadow": False, "research_only": True, "affects_v12_selection": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return _MODEL_CACHE


def reset_cache():
    global _MODEL_CACHE
    _MODEL_CACHE = None


def optimized_variant(result, shadow, model):
    if not model.get("active_for_v124_shadow"):
        return None
    from . import predictive_v124 as v124
    base_h = _num(shadow.get("base_home_mu"), _num(result.get("hmu"), 4.4))
    base_a = _num(shadow.get("base_away_mu"), _num(result.get("amu"), 4.2))
    hlog = alog = 0.0
    effective = {}
    modules = shadow.get("modules") or {}
    for name in MODULES:
        mod = modules.get(name) or {}
        coverage = _coverage(mod)
        weight = max(0.0, min(MAX_WEIGHT, _num((model.get("weights") or {}).get(name), 0.0)))
        ew = weight*coverage
        effective[name] = {"learned_weight": weight, "coverage": coverage, "effective_weight": ew}
        hlog += ew*math.log(max(.80, min(1.20, _num(mod.get("home_factor"), 1.0))))
        alog += ew*math.log(max(.80, min(1.20, _num(mod.get("away_factor"), 1.0))))
    hf = max(.88, min(1.12, math.exp(hlog)))
    af = max(.88, min(1.12, math.exp(alog)))
    h = max(1.6, min(8.0, base_h*hf))
    a = max(1.6, min(8.0, base_a*af))
    unc = _num((modules.get("uncertainty") or {}).get("uncertainty"), 0.0)
    return {
        "home_mu": h, "away_mu": a, "home_factor": hf, "away_factor": af,
        "uncertainty": unc, "options": v124.price_variant(result, h, a, unc),
        "optimizer": _model_summary(model), "effective_weights": effective,
        "research_only": True, "affects_v12_selection": False,
    }


def install():
    global _INSTALLED
    if _INSTALLED:
        return True
    from . import predictive_v124 as v124
    if getattr(v124, "_weight_optimizer_v124_installed", False):
        _INSTALLED = True
        return True
    original_analyze = v124.analyze
    original_metrics = v124.metrics

    def analyze(result, v115=None):
        shadow = original_analyze(result, v115)
        model = current_model()
        shadow["weight_optimizer"] = _model_summary(model)
        variant = optimized_variant(result, shadow, model)
        if variant is not None:
            shadow.setdefault("variants", {})["optimized"] = variant
        return shadow

    def metrics(rows):
        report = original_metrics(rows)
        model = build_model(rows)
        report["weight_optimizer"] = model
        report.setdefault("activation", {})["optimizer_affects_v12_selection"] = False
        return report

    v124.analyze = analyze
    v124.metrics = metrics
    v124._weight_optimizer_v124_installed = True
    _INSTALLED = True
    return True
