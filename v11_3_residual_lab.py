#!/usr/bin/env python3
"""V11.3 leakage-safe residual learner over strict 2026 walk-forward rows.

Research/shadow only. The final chronological holdout is never used to select
features, regularization, decision threshold, or strong-pick threshold.

V11.3 keeps V10 as an offset and learns only a regularized residual correction.
Model family selection is done by expanding-window chronological CV inside the
first 75% of the season. The last 25% is opened once for the final verdict.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from statistics import mean

VERSION = "11.3-residual-cv-v1"
DEFAULT_INPUT = Path("data/v11_walkforward_2026.jsonl")
DEFAULT_V112_REPORT = Path("data/v11_2_report.json")
DEFAULT_REPORT = Path("data/v11_3_report.json")
DEFAULT_PREDS = Path("data/v11_3_predictions.jsonl")


def clamp(x, lo=.001, hi=.999):
    return max(lo, min(hi, float(x)))


def sigmoid(z):
    z = max(-30.0, min(30.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def logit(p):
    p = clamp(p)
    return math.log(p / (1.0 - p))


def fnum(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def feat(row):
    f = row.get("features") or {}
    cov = row.get("coverage") or {}
    hl = f.get("home_lineup_projected") or {}
    al = f.get("away_lineup_projected") or {}
    hs = f.get("home_starter") or {}
    ass = f.get("away_starter") or {}
    hb = f.get("home_bullpen") or {}
    ab = f.get("away_bullpen") or {}
    hm = f.get("home_matchup_projected") or {}
    am = f.get("away_matchup_projected") or {}

    lineup_ok = bool(hl.get("available") and al.get("available"))
    starter_ok = bool(hs.get("available") and ass.get("available"))
    bullpen_ok = bool(hb.get("available") and ab.get("available"))
    matchup_ok = bool(hm.get("available") and am.get("available"))

    if lineup_ok:
        h_lu, h_reg = fnum(hl.get("lineup_ops"), .720), fnum(hl.get("regular_ops"), .720)
        a_lu, a_reg = fnum(al.get("lineup_ops"), .720), fnum(al.get("regular_ops"), .720)
        lineup_relative = ((h_lu-h_reg) - (a_lu-a_reg)) / .08
        regular_overlap = (h_reg-a_reg) / .08
        lineup_abs = (h_lu-a_lu) / .08
        lineup_cov = fnum(hl.get("stats_coverage"), 0) - fnum(al.get("stats_coverage"), 0)
    else:
        lineup_relative = regular_overlap = lineup_abs = lineup_cov = 0.0

    starter_score = fnum(hs.get("score")) - fnum(ass.get("score")) if starter_ok else 0.0
    starter_recent = (fnum(ass.get("recent_metric"), 4.25) - fnum(hs.get("recent_metric"), 4.25)) / 1.5 if starter_ok else 0.0
    starter_season = (fnum(ass.get("season_metric"), 4.25) - fnum(hs.get("season_metric"), 4.25)) / 1.5 if starter_ok else 0.0
    starter_form_delta = ((fnum(ass.get("recent_metric"),4.25)-fnum(ass.get("season_metric"),4.25)) - (fnum(hs.get("recent_metric"),4.25)-fnum(hs.get("season_metric"),4.25))) / 1.5 if starter_ok else 0.0

    bullpen_score = fnum(hb.get("score")) - fnum(ab.get("score")) if bullpen_ok else 0.0
    bullpen_fatigue = fnum(ab.get("fatigue")) - fnum(hb.get("fatigue")) if bullpen_ok else 0.0
    bullpen_hl = (fnum(ab.get("high_leverage_unavailable")) - fnum(hb.get("high_leverage_unavailable"))) / 3.0 if bullpen_ok else 0.0
    bullpen_depth = (fnum(hb.get("reliever_count")) - fnum(ab.get("reliever_count"))) / 5.0 if bullpen_ok else 0.0

    matchup_score = fnum(hm.get("score")) - fnum(am.get("score")) if matchup_ok else 0.0
    matchup_adv = (fnum(hm.get("advantage_hitters")) - fnum(am.get("advantage_hitters"))) / 9.0 if matchup_ok else 0.0

    hrun = fnum(row.get("base_home_runs"), 4.3)
    arun = fnum(row.get("base_away_runs"), 4.3)
    base = clamp(row.get("base_p_home", .5))
    base_logit = logit(base)
    base_strength = min(abs(base_logit), 2.5) / 2.5

    return {
        "lineup_relative": lineup_relative,
        "regular_overlap": regular_overlap,
        "lineup_abs": lineup_abs,
        "lineup_cov_diff": lineup_cov,
        "starter_score_diff": starter_score,
        "starter_recent_diff": starter_recent,
        "starter_season_diff": starter_season,
        "starter_form_delta": starter_form_delta,
        "bullpen_score_diff": bullpen_score,
        "bullpen_fatigue_diff": bullpen_fatigue,
        "bullpen_hl_diff": bullpen_hl,
        "bullpen_depth_diff": bullpen_depth,
        "matchup_score_diff": matchup_score,
        "matchup_adv_diff": matchup_adv,
        "run_diff": (hrun-arun)/2.0,
        "run_total": (hrun+arun-8.6)/3.0,
        "base_strength": base_strength,
        "lineup_x_uncertainty": lineup_relative * (1.0-base_strength),
        "starter_x_uncertainty": starter_score * (1.0-base_strength),
        "bullpen_x_uncertainty": bullpen_score * (1.0-base_strength),
        "lineup_available": 1.0 if lineup_ok else 0.0,
        "starter_available": 1.0 if starter_ok else 0.0,
        "bullpen_available": 1.0 if bullpen_ok else 0.0,
        "matchup_available": 1.0 if matchup_ok else 0.0,
        "full_available": 1.0 if cov.get("full_projected") else 0.0,
    }


FEATURE_SETS = {
    "lineup": [
        "lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff",
        "lineup_x_uncertainty", "lineup_available",
    ],
    "lineup_run": [
        "lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff",
        "lineup_x_uncertainty", "lineup_available", "run_diff", "run_total", "base_strength",
    ],
    "lineup_starter": [
        "lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff",
        "lineup_x_uncertainty", "lineup_available", "starter_score_diff",
        "starter_recent_diff", "starter_season_diff", "starter_form_delta",
        "starter_x_uncertainty", "starter_available",
    ],
    "lineup_bullpen": [
        "lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff",
        "lineup_x_uncertainty", "lineup_available", "bullpen_score_diff",
        "bullpen_fatigue_diff", "bullpen_hl_diff", "bullpen_depth_diff",
        "bullpen_x_uncertainty", "bullpen_available",
    ],
    "full_regularized": [
        "lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff",
        "starter_score_diff", "starter_recent_diff", "starter_season_diff", "starter_form_delta",
        "bullpen_score_diff", "bullpen_fatigue_diff", "bullpen_hl_diff", "bullpen_depth_diff",
        "matchup_score_diff", "matchup_adv_diff", "run_diff", "run_total", "base_strength",
        "lineup_x_uncertainty", "starter_x_uncertainty", "bullpen_x_uncertainty",
        "lineup_available", "starter_available", "bullpen_available", "matchup_available", "full_available",
    ],
}


def solve_linear(a, b):
    n = len(b)
    m = [list(map(float, a[i])) + [float(b[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-10:
            m[pivot][col] += 1e-8
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        for j in range(col, n+1):
            m[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            fac = m[r][col]
            if abs(fac) < 1e-14:
                continue
            for j in range(col, n+1):
                m[r][j] -= fac*m[col][j]
    return [m[i][n] for i in range(n)]


def fit_model(rows, names, l2):
    raw = [feat(r) for r in rows]
    means = {k: mean(v[k] for v in raw) for k in names}
    stds = {}
    for k in names:
        var = mean((v[k]-means[k])**2 for v in raw)
        stds[k] = math.sqrt(var) if var > 1e-10 else 1.0
    xs = [[1.0] + [(v[k]-means[k])/stds[k] for k in names] for v in raw]
    ys = [int(r["y"]) for r in rows]
    offs = [logit(r.get("base_p_home", .5)) for r in rows]
    p = len(names)+1
    beta = [0.0]*p
    for _ in range(30):
        grad = [0.0]*p
        hess = [[0.0]*p for _ in range(p)]
        for x, y, off in zip(xs, ys, offs):
            pr = sigmoid(off + sum(beta[j]*x[j] for j in range(p)))
            err = pr-y
            w = max(pr*(1-pr), 1e-5)
            for j in range(p):
                grad[j] += err*x[j]
                for k in range(j+1):
                    hess[j][k] += w*x[j]*x[k]
        for j in range(p):
            for k in range(j):
                hess[k][j] = hess[j][k]
        for j in range(1, p):
            grad[j] += l2*beta[j]
            hess[j][j] += l2
        hess[0][0] += 1e-6
        delta = solve_linear(hess, grad)
        beta = [beta[j]-delta[j] for j in range(p)]
        if max(abs(x) for x in delta) < 1e-7:
            break
    return {"features": list(names), "l2": l2, "means": means, "stds": stds, "beta": beta}


def predict_model(row, model):
    v = feat(row)
    z = logit(row.get("base_p_home", .5)) + model["beta"][0]
    for i, k in enumerate(model["features"], 1):
        z += model["beta"][i] * ((v[k]-model["means"][k])/model["stds"][k])
    return clamp(sigmoid(z))


def v112_predict(row, params):
    v = feat(row)
    z = logit(row.get("base_p_home", .5))
    z += fnum(params.get("intercept"))
    z += fnum(params.get("relative_lineup_coef")) * v["lineup_relative"]
    z += fnum(params.get("regular_overlap_coef")) * v["regular_overlap"]
    return clamp(sigmoid(z))


def metrics(rows, pred_fn, threshold=.5):
    vals = [(pred_fn(r), int(r["y"])) for r in rows if r.get("y") in (0,1)]
    if not vals:
        return {"n": 0, "accuracy": None, "brier": None, "logloss": None}
    return {
        "n": len(vals),
        "accuracy": mean(((p >= threshold) == bool(y)) for p,y in vals),
        "brier": mean((p-y)**2 for p,y in vals),
        "logloss": mean(-(y*math.log(clamp(p)) + (1-y)*math.log(clamp(1-p))) for p,y in vals),
    }


def bootstrap_gain(rows, new_fn, base_fn, reps=4000, seed=113):
    pairs=[]
    for r in rows:
        if r.get("y") not in (0,1):
            continue
        y=int(r["y"]); pb=base_fn(r); pn=new_fn(r)
        pairs.append(((pb-y)**2, (pn-y)**2))
    if not pairs:
        return None
    rng=random.Random(seed); n=len(pairs); wins=0
    for _ in range(reps):
        gain=0.0
        for _ in range(n):
            b,nw=pairs[rng.randrange(n)]; gain += b-nw
        wins += gain > 0
    return wins/reps


def rolling_folds(n):
    # Expanding-window CV entirely inside the first 75% development sample.
    cuts=[(.34,.50),(.50,.63),(.63,.75),(.75,.875),(.875,1.0)]
    out=[]
    for tr_frac, va_frac in cuts:
        tr=max(120,int(n*tr_frac)); va=max(tr+30,int(n*va_frac))
        va=min(n,va)
        if va>tr:
            out.append((0,tr,tr,va))
    return out


def cv_candidate(train, names, l2):
    fold_rows=[]
    all_oof=[]
    for _,tr1,va0,va1 in rolling_folds(len(train)):
        tr=train[:tr1]; va=train[va0:va1]
        model=fit_model(tr,names,l2)
        m=metrics(va,lambda r,m=model:predict_model(r,m))
        fold_rows.append(m)
        for r in va:
            all_oof.append((r,predict_model(r,model)))
    if not fold_rows:
        return None
    weights=[x["n"] for x in fold_rows]; den=sum(weights)
    return {
        "cv_brier": sum(x["brier"]*w for x,w in zip(fold_rows,weights))/den,
        "cv_logloss": sum(x["logloss"]*w for x,w in zip(fold_rows,weights))/den,
        "cv_accuracy": sum(x["accuracy"]*w for x,w in zip(fold_rows,weights))/den,
        "folds": fold_rows,
        "oof": all_oof,
    }


def choose_decision_threshold(oof):
    best=None
    for t_i in range(460,541,2):
        t=t_i/1000.0
        acc=mean(((p>=t)==bool(int(r["y"]))) for r,p in oof)
        key=(acc,-abs(t-.5))
        if best is None or key>best[0]:
            best=(key,t,acc)
    return best[1],best[2]


def choose_strong_threshold(oof, target=.63, min_coverage=.25):
    n=len(oof); eligible=[]
    for c_i in range(520,701,5):
        c=c_i/1000.0
        sub=[(r,p) for r,p in oof if max(p,1-p)>=c]
        if not sub:
            continue
        cov=len(sub)/n
        acc=mean(((p>=.5)==bool(int(r["y"]))) for r,p in sub)
        eligible.append((c,cov,acc,len(sub)))
    passing=[x for x in eligible if x[1]>=min_coverage and x[2]>=target]
    if passing:
        # Maximize coverage once target accuracy is reached.
        return max(passing,key=lambda x:(x[1],x[2],-x[0]))
    viable=[x for x in eligible if x[1]>=min_coverage]
    return max(viable,key=lambda x:(x[2],x[1])) if viable else (0.60,0.0,0.0,0)


def strong_metrics(rows,pred_fn,certainty):
    sub=[]
    for r in rows:
        p=pred_fn(r)
        if max(p,1-p)>=certainty:
            sub.append(r)
    m=metrics(sub,pred_fn)
    m["coverage"]=len(sub)/len(rows) if rows else 0.0
    m["certainty_threshold"]=certainty
    return m


def self_test():
    rows=[]
    for i in range(300):
        base=.45 if i%2 else .55
        y=1 if (i%5 in (0,2,4)) else 0
        rows.append({"base_p_home":base,"y":y,"features":{},"coverage":{},"base_home_runs":4.3,"base_away_runs":4.2})
    m=fit_model(rows,FEATURE_SETS["lineup"],8.0)
    p=predict_model(rows[0],m)
    assert 0<p<1 and len(m["beta"])==len(FEATURE_SETS["lineup"])+1
    assert rolling_folds(300)
    print("SELF-TEST V11.3 RESIDUAL LAB OK")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default=str(DEFAULT_INPUT))
    ap.add_argument("--v112-report",default=str(DEFAULT_V112_REPORT))
    ap.add_argument("--report",default=str(DEFAULT_REPORT))
    ap.add_argument("--predictions",default=str(DEFAULT_PREDS))
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        self_test(); return

    rows=[json.loads(x) for x in Path(args.input).read_text(encoding="utf-8").splitlines() if x.strip()]
    rows=[r for r in rows if r.get("y") in (0,1) and r.get("base_p_home") is not None]
    rows.sort(key=lambda r:(r.get("game_date") or "",int(r.get("game_pk") or 0)))
    if len(rows)<1000:
        raise SystemExit("V11.3 requires the full leakage-safe walk-forward sample")
    split=int(len(rows)*.75); train,holdout=rows[:split],rows[split:]

    v112_rep=json.loads(Path(args.v112_report).read_text(encoding="utf-8")) if Path(args.v112_report).exists() else {}
    v112_params=v112_rep.get("selected_params") or {"intercept":.045,"relative_lineup_coef":.05,"regular_overlap_coef":-.25}
    base_fn=lambda r:clamp(r.get("base_p_home",.5))
    v112_fn=lambda r:v112_predict(r,v112_params)

    candidates=[]
    for set_name,names in FEATURE_SETS.items():
        for l2 in (0.5,2.0,8.0,32.0,128.0):
            cv=cv_candidate(train,names,l2)
            if cv:
                candidates.append({"feature_set":set_name,"l2":l2,**{k:v for k,v in cv.items() if k!="oof"},"_oof":cv["oof"]})
    # Primary selection = lowest chronological CV Brier; then LogLoss; then higher accuracy; then simpler set.
    selected=min(candidates,key=lambda x:(x["cv_brier"],x["cv_logloss"],-x["cv_accuracy"],len(FEATURE_SETS[x["feature_set"]]),x["l2"]))
    names=FEATURE_SETS[selected["feature_set"]]
    model=fit_model(train,names,selected["l2"])
    new_fn=lambda r:predict_model(r,model)

    # Rebuild OOF predictions using only the selected family/hyperparameter.
    selected_cv=cv_candidate(train,names,selected["l2"])
    oof=selected_cv["oof"]
    decision_threshold,oof_direction_acc=choose_decision_threshold(oof)
    strong_thr,strong_oof_cov,strong_oof_acc,strong_oof_n=choose_strong_threshold(oof,target=.63,min_coverage=.25)

    hold_base=metrics(holdout,base_fn)
    hold_v112=metrics(holdout,v112_fn)
    hold_new=metrics(holdout,new_fn)
    hold_new_dir=metrics(holdout,new_fn,threshold=decision_threshold)
    hold_strong=strong_metrics(holdout,new_fn,strong_thr)
    all_new=metrics(rows,new_fn)

    fixed_conf={}
    for c in (.54,.56,.58,.60,.62,.64):
        fixed_conf[f"{c:.2f}"]=strong_metrics(holdout,new_fn,c)

    monthly={}
    for r in holdout:
        monthly.setdefault(str(r.get("eastern_day") or "")[:7],[]).append(r)

    pred_rows=[]
    for i,r in enumerate(rows):
        p=new_fn(r)
        pred_rows.append({
            "version":VERSION,"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),"eastern_day":r.get("eastern_day"),
            "y":r.get("y"),"base_p_home":r.get("base_p_home"),"v11_2_p_home":round(v112_fn(r),6),"v11_3_p_home":round(p,6),
            "direction_threshold":decision_threshold,"v11_3_home_pick":bool(p>=decision_threshold),
            "strong_pick":bool(max(p,1-p)>=strong_thr),"partition":"train" if i<split else "holdout",
            "official_effect":False,"no_lookahead":bool(r.get("no_lookahead")),
        })

    public_candidates=[]
    for x in sorted(candidates,key=lambda z:(z["cv_brier"],z["cv_logloss"])):
        public_candidates.append({k:v for k,v in x.items() if k not in ("_oof","folds")})

    report={
        "version":VERSION,
        "official_effect":False,
        "samples":{"all":len(rows),"train":len(train),"holdout":len(holdout)},
        "methodology":{
            "base":"V10 logit as fixed offset",
            "train_holdout":"first 75% development / final 25% untouched holdout",
            "selection":"expanding-window chronological CV entirely inside development sample",
            "holdout_used_for_feature_selection":False,
            "holdout_used_for_regularization_selection":False,
            "holdout_used_for_decision_threshold":False,
            "holdout_used_for_strong_pick_threshold":False,
            "feature_policy":"previously weak baseball features may re-enter only through regularized residual learning; no heuristic production weight is restored",
            "live_confirmation_required":True,
        },
        "selected":{"feature_set":selected["feature_set"],"features":names,"l2":selected["l2"],"cv_brier":selected_cv["cv_brier"],"cv_logloss":selected_cv["cv_logloss"],"cv_accuracy":selected_cv["cv_accuracy"],"beta":model["beta"]},
        "thresholds":{"direction_threshold":decision_threshold,"oof_direction_accuracy":oof_direction_acc,"strong_certainty_threshold":strong_thr,"strong_oof_accuracy":strong_oof_acc,"strong_oof_coverage":strong_oof_cov,"strong_oof_n":strong_oof_n},
        "holdout":{"v10":hold_base,"v11_2":hold_v112,"v11_3_probability":hold_new,"v11_3_directional":hold_new_dir,"v11_3_strong_picks":hold_strong,"fixed_confidence_bands":fixed_conf,
            "brier_gain_vs_v10":hold_base["brier"]-hold_new["brier"],"brier_gain_vs_v11_2":hold_v112["brier"]-hold_new["brier"],
            "bootstrap_gain_probability_vs_v10":bootstrap_gain(holdout,new_fn,base_fn),"bootstrap_gain_probability_vs_v11_2":bootstrap_gain(holdout,new_fn,v112_fn,seed=114)},
        "all":{"v10":metrics(rows,base_fn),"v11_2":metrics(rows,v112_fn),"v11_3":all_new},
        "holdout_monthly":{k:{"v10":metrics(v,base_fn),"v11_2":metrics(v,v112_fn),"v11_3":metrics(v,new_fn)} for k,v in sorted(monthly.items())},
        "cv_candidates":public_candidates,
        "targets":{"all_match_holdout_accuracy":.60,"stretch_accuracy":.61,"strong_pick_accuracy":.63,"strong_pick_min_coverage":.25},
        "gate":{
            "v11_3_beats_v10_brier":hold_new["brier"]<hold_base["brier"],
            "v11_3_beats_v10_logloss":hold_new["logloss"]<hold_base["logloss"],
            "v11_3_beats_v11_2_brier":hold_new["brier"]<hold_v112["brier"],
            "all_match_accuracy_ge_60":hold_new_dir["accuracy"]>=.60,
            "strong_accuracy_ge_63":hold_strong["accuracy"] is not None and hold_strong["accuracy"]>=.63,
            "strong_coverage_ge_25":hold_strong.get("coverage",0)>=.25,
            "auto_activation":False,
        },
    }

    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    with Path(args.predictions).open("w",encoding="utf-8") as fh:
        for r in pred_rows:
            fh.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")

    print(json.dumps({
        "version":VERSION,"selected_feature_set":selected["feature_set"],"selected_l2":selected["l2"],
        "decision_threshold":decision_threshold,"strong_threshold":strong_thr,
        "holdout_v10_accuracy":hold_base["accuracy"],"holdout_v11_2_accuracy":hold_v112["accuracy"],
        "holdout_v11_3_accuracy_050":hold_new["accuracy"],"holdout_v11_3_directional_accuracy":hold_new_dir["accuracy"],
        "holdout_v11_3_brier":hold_new["brier"],"holdout_v11_3_logloss":hold_new["logloss"],
        "holdout_strong_accuracy":hold_strong["accuracy"],"holdout_strong_coverage":hold_strong["coverage"],
        "bootstrap_vs_v10":report["holdout"]["bootstrap_gain_probability_vs_v10"],"gate":report["gate"],
    },indent=2))


if __name__=="__main__":
    main()
