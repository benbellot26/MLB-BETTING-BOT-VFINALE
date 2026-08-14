from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from . import config

FEATURES = (
    "home_ops", "away_ops", "home_lineup_ops", "away_lineup_ops",
    "home_team_era", "away_team_era", "home_starter_era", "away_starter_era",
    "home_starter_whip", "away_starter_whip", "home_starter_k9", "away_starter_k9",
    "home_starter_bb9", "away_starter_bb9", "home_starter_hr9", "away_starter_hr9",
    "home_operational_adjustment", "away_operational_adjustment", "park_factor",
    "temperature_c", "wind_kph", "humidity_pct",
    "home_bullpen_recent_era", "away_bullpen_recent_era",
    "home_bullpen_recent_whip", "away_bullpen_recent_whip",
    "home_bullpen_taxed", "away_bullpen_taxed",
    "home_bullpen_unavailable", "away_bullpen_unavailable",
)
PHASES = ("EARLY", "LATE", "FINAL")


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _maybe_num(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except Exception:
        return None


def _dt(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _logit(p):
    p = max(.001, min(.999, _num(p, .5)))
    return math.log(p/(1-p))


def _sigmoid(z):
    return 1/(1+math.exp(-max(-30, min(30, z))))


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def feature_schema_hash():
    raw = json.dumps({"version": config.FEATURE_SCHEMA_VERSION, "features": FEATURES}, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def feature_dict(result_or_row):
    f = dict(result_or_row.get("features") or {})
    starters = result_or_row.get("starters") or {}
    ctx = result_or_row.get("ctx") or {}
    if ctx:
        starters = {"home": ctx.get("home_starter") or {}, "away": ctx.get("away_starter") or {}}
    hs, aws = starters.get("home") or {}, starters.get("away") or {}
    f.update({
        "home_starter_era": hs.get("era"), "away_starter_era": aws.get("era"),
        "home_starter_whip": hs.get("whip"), "away_starter_whip": aws.get("whip"),
        "home_starter_k9": hs.get("k9"), "away_starter_k9": aws.get("k9"),
        "home_starter_bb9": hs.get("bb9"), "away_starter_bb9": aws.get("bb9"),
        "home_starter_hr9": hs.get("hr9"), "away_starter_hr9": aws.get("hr9"),
    })
    w = f.get("weather") or {}
    f["temperature_c"] = w.get("temperature_c")
    f["wind_kph"] = w.get("wind_kph")
    f["humidity_pct"] = w.get("humidity_pct")
    bp = f.get("bullpen") or {}
    hb, ab = bp.get("home") or {}, bp.get("away") or {}
    f.update({
        "home_bullpen_recent_era": hb.get("recent_reliever_era"),
        "away_bullpen_recent_era": ab.get("recent_reliever_era"),
        "home_bullpen_recent_whip": hb.get("recent_reliever_whip"),
        "away_bullpen_recent_whip": ab.get("recent_reliever_whip"),
        "home_bullpen_taxed": hb.get("taxed_relievers"),
        "away_bullpen_taxed": ab.get("taxed_relievers"),
        "home_bullpen_unavailable": hb.get("likely_unavailable_relievers"),
        "away_bullpen_unavailable": ab.get("likely_unavailable_relievers"),
    })
    return f


def _raw_vector(result_or_row):
    f = feature_dict(result_or_row)
    return [_maybe_num(f.get(name)) for name in FEATURES]


def _feature_stats(rows):
    raw = [_raw_vector(r) for r in rows]
    means, stds, observed = {}, {}, {}
    for i, name in enumerate(FEATURES):
        vals = [r[i] for r in raw if r[i] is not None]
        m = sum(vals)/len(vals) if vals else 0.0
        v = sum((x-m)**2 for x in vals)/len(vals) if vals else 0.0
        means[name] = m
        stds[name] = math.sqrt(v) or 1.0
        observed[name] = len(vals)
    return means, stds, observed


def vector(result_or_row, means=None):
    means = means or {name: 0.0 for name in FEATURES}
    raw = _raw_vector(result_or_row)
    return [means[FEATURES[i]] if raw[i] is None else raw[i] for i in range(len(FEATURES))]


def _standardize(xs, means, stds):
    return [[(row[i]-means[FEATURES[i]])/max(1e-9, stds[FEATURES[i]]) for i in range(len(FEATURES))] for row in xs]


def _solve(a, b):
    n = len(b)
    m = [list(a[i])+[b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            continue
        m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        m[col] = [x/div for x in m[col]]
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col]
            if abs(factor) < 1e-15:
                continue
            m[r] = [x-factor*y for x, y in zip(m[r], m[col])]
    return [m[i][-1] for i in range(n)]


def _ridge_fit(xs, ys, ridge=8.0):
    if not xs:
        return []
    p = len(xs[0])+1
    ata = [[0.0]*p for _ in range(p)]
    aty = [0.0]*p
    for x, y in zip(xs, ys):
        z = [1.0]+list(x)
        for i in range(p):
            aty[i] += z[i]*y
            for j in range(p):
                ata[i][j] += z[i]*z[j]
    for i in range(1, p):
        ata[i][i] += ridge
    return _solve(ata, aty)


def _predict_linear(coefs, x):
    if not coefs:
        return 0.0
    return coefs[0]+sum(c*v for c, v in zip(coefs[1:], x))


def _fit_calibrator(examples, iterations=800, lr=.025, l2=.02):
    a, b = 0.0, 1.0
    n = max(1, len(examples))
    for _ in range(iterations):
        ga = gb = 0.0
        for p, y in examples:
            x = _logit(p)
            q = _sigmoid(a+b*x)
            e = q-y
            ga += e
            gb += e*x
        a -= lr*(ga/n+l2*a)
        b -= lr*(gb/n+l2*(b-1))
    return a, b


def _binary_metrics(ps, ys):
    if not ps:
        return {"n": 0}
    n = len(ps)
    return {
        "n": n,
        "brier": sum((p-y)**2 for p, y in zip(ps, ys))/n,
        "logloss": sum(-(y*math.log(max(.001, p))+(1-y)*math.log(max(.001, 1-p))) for p, y in zip(ps, ys))/n,
        "accuracy": sum((p >= .5) == bool(y) for p, y in zip(ps, ys))/n,
    }


def _pregame(row):
    analyzed, game_time = _dt(row.get("analyzed_at")), _dt(row.get("game_date"))
    return bool(analyzed and game_time and analyzed < game_time)


def _compatible(row):
    return (row.get("schema") == config.SCHEMA_VERSION
            and row.get("engine_version") == config.VERSION
            and row.get("feature_schema") == config.FEATURE_SCHEMA_VERSION)


def base_runs(row):
    sh, sa = row.get("structural_home_runs"), row.get("structural_away_runs")
    if sh is not None and sa is not None:
        return _num(sh), _num(sa)
    model = row.get("model") or {}
    if not model.get("active") and row.get("projected_home_runs") is not None and row.get("projected_away_runs") is not None:
        return _num(row.get("projected_home_runs")), _num(row.get("projected_away_runs"))
    return None, None


def canonical_phase_rows(rows, compatible_only=False):
    best = {}
    for r in rows:
        if r.get("result_status") != "FINAL" or not r.get("game_pk") or not r.get("features") or not _pregame(r):
            continue
        if compatible_only and not _compatible(r):
            continue
        if r.get("home_score") is None or r.get("away_score") is None:
            continue
        bh, ba = base_runs(r)
        if bh is None or ba is None:
            continue
        phase = str(r.get("phase") or "EARLY").upper()
        if phase not in PHASES:
            continue
        key = (str(r.get("game_pk")), phase)
        rank = str(r.get("analyzed_at") or "")
        if key not in best or rank > best[key][0]:
            best[key] = (rank, r)
    return sorted((x[1] for x in best.values()), key=lambda r: (str(r.get("game_date") or ""), str(r.get("analyzed_at") or "")))


def canonical_settled_rows(rows, phase=None, compatible_only=False):
    source = canonical_phase_rows(rows, compatible_only=compatible_only)
    if phase:
        return [r for r in source if str(r.get("phase") or "").upper() == str(phase).upper()]
    best = {}
    for r in source:
        gid, rank = str(r.get("game_pk")), str(r.get("analyzed_at") or "")
        if gid not in best or rank > best[gid][0]:
            best[gid] = (rank, r)
    return sorted((x[1] for x in best.values()), key=lambda r: (str(r.get("game_date") or ""), str(r.get("analyzed_at") or "")))


def _p(opt):
    return _num(opt.get("p_model", opt.get("p_effective")), .5)


def canonical_market_pair(row, market):
    opts = [o for o in row.get("options") or [] if o.get("market") == market]
    marked = [o for o in opts if o.get("is_canonical_line")]
    if market == "ML":
        home, away = str(row.get("home") or ""), str(row.get("away") or "")
        a = next((o for o in opts if _norm(o.get("name")) == _norm(home)), None)
        b = next((o for o in opts if _norm(o.get("name")) == _norm(away)), None)
        return (a, b) if a and b else (None, None)
    if marked:
        a = marked[0]
        if market == "RUNLINE":
            b = next((o for o in opts if _norm(o.get("name")) != _norm(a.get("name")) and o.get("point") is not None and abs(_num(o.get("point"))+_num(a.get("point"))) <= 1e-6), None)
        else:
            b = next((o for o in opts if str(o.get("name") or "").lower() != str(a.get("name") or "").lower() and o.get("point") is not None and abs(_num(o.get("point"))-_num(a.get("point"))) <= 1e-6), None)
        return (a, b) if b else (None, None)
    if market == "RUNLINE":
        home = str(row.get("home") or "")
        homes = [o for o in opts if _norm(o.get("name")) == _norm(home) and o.get("point") is not None]
        if not homes:
            return None, None
        a = min(homes, key=lambda o: abs(abs(_num(o.get("point")))-1.5))
        point = _num(a.get("point"))
        b = next((o for o in opts if _norm(o.get("name")) != _norm(home) and o.get("point") is not None and abs(_num(o.get("point"))+point) <= 1e-6), None)
        return (a, b) if b else (None, None)
    if market == "TOTAL":
        overs = sorted([o for o in opts if str(o.get("name") or "").lower() == "over" and o.get("point") is not None], key=lambda o: _num(o.get("point")))
        if not overs:
            return None, None
        a = overs[len(overs)//2]
        point = _num(a.get("point"))
        b = next((o for o in opts if str(o.get("name") or "").lower() == "under" and o.get("point") is not None and abs(_num(o.get("point"))-point) <= 1e-6), None)
        return (a, b) if b else (None, None)
    return None, None


def canonical_market_option(row, market):
    return canonical_market_pair(row, market)[0]


def dataset_fingerprint(rows):
    payload = [{
        "game_pk": r.get("game_pk"), "phase": r.get("phase"), "analyzed_at": r.get("analyzed_at"),
        "game_date": r.get("game_date"), "schema": r.get("schema"), "engine_version": r.get("engine_version"),
        "feature_schema": r.get("feature_schema"),
    } for r in sorted(rows, key=lambda x: (str(x.get("game_pk")), str(x.get("phase")), str(x.get("analyzed_at"))))]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_model(path=config.CHAMPION_MODEL_FILE):
    p = Path(path)
    if not p.exists():
        return {"active": False, "version": "structural-only", "artifact_status": "ABSENT"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"active": False, "version": "invalid-artifact", "artifact_status": "INVALID", "artifact_error": type(e).__name__}
    meta = d.get("metadata") or {}
    if meta.get("feature_schema_hash") != feature_schema_hash():
        return {"active": False, "version": d.get("version", "incompatible"), "artifact_status": "INCOMPATIBLE", "artifact_error": "feature_schema_hash_mismatch"}
    d["artifact_status"] = "VALID"
    return d


def _phase_model(model, phase):
    return ((model.get("phase_models") or {}).get(str(phase or "EARLY").upper()) or {})


def _apply_residual_component(home_mu, away_mu, result_like, residual):
    if not residual.get("active"):
        return home_mu, away_mu, {"active": False, "home_delta": 0.0, "away_delta": 0.0}
    means, stds = residual.get("means") or {}, residual.get("stds") or {}
    raw = vector(result_like, means)
    x = [(raw[i]-_num(means.get(FEATURES[i])))/max(1e-9, _num(stds.get(FEATURES[i]), 1)) for i in range(len(FEATURES))]
    hd = max(-config.MAX_LEARNED_RUN_ADJ, min(config.MAX_LEARNED_RUN_ADJ, _predict_linear(residual.get("home_coefs") or [], x)))
    ad = max(-config.MAX_LEARNED_RUN_ADJ, min(config.MAX_LEARNED_RUN_ADJ, _predict_linear(residual.get("away_coefs") or [], x)))
    return max(1.4, home_mu+hd), max(1.4, away_mu+ad), {"active": True, "home_delta": hd, "away_delta": ad}


def apply_run_correction(home_mu, away_mu, result_like, model=None, phase=None):
    model = load_model() if model is None else model
    phase = phase or result_like.get("phase") or "EARLY"
    if not model.get("active"):
        return home_mu, away_mu, {"active": False, "home_delta": 0.0, "away_delta": 0.0}
    residual = _phase_model(model, phase).get("residual") or {}
    h, a, info = _apply_residual_component(home_mu, away_mu, result_like, residual)
    info["phase"] = str(phase).upper()
    info["version"] = model.get("version")
    return h, a, info


def model_dispersion(model=None):
    model = load_model() if model is None else model
    d = model.get("dispersion") or {}
    if model.get("active") and d.get("active"):
        return max(.5, _num(d.get("value"), config.RUN_DISPERSION)), "champion"
    return config.RUN_DISPERSION, "fixed"


def model_environment_sigma(model=None):
    model = load_model() if model is None else model
    d = model.get("environment") or {}
    if model.get("active") and d.get("active"):
        return max(0.0, min(.30, _num(d.get("sigma"), config.RUN_ENV_SIGMA))), "champion"
    return config.RUN_ENV_SIGMA, "fixed"


def _apply_cal(cal, p):
    if cal.get("active"):
        return _sigmoid(_num(cal.get("a"))+_num(cal.get("b"), 1.0)*_logit(p))
    return max(.001, min(.999, _num(p, .5)))


def calibrate_triplet(market, p1, p2, p_push=0.0, model=None, phase="EARLY"):
    model = load_model() if model is None else model
    total = max(1e-9, _num(p1, .5)+_num(p2, .5))
    p1 = max(.001, min(.999, _num(p1, .5)/total))
    phase_model = _phase_model(model, phase)
    cal = ((phase_model.get("calibration") or {}).get(str(market).upper()) or {})
    if model.get("active") and cal.get("side", {}).get("active"):
        q1 = _apply_cal(cal["side"], p1)
        source = "champion"
    else:
        q1, source = p1, "uncalibrated"
    push_cal = cal.get("push") or {}
    qpush = _apply_cal(push_cal, max(.001, min(.35, _num(p_push, 0.0)))) if model.get("active") and push_cal.get("active") else max(0.0, min(.35, _num(p_push, 0.0)))
    return q1, 1-q1, qpush, source


def calibrate_pair(market, p1, p2, model=None, phase="EARLY"):
    q1, q2, _, source = calibrate_triplet(market, p1, p2, 0.0, model, phase)
    unc = model_uncertainty(market, q1, phase, model=model)
    return q1, q2, unc, source


def _uncertainty_bins(examples):
    bins = []
    edges = (0.0, .40, .45, .50, .55, .60, 1.001)
    for lo, hi in zip(edges[:-1], edges[1:]):
        z = [(p, y) for p, y in examples if lo <= p < hi]
        if not z:
            continue
        avgp = sum(p for p, _ in z)/len(z)
        hit = sum(y for _, y in z)/len(z)
        se = math.sqrt(max(.01, hit*(1-hit))/len(z))
        u = max(config.MIN_MODEL_UNCERTAINTY, min(config.MAX_MODEL_UNCERTAINTY, abs(hit-avgp)+se))
        bins.append({"lo": lo, "hi": hi, "n": len(z), "avg_probability": avgp, "hit_rate": hit, "uncertainty": u})
    return bins


def model_uncertainty(market, p, phase="EARLY", sharp_dispersion=None, dq_score=1.0, model=None):
    model = load_model() if model is None else model
    phase_model = _phase_model(model, phase)
    cal = ((phase_model.get("calibration") or {}).get(str(market).upper()) or {})
    bins = cal.get("uncertainty_bins") or []
    base = config.FALLBACK_MODEL_UNCERTAINTY
    for b in bins:
        if _num(b.get("lo")) <= p < _num(b.get("hi"), 1.001):
            base = _num(b.get("uncertainty"), base)
            break
    if sharp_dispersion is not None:
        base += .35*max(0.0, _num(sharp_dispersion))
    base += .04*max(0.0, 1-_num(dq_score, 1.0))
    return max(config.MIN_MODEL_UNCERTAINTY, min(config.MAX_MODEL_UNCERTAINTY, base))


def _estimate_dispersion(rows):
    numer = denom = 0.0
    for r in canonical_settled_rows(rows):
        bh, ba = base_runs(r)
        for mu, score in ((bh, r.get("home_score")), (ba, r.get("away_score"))):
            mu = max(.1, _num(mu))
            y = _num(score)
            numer += mu*mu
            denom += max(0.0, (y-mu)**2-mu)
    return config.RUN_DISPERSION if denom <= 1e-9 else max(2.0, min(30.0, numer/denom))


def _estimate_environment_sigma(rows):
    numer = denom = 0.0
    for r in canonical_settled_rows(rows):
        bh, ba = base_runs(r)
        if bh is None or ba is None:
            continue
        eh = _num(r.get("home_score"))-bh
        ea = _num(r.get("away_score"))-ba
        numer += eh*ea
        denom += max(.1, bh*ba)
    sigma2 = max(0.0, numer/max(1e-9, denom))
    return max(0.0, min(.25, math.sqrt(sigma2)))


def _nb_nll(mu, y, dispersion):
    r = max(.5, _num(dispersion, config.RUN_DISPERSION))
    mu = max(.01, _num(mu))
    y = max(0, int(_num(y)))
    p = r/(r+mu)
    return -(math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p))


def _run_nll(rows, dispersion):
    vals = []
    for r in canonical_settled_rows(rows):
        bh, ba = base_runs(r)
        vals += [_nb_nll(bh, r.get("home_score"), dispersion), _nb_nll(ba, r.get("away_score"), dispersion)]
    return sum(vals)/len(vals) if vals else None


def _fit_residual(rows):
    rows = list(rows)
    out = {"active": False, "n": len(rows), "status": "COLLECTING"}
    if len(rows) < config.MIN_RESIDUAL_TRAIN_GAMES:
        return out
    cut = min(max(config.MIN_RESIDUAL_TRAIN_GAMES, int(len(rows)*.78)), len(rows)-max(20, len(rows)//10))
    if cut <= 0 or cut >= len(rows):
        return out
    train, hold = rows[:cut], rows[cut:]
    means, stds, observed = _feature_stats(train)
    xs = _standardize([vector(r, means) for r in train], means, stds)
    yh, ya = [], []
    for r in train:
        bh, ba = base_runs(r)
        yh.append(_num(r.get("home_score"))-bh)
        ya.append(_num(r.get("away_score"))-ba)
    hc, ac = _ridge_fit(xs, yh), _ridge_fit(xs, ya)
    component = {"active": True, "means": means, "stds": stds, "observed": observed, "home_coefs": hc, "away_coefs": ac}
    base_err, model_err = [], []
    for r in hold:
        bh, ba = base_runs(r)
        ch, ca, _ = _apply_residual_component(bh, ba, r, component)
        ah, aa = _num(r.get("home_score")), _num(r.get("away_score"))
        base_err += [(bh-ah)**2, (ba-aa)**2]
        model_err += [(ch-ah)**2, (ca-aa)**2]
    base_rmse = math.sqrt(sum(base_err)/len(base_err))
    model_rmse = math.sqrt(sum(model_err)/len(model_err))
    passes = model_rmse <= base_rmse-config.MIN_RESIDUAL_RMSE_GAIN
    component.update({"active": passes, "n": len(rows), "train_n": len(train), "holdout_n": len(hold),
                      "base_rmse": base_rmse, "model_rmse": model_rmse, "passes": passes,
                      "status": "PASS" if passes else "FAIL"})
    return component


def _fit_calibration(rows, market):
    pairs = []
    push_examples = []
    for r in rows:
        a, b = canonical_market_pair(r, market)
        if not a or not b:
            continue
        result = a.get("result")
        if result not in {"WIN", "LOSS", "PUSH"}:
            continue
        push_examples.append((max(.001, min(.35, _num(a.get("p_push"), 0))), 1 if result == "PUSH" else 0))
        if result != "PUSH":
            pairs.append((_p(a), 1 if result == "WIN" else 0))
    out = {"active": False, "n": len(pairs), "side": {"active": False}, "push": {"active": False}}
    if len(pairs) < config.MIN_CALIBRATION_GAMES:
        out["status"] = "COLLECTING"
        return out
    cut = min(max(config.MIN_CALIBRATION_GAMES, int(len(pairs)*.75)), len(pairs)-config.MIN_CALIBRATION_HOLDOUT)
    if cut <= 0 or len(pairs)-cut < config.MIN_CALIBRATION_HOLDOUT:
        out["status"] = "COLLECTING"
        return out
    train, hold = pairs[:cut], pairs[cut:]
    a, b = _fit_calibrator(train)
    base = [_num(p, .5) for p, _ in hold]
    ys = [y for _, y in hold]
    cand = [_sigmoid(a+b*_logit(p)) for p in base]
    mb, mc = _binary_metrics(base, ys), _binary_metrics(cand, ys)
    gain = mb["brier"]-mc["brier"]
    side_pass = gain >= config.MIN_CALIBRATION_BRIER_GAIN and mc["logloss"] <= mb["logloss"]
    side = {"active": side_pass, "a": a, "b": b, "base": mb, "candidate": mc, "brier_gain": gain, "passes": side_pass}
    push = {"active": False, "n": len(push_examples)}
    if market != "ML" and len(push_examples) >= config.MIN_CALIBRATION_GAMES and any(y for _, y in push_examples):
        pcut = min(max(config.MIN_CALIBRATION_GAMES, int(len(push_examples)*.75)), len(push_examples)-config.MIN_CALIBRATION_HOLDOUT)
        if pcut > 0 and len(push_examples)-pcut >= config.MIN_CALIBRATION_HOLDOUT:
            pa, pb = _fit_calibrator(push_examples[:pcut])
            hb = push_examples[pcut:]
            bp = [p for p, _ in hb]
            by = [y for _, y in hb]
            cp = [_sigmoid(pa+pb*_logit(p)) for p in bp]
            pm0, pm1 = _binary_metrics(bp, by), _binary_metrics(cp, by)
            ppass = pm1["brier"] <= pm0["brier"] and pm1["logloss"] <= pm0["logloss"]
            push = {"active": ppass, "a": pa, "b": pb, "base": pm0, "candidate": pm1, "passes": ppass, "n": len(push_examples)}
    calibrated_examples = [(_sigmoid(a+b*_logit(p)) if side_pass else p, y) for p, y in pairs]
    out.update({"active": side_pass or push.get("active", False), "status": "PASS" if side_pass or push.get("active", False) else "FAIL",
                "side": side, "push": push, "uncertainty_bins": _uncertainty_bins(calibrated_examples),
                "train_n": len(train), "holdout_n": len(hold)})
    return out


def _build_components(rows):
    latest = canonical_settled_rows(rows)
    dispersion = {"active": False, "value": config.RUN_DISPERSION, "n": len(latest)}
    if len(latest) >= config.MIN_DISPERSION_TRAIN_GAMES+config.MIN_DISPERSION_HOLDOUT:
        cut = len(latest)-config.MIN_DISPERSION_HOLDOUT
        train, hold = latest[:cut], latest[cut:]
        cand = _estimate_dispersion(train)
        base_nll, cand_nll = _run_nll(hold, config.RUN_DISPERSION), _run_nll(hold, cand)
        gain = (base_nll-cand_nll) if base_nll is not None and cand_nll is not None else -999
        passed = gain >= config.MIN_DISPERSION_NLL_GAIN
        dispersion = {"active": passed, "value": cand if passed else config.RUN_DISPERSION,
                      "candidate_value": cand, "n": len(latest), "holdout_n": len(hold),
                      "base_nll": base_nll, "candidate_nll": cand_nll, "nll_gain": gain, "passes": passed}
    env_sigma = _estimate_environment_sigma(latest) if len(latest) >= config.MIN_DISPERSION_TRAIN_GAMES else config.RUN_ENV_SIGMA
    phase_models = {}
    for phase in PHASES:
        pr = canonical_settled_rows(rows, phase)
        phase_models[phase] = {
            "training_games": len(pr),
            "residual": _fit_residual(pr),
            "calibration": {m: _fit_calibration(pr, m) for m in ("ML", "RUNLINE", "TOTAL")},
        }
    return {"dispersion": dispersion,
            "environment": {"active": len(latest) >= config.MIN_DISPERSION_TRAIN_GAMES, "sigma": env_sigma, "n": len(latest)},
            "phase_models": phase_models}


def _force_active(model):
    d = json.loads(json.dumps(model))
    d["active"] = True
    return d


def _blend_saved(p, opt):
    sp = opt.get("p_market")
    if sp is None:
        return p
    w = max(0.0, min(config.MAX_MARKET_BLEND_WEIGHT, _num(opt.get("sharp_weight"), 0.0)))
    return max(.001, min(.999, (1-w)*p+w*_num(sp, .5)))


def predict_market_triplet(row, market, model):
    from . import engine_v12
    bh, ba = base_runs(row)
    if bh is None or ba is None:
        return None
    phase = str(row.get("phase") or "EARLY").upper()
    hmu, amu, _ = apply_run_correction(bh, ba, row, model, phase)
    dispersion = model_dispersion(model)[0]
    env_sigma = model_environment_sigma(model)[0]
    a, b = canonical_market_pair(row, market)
    if not a or not b:
        return None
    if market == "ML":
        p1 = engine_v12.prob_home_win(hmu, amu, dispersion, env_sigma)
        p2, push = 1-p1, 0.0
    elif market == "RUNLINE":
        p1w, push = engine_v12.prob_cover_parts(hmu, amu, "home", _num(a.get("point")), dispersion, env_sigma)
        p2w, push2 = engine_v12.prob_cover_parts(hmu, amu, "away", _num(b.get("point")), dispersion, env_sigma)
        push = (push+push2)/2
        p1 = p1w/max(1e-9, 1-push)
        p2 = p2w/max(1e-9, 1-push)
    else:
        p1w, push = engine_v12.prob_total_parts(hmu, amu, "over", _num(a.get("point")), dispersion, env_sigma)
        p2w, push2 = engine_v12.prob_total_parts(hmu, amu, "under", _num(b.get("point")), dispersion, env_sigma)
        push = (push+push2)/2
        p1 = p1w/max(1e-9, 1-push)
        p2 = p2w/max(1e-9, 1-push)
    total = max(1e-9, p1+p2)
    p1, p2 = p1/total, p2/total
    p1, p2 = _blend_saved(p1, a), _blend_saved(p2, b)
    total = max(1e-9, p1+p2)
    p1, p2 = p1/total, p2/total
    q1, q2, qpush, _ = calibrate_triplet(market, p1, p2, push, model, phase)
    return {"win": q1*(1-qpush), "push": qpush, "loss": q2*(1-qpush), "conditional": q1}


def _multiclass_metrics(rows, model):
    scores, losses, by_market = [], [], {}
    for market in ("ML", "RUNLINE", "TOTAL"):
        ms, ml = [], []
        for r in rows:
            a, _ = canonical_market_pair(r, market)
            if not a or a.get("result") not in {"WIN", "LOSS", "PUSH"}:
                continue
            pr = predict_market_triplet(r, market, model)
            if not pr:
                continue
            actual = a.get("result").lower()
            one = {"win": 0.0, "push": 0.0, "loss": 0.0}
            one[actual] = 1.0
            brier = sum((pr[k]-one[k])**2 for k in one)
            logloss = -math.log(max(.001, pr[actual]))
            ms.append(brier)
            ml.append(logloss)
            scores.append(brier)
            losses.append(logloss)
        by_market[market] = {"n": len(ms), "brier": sum(ms)/len(ms) if ms else None, "logloss": sum(ml)/len(ml) if ml else None}
    return {"n": len(scores), "brier": sum(scores)/len(scores) if scores else None,
            "logloss": sum(losses)/len(losses) if losses else None, "by_market": by_market}


def evaluate_stack(rows, incumbent, challenger):
    base = _multiclass_metrics(rows, incumbent)
    cand = _multiclass_metrics(rows, _force_active(challenger))
    if not base.get("n") or not cand.get("n"):
        return {"passes": False, "status": "COLLECTING", "baseline": base, "candidate": cand}
    brier_gain = _num(base.get("brier"))-_num(cand.get("brier"))
    logloss_gain = _num(base.get("logloss"))-_num(cand.get("logloss"))
    market_safe = True
    for m in ("ML", "RUNLINE", "TOTAL"):
        b0, b1 = base["by_market"].get(m) or {}, cand["by_market"].get(m) or {}
        if b0.get("n", 0) >= 15 and b1.get("n", 0) >= 15 and _num(b1.get("brier"), 1) > _num(b0.get("brier"), 1)+.003:
            market_safe = False
    passes = (cand["n"] >= config.MIN_STACK_HOLDOUT_GAMES and brier_gain >= config.MIN_STACK_BRIER_GAIN
              and logloss_gain >= config.MIN_STACK_LOGLOSS_GAIN and market_safe)
    return {"passes": passes, "status": "PASS" if passes else "FAIL", "baseline": base, "candidate": cand,
            "brier_gain": brier_gain, "logloss_gain": logloss_gain, "market_safe": market_safe}


def _game_groups(rows):
    by = {}
    for r in rows:
        by.setdefault(str(r.get("game_pk")), []).append(r)
    order = sorted(by, key=lambda gid: min(str(r.get("game_date") or "") for r in by[gid]))
    return order, by


def _assemble_model(rows, incumbent, metadata=None):
    components = _build_components(rows)
    out = {
        "schema": "v12-champion-model-v3", "version": "v12-professional-challenger-3",
        "generated_at": datetime.now(timezone.utc).isoformat(), "active": False, "auto_promotion": False,
        "features": list(FEATURES), "feature_schema": config.FEATURE_SCHEMA_VERSION,
        "metadata": metadata or {}, "passes": False,
    }
    out.update(components)
    return out


def _walk_forward_gate(rows, incumbent, max_windows=4):
    games, by = _game_groups(rows)
    min_train = max(config.MIN_RESIDUAL_TRAIN_GAMES, config.MIN_CALIBRATION_GAMES, config.MIN_DISPERSION_TRAIN_GAMES)
    if len(games) < min_train+config.MIN_STACK_HOLDOUT_GAMES:
        return {"passes": False, "status": "COLLECTING", "windows": []}
    block = max(config.MIN_STACK_HOLDOUT_GAMES, min(60, len(games)//5))
    endpoints = list(range(min_train, len(games)-block+1, block))[-max_windows:]
    windows = []
    for end in endpoints:
        train_ids, test_ids = set(games[:end]), set(games[end:end+block])
        train = [r for gid in train_ids for r in by[gid]]
        test = [r for gid in test_ids for r in by[gid]]
        c = _assemble_model(train, incumbent)
        ev = evaluate_stack(test, incumbent, c)
        windows.append({"train_games": len(train_ids), "future_games": len(test_ids), **ev})
    valid = [w for w in windows if w.get("status") != "COLLECTING"]
    rate = sum(bool(w.get("passes")) for w in valid)/len(valid) if valid else 0.0
    passes = len(valid) >= config.MIN_WALK_FORWARD_WINDOWS and rate >= config.MIN_WALK_FORWARD_PASS_RATE
    return {"passes": passes, "status": "PASS" if passes else "FAIL" if valid else "COLLECTING",
            "pass_rate": rate, "valid_windows": len(valid), "windows": windows}


def build_candidate(rows, incumbent=None):
    incumbent = load_model() if incumbent is None else incumbent
    phase_rows = canonical_phase_rows(rows, compatible_only=True)
    games, by = _game_groups(phase_rows)
    metadata = {
        "engine_version": config.VERSION, "schema_version": config.SCHEMA_VERSION,
        "feature_schema": config.FEATURE_SCHEMA_VERSION, "feature_schema_hash": feature_schema_hash(),
        "dataset_fingerprint": dataset_fingerprint(phase_rows), "training_games_available": len(games),
        "training_rows_available": len(phase_rows), "training_cutoff": max((str(r.get("game_date") or "") for r in phase_rows), default=None),
        "code_commit": os.getenv("GITHUB_SHA", "unknown"),
        "incumbent_version": incumbent.get("version"), "incumbent_artifact_status": incumbent.get("artifact_status"),
    }
    out = _assemble_model(phase_rows, incumbent, metadata)
    if incumbent.get("artifact_error"):
        out["promotion_gate"] = {"passes": False, "status": "BLOCKED", "reason": "incumbent_artifact_invalid"}
        return out
    min_outer = max(config.MIN_RESIDUAL_TRAIN_GAMES, config.MIN_CALIBRATION_GAMES, config.MIN_DISPERSION_TRAIN_GAMES)
    if len(games) < min_outer+config.MIN_STACK_HOLDOUT_GAMES:
        out["promotion_gate"] = {"passes": False, "status": "COLLECTING", "reason": "insufficient_v12_2_games"}
        return out
    hold_n = max(config.MIN_STACK_HOLDOUT_GAMES, int(len(games)*.20))
    train_ids, hold_ids = set(games[:-hold_n]), set(games[-hold_n:])
    train_rows = [r for gid in train_ids for r in by[gid]]
    hold_rows = [r for gid in hold_ids for r in by[gid]]
    fitted = _assemble_model(train_rows, incumbent, metadata)
    for key in ("dispersion", "environment", "phase_models"):
        out[key] = fitted[key]
    out["stack_validation"] = evaluate_stack(hold_rows, incumbent, out)
    out["walk_forward_gate"] = _walk_forward_gate(phase_rows, incumbent)
    passes = bool(out["stack_validation"].get("passes") and out["walk_forward_gate"].get("passes"))
    out["passes"] = passes
    out["promotion_gate"] = {"passes": passes, "status": "PASS" if passes else "FAIL",
                             "requires": ["end_to_end_holdout", "walk_forward", "live_evidence_at_promotion"]}
    return out


def production_evidence_gate(summary):
    settled = int(_num(summary.get("settled_singles")))+int(_num(summary.get("settled_combos")))
    clv_n = int(_num(summary.get("close_candidate_clv_n")))
    passes = settled >= config.MIN_PROD_SETTLED_BETS and clv_n >= config.MIN_PROD_CLV_OBSERVATIONS
    return {"passes": passes, "settled_bets": settled, "required_settled_bets": config.MIN_PROD_SETTLED_BETS,
            "clv_observations": clv_n, "required_clv_observations": config.MIN_PROD_CLV_OBSERVATIONS,
            "status": "VALIDATED" if passes else "COLLECTING"}


def write_candidate(rows, path=config.CANDIDATE_MODEL_FILE):
    candidate = build_candidate(rows)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return candidate


def promote_candidate(candidate_path=config.CANDIDATE_MODEL_FILE, champion_path=config.CHAMPION_MODEL_FILE, require_live_evidence=True):
    cp = Path(candidate_path)
    if not cp.exists():
        raise FileNotFoundError(cp)
    candidate = json.loads(cp.read_text(encoding="utf-8"))
    if not candidate.get("passes") or not (candidate.get("promotion_gate") or {}).get("passes"):
        raise RuntimeError("Le challenger ne passe pas les gates end-to-end et walk-forward")
    meta = candidate.get("metadata") or {}
    if meta.get("feature_schema_hash") != feature_schema_hash() or meta.get("engine_version") != config.VERSION:
        raise RuntimeError("Artefact challenger incompatible avec le code courant")
    if require_live_evidence:
        from . import storage
        evidence = production_evidence_gate(storage.ledger_summary())
        if not evidence.get("passes"):
            raise RuntimeError(f"Preuve live insuffisante: {evidence}")
        candidate["live_evidence_at_promotion"] = evidence
    candidate["active"] = True
    candidate["promoted_at"] = datetime.now(timezone.utc).isoformat()
    candidate["metadata"]["promoted_by_commit"] = os.getenv("GITHUB_SHA", "unknown")
    p = Path(champion_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return candidate
