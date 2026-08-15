from __future__ import annotations

import math

_INSTALLED = False
_pro = _config = _engine = None
_ORIGINALS = {}

RELIABILITY_EDGES = (0.0, .40, .45, .50, .55, .60, .65, .70, 1.001)
CONFIDENCE_EDGES = (.50, .55, .60, .65, .70, .75, 1.001)


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
    return 1/(1+math.exp(-max(-30.0, min(30.0, _num(z)))))


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _point_equal(a, b, opposite=False):
    if a is None or b is None:
        return a is None and b is None
    target = -_num(b) if opposite else _num(b)
    return abs(_num(a)-target) <= 1e-6


def _is_alternate_option(opt):
    if opt.get("is_canonical_line"):
        return False
    ref = opt.get("reference_market") or {}
    return str(ref.get("market_key") or "").lower() == "alternate_spreads"


def research_market_pair(row, market):
    """Return one non-alternate research line, independent of Winamax execution.

    ML is always the home/away pair. For Run Line and Total, explicitly marked
    canonical options are preferred. If the execution bookmaker did not expose
    the market, the best-supported featured sharp line is used. Alternate
    spreads are never admitted to calibration/training.
    """
    market = str(market or "").upper()
    opts = [o for o in row.get("options") or [] if str(o.get("market") or "").upper() == market]
    if market == "ML":
        home, away = str(row.get("home") or ""), str(row.get("away") or "")
        a = next((o for o in opts if _norm(o.get("name")) == _norm(home)), None)
        b = next((o for o in opts if _norm(o.get("name")) == _norm(away)), None)
        return (a, b) if a and b else (None, None)

    opts = [o for o in opts if not _is_alternate_option(o)]
    if not opts:
        return None, None

    def support(o):
        return (
            1 if o.get("is_canonical_line") else 0,
            _num(o.get("sharp_effective_n"), _num(o.get("refs"), 0)),
            _num(o.get("refs"), 0),
        )

    if market == "RUNLINE":
        home = str(row.get("home") or "")
        homes = [o for o in opts if _norm(o.get("name")) == _norm(home) and o.get("point") is not None]
        pairs = []
        for a in homes:
            b = next((o for o in opts
                      if _norm(o.get("name")) != _norm(home)
                      and o.get("point") is not None
                      and _point_equal(o.get("point"), a.get("point"), opposite=True)), None)
            if b:
                key = (
                    min(support(a)[0], support(b)[0]),
                    min(support(a)[1], support(b)[1]),
                    min(support(a)[2], support(b)[2]),
                    -abs(abs(_num(a.get("point")))-1.5),
                )
                pairs.append((key, a, b))
        if not pairs:
            return None, None
        _, a, b = max(pairs, key=lambda x: x[0])
        return a, b

    if market == "TOTAL":
        overs = [o for o in opts if str(o.get("name") or "").lower() == "over" and o.get("point") is not None]
        pairs = []
        for a in overs:
            b = next((o for o in opts
                      if str(o.get("name") or "").lower() == "under"
                      and o.get("point") is not None
                      and _point_equal(o.get("point"), a.get("point"))), None)
            if b:
                key = (
                    min(support(a)[0], support(b)[0]),
                    min(support(a)[1], support(b)[1]),
                    min(support(a)[2], support(b)[2]),
                    -abs(_num(a.get("p_market"), .5)-.5),
                )
                pairs.append((key, a, b))
        if not pairs:
            return None, None
        _, a, b = max(pairs, key=lambda x: x[0])
        return a, b

    return None, None


def reliability_metrics(examples, edges=RELIABILITY_EDGES):
    examples = [(_clip(p), int(bool(y))) for p, y in examples]
    if not examples:
        return {"n": 0, "ece": None, "mce": None, "bins": []}
    bins = []
    n = len(examples)
    ece = 0.0
    mce = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        z = [(p, y) for p, y in examples if lo <= p < hi]
        if not z:
            continue
        avgp = sum(p for p, _ in z)/len(z)
        hit = sum(y for _, y in z)/len(z)
        gap = abs(hit-avgp)
        ece += len(z)/n*gap
        mce = max(mce, gap)
        bins.append({
            "lo": lo, "hi": hi, "n": len(z),
            "avg_probability": avgp, "hit_rate": hit,
            "gap": gap,
        })
    return {"n": n, "ece": ece, "mce": mce, "bins": bins}


def _binary_diagnostics(examples):
    examples = [(_clip(p), int(bool(y))) for p, y in examples]
    if not examples:
        return {"n": 0, "brier": None, "logloss": None, "accuracy": None,
                "ece": None, "mce": None, "reliability_bins": [],
                "calibration_intercept": None, "calibration_slope": None}
    ps = [p for p, _ in examples]
    ys = [y for _, y in examples]
    n = len(examples)
    base = {
        "n": n,
        "brier": sum((p-y)**2 for p, y in examples)/n,
        "logloss": sum(-(y*math.log(max(.001, p))+(1-y)*math.log(max(.001, 1-p))) for p, y in examples)/n,
        "accuracy": sum((p >= .5) == bool(y) for p, y in examples)/n,
    }
    rel = reliability_metrics(examples)
    a = b = None
    if n >= 20 and 0 < sum(ys) < n:
        a, b = _pro._fit_calibrator(examples)
    base.update({
        "ece": rel["ece"], "mce": rel["mce"], "reliability_bins": rel["bins"],
        "calibration_intercept": a, "calibration_slope": b,
        "mean_probability": sum(ps)/n, "hit_rate": sum(ys)/n,
    })
    return base


def _fit_beta(examples, iterations=1200, lr=.018, l2=.03):
    # Monotone beta calibration:
    # logit(q) = c + a*log(p) + b*(-log(1-p)); identity is c=0,a=b=1.
    c, a, b = 0.0, 1.0, 1.0
    n = max(1, len(examples))
    for _ in range(iterations):
        gc = ga = gb = 0.0
        for p, y in examples:
            p = _clip(p)
            x1, x2 = math.log(p), -math.log(1-p)
            q = _sigmoid(c+a*x1+b*x2)
            e = q-int(bool(y))
            gc += e
            ga += e*x1
            gb += e*x2
        c -= lr*(gc/n+l2*c)
        a -= lr*(ga/n+l2*(a-1.0))
        b -= lr*(gb/n+l2*(b-1.0))
        c = max(-5.0, min(5.0, c))
        a = max(.05, min(5.0, a))
        b = max(.05, min(5.0, b))
    return {"method": "beta", "c": c, "a": a, "b": b}


def apply_calibrator(cal, p):
    p = _clip(p)
    if not cal or not cal.get("active"):
        return p
    method = str(cal.get("method") or "platt").lower()
    if method == "identity":
        return p
    if method == "beta":
        z = (_num(cal.get("c"))
             + _num(cal.get("a"), 1.0)*math.log(p)
             + _num(cal.get("b"), 1.0)*(-math.log(1-p)))
        return _sigmoid(z)
    return _sigmoid(_num(cal.get("a"))+_num(cal.get("b"), 1.0)*_logit(p))


def _fit_method(method, train):
    if method == "identity":
        return {"method": "identity", "active": False}
    if method == "beta":
        return _fit_beta(train)
    a, b = _pro._fit_calibrator(train)
    return {"method": "platt", "a": a, "b": b}


def _apply_params(params, p):
    p = _clip(p)
    method = str((params or {}).get("method") or "identity").lower()
    if method == "identity":
        return p
    if method == "beta":
        return _sigmoid(
            _num(params.get("c"))
            + _num(params.get("a"), 1.0)*math.log(p)
            + _num(params.get("b"), 1.0)*(-math.log(1-p))
        )
    return _sigmoid(_num(params.get("a"))+_num(params.get("b"), 1.0)*_logit(p))


def _evaluate_method(params, hold):
    transformed = [(_apply_params(params, p), y) for p, y in hold]
    return _binary_diagnostics(transformed)


def _fit_side_challenger(pairs):
    n = len(pairs)
    out = {
        "active": False, "method": "identity", "n": n, "status": "COLLECTING",
        "candidates": {}, "train_n": 0, "holdout_n": 0,
    }
    minimum = int(_config.MIN_CALIBRATION_GAMES)
    holdout = int(_config.MIN_CALIBRATION_HOLDOUT)
    if n < minimum+holdout:
        return out
    cut = min(max(minimum, int(n*.75)), n-holdout)
    if cut <= 0 or n-cut < holdout:
        return out
    train, hold = pairs[:cut], pairs[cut:]
    if len({y for _, y in train}) < 2 or len({y for _, y in hold}) < 2:
        out.update({"status": "COLLECTING_CLASSES", "train_n": len(train), "holdout_n": len(hold)})
        return out
    baseline = _binary_diagnostics(hold)
    candidates = {
        "identity": {"params": {"method": "identity"}, "metrics": baseline,
                     "brier_gain": 0.0, "logloss_gain": 0.0, "ece_gain": 0.0, "passes": True},
    }
    max_ece_regression = float(getattr(_config, "V123_MAX_CALIBRATION_ECE_REGRESSION", .002))
    for method in ("platt", "beta"):
        params = _fit_method(method, train)
        metrics = _evaluate_method(params, hold)
        brier_gain = _num(baseline.get("brier"), 9)-_num(metrics.get("brier"), 9)
        logloss_gain = _num(baseline.get("logloss"), 9)-_num(metrics.get("logloss"), 9)
        ece_gain = _num(baseline.get("ece"), 9)-_num(metrics.get("ece"), 9)
        passes = (
            brier_gain >= _config.MIN_CALIBRATION_BRIER_GAIN
            and logloss_gain >= -1e-12
            and _num(metrics.get("ece"), 9) <= _num(baseline.get("ece"), 9)+max_ece_regression
        )
        candidates[method] = {
            "params": params, "metrics": metrics,
            "brier_gain": brier_gain, "logloss_gain": logloss_gain,
            "ece_gain": ece_gain, "passes": passes,
        }
    eligible = [(name, c) for name, c in candidates.items() if name != "identity" and c["passes"]]
    if eligible:
        name, best = min(
            eligible,
            key=lambda item: (
                _num(item[1]["metrics"].get("brier"), 9),
                _num(item[1]["metrics"].get("logloss"), 9),
                _num(item[1]["metrics"].get("ece"), 9),
            ),
        )
        params = dict(best["params"])
        params.update({
            "active": True, "passes": True, "method": name,
            "base": baseline, "candidate": best["metrics"],
            "brier_gain": best["brier_gain"], "logloss_gain": best["logloss_gain"],
            "ece_gain": best["ece_gain"],
        })
        out.update(params)
        out["status"] = "PASS"
    else:
        out.update({"active": False, "method": "identity", "passes": False, "status": "FAIL",
                    "base": baseline, "candidate": baseline, "brier_gain": 0.0,
                    "logloss_gain": 0.0, "ece_gain": 0.0})
    out.update({"candidates": candidates, "train_n": len(train), "holdout_n": len(hold)})
    return out


def _fit_push_challenger(examples):
    out = {"active": False, "method": "identity", "n": len(examples), "status": "COLLECTING"}
    if len(examples) < _config.MIN_CALIBRATION_GAMES+_config.MIN_CALIBRATION_HOLDOUT:
        return out
    if not any(y for _, y in examples):
        out["status"] = "NO_PUSHES"
        return out
    return _fit_side_challenger(examples)


def _fit_calibration_v2(rows, market):
    pairs, push_examples = [], []
    for row in rows:
        a, b = research_market_pair(row, market)
        if not a or not b:
            continue
        result = a.get("result")
        if result not in {"WIN", "LOSS", "PUSH"}:
            continue
        push_examples.append((max(.001, min(.35, _num(a.get("p_push"), 0))), 1 if result == "PUSH" else 0))
        if result != "PUSH":
            pairs.append((_pro._p(a), 1 if result == "WIN" else 0))

    side = _fit_side_challenger(pairs)
    push = {"active": False, "method": "identity", "n": len(push_examples), "status": "N/A"}
    if str(market).upper() != "ML":
        push = _fit_push_challenger(push_examples)

    calibrated_examples = [
        (apply_calibrator(side, p) if side.get("active") else _clip(p), y)
        for p, y in pairs
    ]
    out = {
        "active": bool(side.get("active") or push.get("active")),
        "status": "PASS" if side.get("active") or push.get("active")
                  else "COLLECTING" if str(side.get("status") or "").startswith("COLLECTING") else "FAIL",
        "n": len(pairs), "side": side, "push": push,
        "uncertainty_bins": _pro._uncertainty_bins(calibrated_examples),
        "diagnostics": {
            "raw": _binary_diagnostics(pairs),
            "calibrated": _binary_diagnostics(calibrated_examples),
        },
        "train_n": side.get("train_n", 0), "holdout_n": side.get("holdout_n", 0),
        "research_line_policy": "featured sharp/main line allowed; alternate_spreads excluded; Winamax not required",
    }
    return out


def _build_components_v2(rows):
    out = _ORIGINALS["pro._build_components"](rows)
    latest = _pro.canonical_settled_rows(rows)
    out["global_calibration"] = {
        market: _fit_calibration_v2(latest, market)
        for market in ("ML", "RUNLINE", "TOTAL")
    }
    out["calibration_generation"] = "hierarchical-challenger-v2"
    return out


def _calibration_for(model, market, phase):
    phase_model = _pro._phase_model(model, phase)
    phase_cal = ((phase_model.get("calibration") or {}).get(str(market).upper()) or {})
    global_cal = ((model.get("global_calibration") or {}).get(str(market).upper()) or {})
    return phase_cal, global_cal


def calibrate_triplet_v2(market, p1, p2, p_push=0.0, model=None, phase="EARLY"):
    model = _pro.load_model() if model is None else model
    total = max(1e-9, _num(p1, .5)+_num(p2, .5))
    p1 = _clip(_num(p1, .5)/total)
    phase_cal, global_cal = _calibration_for(model, market, phase)
    q1, source = p1, "uncalibrated"
    if model.get("active"):
        if (phase_cal.get("side") or {}).get("active"):
            side = phase_cal["side"]
            q1 = apply_calibrator(side, p1)
            source = f"champion:phase:{str(side.get('method') or 'platt').lower()}"
        elif (global_cal.get("side") or {}).get("active"):
            side = global_cal["side"]
            q1 = apply_calibrator(side, p1)
            source = f"champion:global:{str(side.get('method') or 'platt').lower()}"

    qpush = max(0.0, min(.35, _num(p_push, 0.0)))
    if model.get("active"):
        if (phase_cal.get("push") or {}).get("active"):
            qpush = apply_calibrator(phase_cal["push"], max(.001, qpush))
        elif (global_cal.get("push") or {}).get("active"):
            qpush = apply_calibrator(global_cal["push"], max(.001, qpush))
    return q1, 1-q1, qpush, source


def model_uncertainty_v2(market, p, phase="EARLY", sharp_dispersion=None, dq_score=1.0, model=None):
    model = _pro.load_model() if model is None else model
    phase_cal, global_cal = _calibration_for(model, market, phase)
    bins = phase_cal.get("uncertainty_bins") or global_cal.get("uncertainty_bins") or []
    base = _config.FALLBACK_MODEL_UNCERTAINTY
    for bucket in bins:
        if _num(bucket.get("lo")) <= p < _num(bucket.get("hi"), 1.001):
            base = _num(bucket.get("uncertainty"), base)
            break
    if sharp_dispersion is not None:
        base += .35*max(0.0, _num(sharp_dispersion))
    base += .04*max(0.0, 1-_num(dq_score, 1.0))
    return max(_config.MIN_MODEL_UNCERTAINTY, min(_config.MAX_MODEL_UNCERTAINTY, base))


def predict_market_triplet_research(row, market, model):
    bh, ba = _pro.base_runs(row)
    if bh is None or ba is None:
        return None
    phase = str(row.get("phase") or "EARLY").upper()
    stack = _pro.compose_runtime(bh, ba, row, model, phase)
    hmu, amu = stack["home_mu"], stack["away_mu"]
    dispersion, env_sigma = stack["dispersion"], stack["environment_sigma"]
    a, b = research_market_pair(row, market)
    if not a or not b:
        return None

    market = str(market).upper()
    if market == "ML":
        p1 = _engine.prob_home_win(hmu, amu, dispersion, env_sigma)
        p2, push = 1-p1, 0.0
    elif market == "RUNLINE":
        p1w, push = _engine.prob_cover_parts(hmu, amu, "home", _num(a.get("point")), dispersion, env_sigma)
        p2w, push2 = _engine.prob_cover_parts(hmu, amu, "away", _num(b.get("point")), dispersion, env_sigma)
        push = (push+push2)/2
        p1 = p1w/max(1e-9, 1-push)
        p2 = p2w/max(1e-9, 1-push)
    elif market == "TOTAL":
        p1w, push = _engine.prob_total_parts(hmu, amu, "over", _num(a.get("point")), dispersion, env_sigma)
        p2w, push2 = _engine.prob_total_parts(hmu, amu, "under", _num(b.get("point")), dispersion, env_sigma)
        push = (push+push2)/2
        p1 = p1w/max(1e-9, 1-push)
        p2 = p2w/max(1e-9, 1-push)
    else:
        return None

    total = max(1e-9, p1+p2)
    p1, p2 = p1/total, p2/total
    p1, p2 = _pro._blend_saved(p1, a), _pro._blend_saved(p2, b)
    total = max(1e-9, p1+p2)
    p1, p2 = p1/total, p2/total
    q1, q2, qpush, _ = calibrate_triplet_v2(market, p1, p2, push, model, phase)
    return {"win": q1*(1-qpush), "push": qpush, "loss": q2*(1-qpush), "conditional": q1}


def _confidence_examples(rows, market, probability_key="p_effective"):
    examples = []
    for row in rows:
        a, b = research_market_pair(row, market)
        if not a or not b:
            continue
        if a.get("result") not in {"WIN", "LOSS"} or b.get("result") not in {"WIN", "LOSS"}:
            continue
        pa, pb = _num(a.get(probability_key), .5), _num(b.get(probability_key), .5)
        chosen = a if pa >= pb else b
        p = max(pa, pb)
        examples.append((_clip(p), 1 if chosen.get("result") == "WIN" else 0))
    return examples


def _confidence_bands(examples):
    out = []
    for lo, hi in zip(CONFIDENCE_EDGES[:-1], CONFIDENCE_EDGES[1:]):
        z = [(p, y) for p, y in examples if lo <= p < hi]
        if not z:
            continue
        avgp = sum(p for p, _ in z)/len(z)
        hit = sum(y for _, y in z)/len(z)
        out.append({
            "lo": lo, "hi": hi, "n": len(z),
            "avg_confidence": avgp, "hit_rate": hit,
            "gap": hit-avgp,
        })
    return out


def calibration_diagnostics(rows, model=None):
    model = _pro.load_model() if model is None else model
    phase_rows = _pro.canonical_phase_rows(rows, compatible_only=True)
    latest = _pro.canonical_settled_rows(rows, compatible_only=True)

    def section(source_rows):
        by_market = {}
        for market in ("ML", "RUNLINE", "TOTAL"):
            raw, effective = [], []
            for row in source_rows:
                a, _ = research_market_pair(row, market)
                if not a or a.get("result") not in {"WIN", "LOSS"}:
                    continue
                y = 1 if a.get("result") == "WIN" else 0
                raw.append((_pro._p(a), y))
                effective.append((_num(a.get("p_effective"), _pro._p(a)), y))
            by_market[market] = {
                "raw_model": _binary_diagnostics(raw),
                "observed_effective": _binary_diagnostics(effective),
                "confidence_bands": _confidence_bands(_confidence_examples(source_rows, market)),
            }
        return by_market

    phases = {}
    for phase in ("EARLY", "LATE", "FINAL"):
        phases[phase] = section([r for r in phase_rows if str(r.get("phase") or "").upper() == phase])

    return {
        "schema": "v12-calibration-diagnostics-v2",
        "generation": "hierarchical identity-vs-platt-vs-beta challenger",
        "compatible_games": len({str(r.get("game_pk")) for r in phase_rows}),
        "latest_games": len(latest),
        "global": section(latest),
        "by_phase": phases,
        "champion_active": bool(model.get("active")),
        "global_calibration": model.get("global_calibration") or {},
        "policy": {
            "phase_specific_preferred": True,
            "global_market_fallback": True,
            "alternate_runlines_trainable": False,
            "winamax_required_for_calibration": False,
            "promotion": "existing end-to-end holdout + walk-forward + live evidence gates remain mandatory",
        },
    }


def install():
    global _INSTALLED, _pro, _config, _engine
    if _INSTALLED:
        return True
    from . import config, pro_model
    from . import engine_v12
    _config, _pro, _engine = config, pro_model, engine_v12

    config.V123_MAX_CALIBRATION_ECE_REGRESSION = float(
        getattr(config, "V123_MAX_CALIBRATION_ECE_REGRESSION", .002)
    )

    _ORIGINALS.update({
        "pro._apply_cal": pro_model._apply_cal,
        "pro._fit_calibration": pro_model._fit_calibration,
        "pro._build_components": pro_model._build_components,
        "pro.calibrate_triplet": pro_model.calibrate_triplet,
        "pro.model_uncertainty": pro_model.model_uncertainty,
        "pro.predict_market_triplet": pro_model.predict_market_triplet,
    })

    pro_model._apply_cal = apply_calibrator
    pro_model._fit_calibration = _fit_calibration_v2
    pro_model._build_components = _build_components_v2
    pro_model.calibrate_triplet = calibrate_triplet_v2
    pro_model.model_uncertainty = model_uncertainty_v2
    pro_model.predict_market_triplet = predict_market_triplet_research
    pro_model.research_market_pair = research_market_pair
    pro_model.reliability_metrics = reliability_metrics
    pro_model.calibration_diagnostics = calibration_diagnostics
    pro_model.CALIBRATION_GENERATION = "hierarchical-challenger-v2"

    _INSTALLED = True
    return True


def installed():
    return _INSTALLED
