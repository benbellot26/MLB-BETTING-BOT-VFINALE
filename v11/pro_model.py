from __future__ import annotations

import json
import math
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


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


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


def _metrics(ps, ys):
    if not ps:
        return {"n": 0}
    n = len(ps)
    return {
        "n": n,
        "brier": sum((p-y)**2 for p, y in zip(ps, ys))/n,
        "logloss": sum(-(y*math.log(max(.001, p)) + (1-y)*math.log(max(.001, 1-p))) for p, y in zip(ps, ys))/n,
        "accuracy": sum((p >= .5) == bool(y) for p, y in zip(ps, ys))/n,
    }


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


def vector(result_or_row, means=None):
    f = feature_dict(result_or_row)
    means = means or {}
    return [_num(f.get(name), _num(means.get(name), 0.0)) for name in FEATURES]


def _mean_std(rows):
    means, stds = {}, {}
    for i, name in enumerate(FEATURES):
        vals = [_num(r[i]) for r in rows]
        m = sum(vals)/len(vals) if vals else 0.0
        v = sum((x-m)**2 for x in vals)/len(vals) if vals else 0.0
        means[name] = m
        stds[name] = math.sqrt(v) or 1.0
    return means, stds


def _standardize(xs, means, stds):
    return [[(row[i]-means[FEATURES[i]])/stds[FEATURES[i]] for i in range(len(FEATURES))] for row in xs]


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
    return coefs[0] + sum(c*v for c, v in zip(coefs[1:], x))


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
        ga = ga/n + l2*a
        gb = gb/n + l2*(b-1)
        a -= lr*ga
        b -= lr*gb
    return a, b


def _pregame(row):
    analyzed, game_time = _dt(row.get("analyzed_at")), _dt(row.get("game_date"))
    return bool(analyzed and game_time and analyzed < game_time)


def base_runs(row):
    """Return the immutable structural baseline used by every Challenger generation."""
    sh, sa = row.get("structural_home_runs"), row.get("structural_away_runs")
    if sh is not None and sa is not None:
        return _num(sh), _num(sa)
    model = row.get("model") or {}
    if not model.get("active") and row.get("projected_home_runs") is not None and row.get("projected_away_runs") is not None:
        return _num(row.get("projected_home_runs")), _num(row.get("projected_away_runs"))
    return None, None


def canonical_settled_rows(rows):
    """Exactly one latest pregame snapshot per settled game, preventing train/holdout leakage."""
    best = {}
    for r in rows:
        if r.get("result_status") != "FINAL" or not r.get("game_pk") or not r.get("features") or not _pregame(r):
            continue
        if r.get("home_score") is None or r.get("away_score") is None:
            continue
        bh, ba = base_runs(r)
        if bh is None or ba is None:
            continue
        gid = str(r.get("game_pk"))
        rank = str(r.get("analyzed_at") or "")
        if gid not in best or rank > best[gid][0]:
            best[gid] = (rank, r)
    return [x[1] for x in sorted(best.values(), key=lambda z: z[0])]


def _p(opt):
    return _num(opt.get("p_model", opt.get("p_effective")), .5)


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def canonical_market_pair(row, market):
    """Return one stable canonical complementary pair per game/market."""
    opts = [o for o in row.get("options") or [] if o.get("market") == market]
    if market == "ML":
        home, away = str(row.get("home") or ""), str(row.get("away") or "")
        a = next((o for o in opts if _norm(o.get("name")) == _norm(home)), None)
        b = next((o for o in opts if _norm(o.get("name")) == _norm(away)), None)
        return (a, b) if a and b else (None, None)
    if market == "RUNLINE":
        home = str(row.get("home") or "")
        homes = [o for o in opts if _norm(o.get("name")) == _norm(home) and o.get("point") is not None]
        if not homes:
            return None, None
        a = min(homes, key=lambda o: (abs(_p(o)-.5), abs(abs(_num(o.get("point")))-1.5)))
        point = _num(a.get("point"))
        b = next((o for o in opts if _norm(o.get("name")) != _norm(home) and o.get("point") is not None and abs(_num(o.get("point"))+point) <= 1e-6), None)
        return (a, b) if b else (None, None)
    if market == "TOTAL":
        overs = [o for o in opts if str(o.get("name") or "").lower() == "over" and o.get("point") is not None]
        if not overs:
            return None, None
        a = min(overs, key=lambda o: abs(_p(o)-.5))
        point = _num(a.get("point"))
        b = next((o for o in opts if str(o.get("name") or "").lower() == "under" and o.get("point") is not None and abs(_num(o.get("point"))-point) <= 1e-6), None)
        return (a, b) if b else (None, None)
    return None, None


def canonical_market_option(row, market):
    a, _ = canonical_market_pair(row, market)
    return a


def load_model(path=config.CHAMPION_MODEL_FILE):
    p = Path(path)
    if not p.exists():
        return {"active": False, "version": "structural-only"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if d.get("active") else {"active": False, "version": d.get("version", "inactive")}
    except Exception:
        return {"active": False, "version": "invalid-artifact"}


def apply_run_correction(home_mu, away_mu, result_like, model=None):
    model = load_model() if model is None else model
    residual = model.get("residual") or {}
    if not model.get("active") or not residual.get("active"):
        return home_mu, away_mu, {"active": False, "home_delta": 0.0, "away_delta": 0.0}
    means, stds = residual.get("means") or {}, residual.get("stds") or {}
    raw = vector(result_like, means)
    x = [(raw[i]-_num(means.get(FEATURES[i])))/max(1e-9, _num(stds.get(FEATURES[i]), 1)) for i in range(len(FEATURES))]
    hd = max(-config.MAX_LEARNED_RUN_ADJ, min(config.MAX_LEARNED_RUN_ADJ, _predict_linear(residual.get("home_coefs") or [], x)))
    ad = max(-config.MAX_LEARNED_RUN_ADJ, min(config.MAX_LEARNED_RUN_ADJ, _predict_linear(residual.get("away_coefs") or [], x)))
    return max(1.4, home_mu+hd), max(1.4, away_mu+ad), {
        "active": True, "home_delta": hd, "away_delta": ad, "version": model.get("version")
    }


def model_dispersion(model=None):
    model = load_model() if model is None else model
    d = model.get("dispersion") or {}
    if model.get("active") and d.get("active"):
        return max(.5, _num(d.get("value"), config.RUN_DISPERSION)), "champion"
    return config.RUN_DISPERSION, "fixed"


def calibrate_pair(market, p1, p2, model=None):
    """Calibrate one canonical side and complement it, preserving p1+p2=1 exactly."""
    model = load_model() if model is None else model
    total = max(1e-9, _num(p1, .5)+_num(p2, .5))
    p1 = max(.001, min(.999, _num(p1, .5)/total))
    cal = ((model.get("calibration") or {}).get(str(market).upper()) or {})
    if model.get("active") and cal.get("active"):
        q1 = _sigmoid(_num(cal.get("a")) + _num(cal.get("b"), 1.0)*_logit(p1))
        hold_n = max(1, int(cal.get("holdout_n", 1)))
        unc = max(config.MIN_MODEL_UNCERTAINTY, math.sqrt(max(1e-9, _num(cal.get("holdout_brier"), .25))/hold_n))
        return q1, 1-q1, unc, "champion"
    return p1, 1-p1, config.FALLBACK_MODEL_UNCERTAINTY, "uncalibrated"


def calibrate(market, p, model=None):
    q, _, u, s = calibrate_pair(market, p, 1-_num(p, .5), model)
    return q, u, s


def _estimate_dispersion(rows):
    numer = denom = 0.0
    for r in rows:
        bh, ba = base_runs(r)
        for mu, score in ((bh, r.get("home_score")), (ba, r.get("away_score"))):
            mu = max(.1, _num(mu))
            y = _num(score)
            numer += mu*mu
            denom += max(0.0, (y-mu)**2-mu)
    if denom <= 1e-9:
        return config.RUN_DISPERSION
    return max(2.0, min(30.0, numer/denom))


def _nb_nll(mu, y, dispersion):
    r = max(.5, _num(dispersion, config.RUN_DISPERSION))
    mu = max(.01, _num(mu))
    y = max(0, int(_num(y)))
    p = r/(r+mu)
    logp = math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p)
    return -logp


def _run_nll(rows, dispersion):
    vals = []
    for r in rows:
        bh, ba = base_runs(r)
        vals += [_nb_nll(bh, r.get("home_score"), dispersion), _nb_nll(ba, r.get("away_score"), dispersion)]
    return sum(vals)/len(vals) if vals else None


def build_candidate(rows):
    settled = canonical_settled_rows(rows)
    out = {
        "schema": "v12-champion-model-v2",
        "version": "v12-professional-challenger-2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active": False,
        "auto_promotion": False,
        "features": list(FEATURES),
        "training_games": len(settled),
        "residual": {"active": False, "n": len(settled)},
        "dispersion": {"active": False, "value": config.RUN_DISPERSION, "n": len(settled)},
        "run_dispersion": config.RUN_DISPERSION,
        "calibration": {},
        "passes": False,
    }

    if len(settled) >= config.MIN_DISPERSION_TRAIN_GAMES:
        cut = max(config.MIN_DISPERSION_TRAIN_GAMES, int(len(settled)*.75))
        cut = min(cut, len(settled)-config.MIN_DISPERSION_HOLDOUT)
        if cut > 0 and len(settled)-cut >= config.MIN_DISPERSION_HOLDOUT:
            train, hold = settled[:cut], settled[cut:]
            cand_d = _estimate_dispersion(train)
            base_nll = _run_nll(hold, config.RUN_DISPERSION)
            cand_nll = _run_nll(hold, cand_d)
            gain = (base_nll-cand_nll) if base_nll is not None and cand_nll is not None else -999
            passes = gain >= config.MIN_DISPERSION_NLL_GAIN
            out["dispersion"] = {
                "active": passes, "value": cand_d if passes else config.RUN_DISPERSION,
                "candidate_value": cand_d, "n": len(settled), "train_n": len(train), "holdout_n": len(hold),
                "base_nll": base_nll, "candidate_nll": cand_nll, "nll_gain": gain, "passes": passes,
            }
            out["run_dispersion"] = out["dispersion"]["value"]

    residual_pass = False
    if len(settled) >= config.MIN_RESIDUAL_TRAIN_GAMES:
        cut = max(config.MIN_RESIDUAL_TRAIN_GAMES, int(len(settled)*.75))
        cut = min(cut, len(settled)-max(20, len(settled)//10))
        train, hold = settled[:cut], settled[cut:]
        raw_train = [vector(r) for r in train]
        means, stds = _mean_std(raw_train)
        xs = _standardize(raw_train, means, stds)
        yh, ya = [], []
        for r in train:
            bh, ba = base_runs(r)
            yh.append(_num(r.get("home_score"))-bh)
            ya.append(_num(r.get("away_score"))-ba)
        hc, ac = _ridge_fit(xs, yh), _ridge_fit(xs, ya)
        hold_raw = [vector(r, means) for r in hold]
        hold_x = _standardize(hold_raw, means, stds)
        base_err, model_err = [], []
        for r, x in zip(hold, hold_x):
            bh, ba = base_runs(r)
            ah, aa = _num(r.get("home_score")), _num(r.get("away_score"))
            base_err += [(bh-ah)**2, (ba-aa)**2]
            model_err += [(bh+_predict_linear(hc, x)-ah)**2, (ba+_predict_linear(ac, x)-aa)**2]
        base_rmse = math.sqrt(sum(base_err)/len(base_err)) if base_err else None
        model_rmse = math.sqrt(sum(model_err)/len(model_err)) if model_err else None
        residual_pass = bool(model_rmse is not None and base_rmse is not None and model_rmse <= base_rmse-config.MIN_RESIDUAL_RMSE_GAIN)
        out["residual"] = {
            "active": residual_pass, "n": len(settled), "train_n": len(train), "holdout_n": len(hold),
            "means": means, "stds": stds, "home_coefs": hc, "away_coefs": ac,
            "base_rmse": base_rmse, "model_rmse": model_rmse, "passes": residual_pass,
        }

    calibration_passes = []
    for market in ("ML", "RUNLINE", "TOTAL"):
        ex = []
        for r in settled:
            o = canonical_market_option(r, market)
            if not o or o.get("result") not in {"WIN", "LOSS"}:
                continue
            ex.append((_p(o), 1 if o.get("result") == "WIN" else 0))
        if len(ex) < config.MIN_CALIBRATION_GAMES:
            out["calibration"][market] = {"active": False, "n": len(ex), "status": "COLLECTING"}
            continue
        cut = max(config.MIN_CALIBRATION_GAMES, int(len(ex)*.75))
        cut = min(cut, len(ex)-config.MIN_CALIBRATION_HOLDOUT)
        if cut <= 0 or len(ex)-cut < config.MIN_CALIBRATION_HOLDOUT:
            out["calibration"][market] = {"active": False, "n": len(ex), "status": "COLLECTING"}
            continue
        train, hold = ex[:cut], ex[cut:]
        a, b = _fit_calibrator(train)
        base = [_num(p, .5) for p, _ in hold]
        ys = [y for _, y in hold]
        cand = [_sigmoid(a+b*_logit(p)) for p in base]
        mb, mc = _metrics(base, ys), _metrics(cand, ys)
        gain = mb["brier"]-mc["brier"]
        passes = gain >= config.MIN_CALIBRATION_BRIER_GAIN and mc["logloss"] <= mb["logloss"]
        calibration_passes.append(passes)
        out["calibration"][market] = {
            "active": passes, "n": len(ex), "train_n": len(train), "holdout_n": len(hold),
            "a": a, "b": b, "base": mb, "candidate": mc,
            "brier_gain": gain, "holdout_brier": mc["brier"], "passes": passes,
            "target": "canonical_home" if market in {"ML", "RUNLINE"} else "canonical_over",
        }

    out["passes"] = residual_pass or any(calibration_passes) or bool((out.get("dispersion") or {}).get("active"))
    return out


def write_candidate(rows, path=config.CANDIDATE_MODEL_FILE):
    candidate = build_candidate(rows)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return candidate


def promote_candidate(candidate_path=config.CANDIDATE_MODEL_FILE, champion_path=config.CHAMPION_MODEL_FILE):
    cp = Path(candidate_path)
    if not cp.exists():
        raise FileNotFoundError(cp)
    candidate = json.loads(cp.read_text(encoding="utf-8"))
    if not candidate.get("passes"):
        raise RuntimeError("Le challenger ne passe pas les critères de promotion")
    candidate["active"] = True
    candidate["promoted_at"] = datetime.now(timezone.utc).isoformat()
    p = Path(champion_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return candidate
