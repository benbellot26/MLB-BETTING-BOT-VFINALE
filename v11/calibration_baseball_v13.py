from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .probability_contract_v13 import clip_probability

MODEL_FILE = Path(os.getenv("V13_BASEBALL_CALIBRATION_FILE", "data/v13_baseball_calibration.json"))
MIN_GLOBAL = int(os.getenv("V13_CAL_MIN_GLOBAL", "300") or 300)
MIN_MARKET = int(os.getenv("V13_CAL_MIN_MARKET", "180") or 180)
MIN_PHASE = int(os.getenv("V13_CAL_MIN_PHASE", "140") or 140)
HOLDOUT_MIN = int(os.getenv("V13_CAL_HOLDOUT_MIN", "80") or 80)
MAX_ECE_REGRESSION = float(os.getenv("V13_CAL_MAX_ECE_REGRESSION", "0.002") or .002)
MIN_WF_WINDOWS = int(os.getenv("V13_CAL_MIN_WF_WINDOWS", "3") or 3)
MIN_WF_PASS_RATE = float(os.getenv("V13_CAL_MIN_WF_PASS_RATE", "0.67") or .67)
RELIABILITY_EDGES = (0.0, .40, .45, .50, .55, .60, .65, .70, 1.001)


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _logit(p: float) -> float:
    p = clip_probability(p)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def _binary_metrics(examples: list[tuple[float, int]]) -> dict[str, Any]:
    if not examples:
        return {"n": 0, "brier": None, "logloss": None, "ece": None, "slope": None, "intercept": None}
    n = len(examples)
    brier = sum((p-y)**2 for p, y in examples) / n
    logloss = sum(-(y*math.log(max(.001, p)) + (1-y)*math.log(max(.001, 1-p))) for p, y in examples) / n
    ece = 0.0
    for lo, hi in zip(RELIABILITY_EDGES[:-1], RELIABILITY_EDGES[1:]):
        z = [(p,y) for p,y in examples if lo <= p < hi]
        if z:
            ece += len(z)/n * abs(sum(p for p,_ in z)/len(z) - sum(y for _,y in z)/len(z))
    intercept = slope = None
    if n >= 40 and 0 < sum(y for _,y in examples) < n:
        intercept, slope = _fit_platt(examples)
    return {"n": n, "brier": brier, "logloss": logloss, "ece": ece, "intercept": intercept, "slope": slope}


def _reliability_bins(examples: list[tuple[float,int]]) -> list[dict[str,Any]]:
    bins=[]
    for lo,hi in zip(RELIABILITY_EDGES[:-1], RELIABILITY_EDGES[1:]):
        z=[(p,y) for p,y in examples if lo <= p < hi]
        if not z:
            continue
        n=len(z); avgp=sum(p for p,_ in z)/n; hit=sum(y for _,y in z)/n
        gap=abs(hit-avgp)
        se=math.sqrt(max(.01,hit*(1-hit))/n)
        # This is an empirical reliability uncertainty, not outcome variance.
        # Small bins stay wide; persistent miscalibration also widens the band.
        sigma=max(.02,min(.14,gap+se))
        bins.append({"lo":lo,"hi":hi,"n":n,"avg_probability":avgp,"hit_rate":hit,
                     "calibration_gap":gap,"sampling_se":se,"sigma":sigma})
    return bins


def _fit_platt(examples: list[tuple[float,int]], iterations: int = 1200, lr: float = .02, l2: float = .025) -> tuple[float, float]:
    a, b = 0.0, 1.0
    n = max(1, len(examples))
    for _ in range(iterations):
        ga = gb = 0.0
        for p, y in examples:
            x = _logit(p); q = _sigmoid(a + b*x); e = q-y
            ga += e; gb += e*x
        a -= lr*(ga/n + l2*a); b -= lr*(gb/n + l2*(b-1.0))
        a = max(-5.0, min(5.0, a)); b = max(.05, min(5.0, b))
    return a, b


def _fit_beta(examples: list[tuple[float, int]], iterations: int = 1500, lr: float = .015, l2: float = .03) -> dict[str, float]:
    c, a, b = 0.0, 1.0, 1.0
    n = max(1, len(examples))
    for _ in range(iterations):
        gc = ga = gb = 0.0
        for p, y in examples:
            p = clip_probability(p); x1, x2 = math.log(p), -math.log(1-p)
            q = _sigmoid(c+a*x1+b*x2); e = q-y
            gc += e; ga += e*x1; gb += e*x2
        c -= lr*(gc/n+l2*c); a -= lr*(ga/n+l2*(a-1.0)); b -= lr*(gb/n+l2*(b-1.0))
        c = max(-5.0, min(5.0, c)); a = max(.05, min(5.0, a)); b = max(.05, min(5.0, b))
    return {"method": "beta", "c": c, "a": a, "b": b}


def _params(method: str, train: list[tuple[float,int]]) -> dict[str,Any]:
    if method == "platt":
        a,b=_fit_platt(train); return {"method":"platt","a":a,"b":b}
    if method == "beta":
        return _fit_beta(train)
    return {"method":"identity"}


def _apply(params: dict[str, Any], p: float) -> float:
    p = clip_probability(p)
    method = str(params.get("method") or "identity")
    if method == "platt":
        return clip_probability(_sigmoid(_num(params.get("a")) + _num(params.get("b"), 1.0)*_logit(p)))
    if method == "beta":
        z = _num(params.get("c")) + _num(params.get("a"),1.0)*math.log(p) + _num(params.get("b"),1.0)*(-math.log(1-p))
        return clip_probability(_sigmoid(z))
    return p


def _candidate(method: str, train: list[tuple[float,int]], hold: list[tuple[float,int]]) -> dict[str, Any]:
    params = _params(method, train)
    transformed = [(_apply(params,p),y) for p,y in hold]
    metrics = _binary_metrics(transformed)
    return {"params": params, "metrics": metrics}


def _gain(candidate: dict[str,Any], baseline: dict[str,Any]) -> dict[str,Any]:
    m=candidate.get("metrics") or {}
    gain_b=_num(baseline.get("brier"),9)-_num(m.get("brier"),9)
    gain_l=_num(baseline.get("logloss"),9)-_num(m.get("logloss"),9)
    ece_ok=_num(m.get("ece"),9) <= _num(baseline.get("ece"),9)+MAX_ECE_REGRESSION
    return {"brier_gain":gain_b,"logloss_gain":gain_l,"ece_ok":ece_ok,
            "passes":gain_b>0 and gain_l>=0 and ece_ok}


def _walk_forward(method: str, discovery: list[tuple[float,int]], minimum: int) -> dict[str,Any]:
    windows=[]
    n=len(discovery)
    for frac in (.50,.62,.74,.84):
        cut=int(n*frac)
        width=max(24,int(n*.12))
        end=min(n,cut+width)
        if cut < max(40, minimum//2) or end-cut < 20:
            continue
        train=discovery[:cut]; hold=discovery[cut:end]
        if len({y for _,y in train})<2 or len({y for _,y in hold})<2:
            continue
        baseline=_binary_metrics(hold)
        cand=_candidate(method,train,hold)
        g=_gain(cand,baseline)
        windows.append({"train_n":len(train),"holdout_n":len(hold),"baseline":baseline,
                        "candidate":cand["metrics"],**g})
    rate=sum(1 for w in windows if w["passes"])/len(windows) if windows else 0.0
    avg_b=sum(_num(w.get("brier_gain")) for w in windows)/len(windows) if windows else -9.0
    avg_l=sum(_num(w.get("logloss_gain")) for w in windows)/len(windows) if windows else -9.0
    return {"windows":windows,"pass_rate":rate,"avg_brier_gain":avg_b,"avg_logloss_gain":avg_l,
            "passes":len(windows)>=MIN_WF_WINDOWS and rate>=MIN_WF_PASS_RATE and avg_b>0 and avg_l>=0}


def fit_calibrator(examples: list[tuple[float,int]], minimum: int) -> dict[str, Any]:
    examples = [(clip_probability(p), int(bool(y))) for p,y in examples]
    out = {"active": False, "method": "identity", "n": len(examples), "status": "COLLECTING",
           "reliability_bins": _reliability_bins(examples)}
    if len(examples) < minimum + HOLDOUT_MIN:
        return out
    final_n=max(HOLDOUT_MIN,int(len(examples)*.20))
    discovery, final_hold = examples[:-final_n], examples[-final_n:]
    if len(discovery) < minimum or len({y for _,y in discovery})<2 or len({y for _,y in final_hold})<2:
        out["status"]="COLLECTING_CLASSES"; return out

    wf={m:_walk_forward(m,discovery,minimum) for m in ("platt","beta")}
    stable=[m for m in ("platt","beta") if wf[m].get("passes")]
    baseline=_binary_metrics(final_hold)
    candidates={"identity":{"params":{"method":"identity"},"metrics":baseline}}
    for method in stable:
        cand=_candidate(method,discovery,final_hold)
        cand.update(_gain(cand,baseline)); candidates[method]=cand
    eligible=[(m,c) for m,c in candidates.items() if m!="identity" and c.get("passes")]
    if eligible:
        name,best=min(eligible,key=lambda x:(_num(x[1]["metrics"].get("brier"),9),_num(x[1]["metrics"].get("logloss"),9)))
        out.update(best["params"]); out.update({"active":True,"method":name,"status":"PASS_NESTED_WALK_FORWARD"})
    else:
        out.update({"active":False,"method":"identity","status":"IDENTITY_BEST_OR_UNSTABLE"})
    out.update({"discovery_n":len(discovery),"final_holdout_n":len(final_hold),"baseline":baseline,
                "walk_forward":wf,"candidates":candidates,
                "validation_protocol":"train-only expanding walk-forward selects method; untouched chronological final holdout decides activation"})
    return out


def _option_probability(opt: dict[str,Any]) -> float | None:
    for key in ("p_baseball_raw", "p_learned", "p_structural"):
        if opt.get(key) is not None:
            return clip_probability(opt.get(key))
    return None


def examples_from_rows(rows: list[dict[str,Any]]) -> dict[str, list[tuple[float,int]]]:
    """Build independent calibration buckets.

    Phase buckets keep one forecast per game/phase/market. Market buckets keep
    only one forecast per game/market, using the latest pregame phase available,
    so repeated EARLY/LATE/FINAL snapshots cannot inflate effective sample size.
    GLOBAL is retained for diagnostics only and is never a runtime fallback.
    """
    buckets: dict[str,list[tuple[float,int]]] = {"GLOBAL":[]}
    phase_seen: set[tuple[str,str,str]] = set()
    latest_market: dict[tuple[str,str], tuple[str,tuple[float,int]]] = {}
    for row in sorted(rows, key=lambda r: (str(r.get("game_date") or ""), str(r.get("analyzed_at") or ""))):
        phase = str(row.get("phase") or "EARLY").upper(); game_pk = str(row.get("game_pk") or "")
        rank = str(row.get("analyzed_at") or "")
        for opt in row.get("options") or []:
            result = opt.get("result")
            if result not in {"WIN","LOSS"}: continue
            p = _option_probability(opt)
            if p is None: continue
            market = str(opt.get("market") or "").upper()
            ex = (p, 1 if result == "WIN" else 0)
            phase_key = (game_pk, phase, market)
            if phase_key not in phase_seen:
                phase_seen.add(phase_key)
                buckets.setdefault(f"PHASE:{phase}:{market}", []).append(ex)
            market_key = (game_pk, market)
            if market_key not in latest_market or rank > latest_market[market_key][0]:
                latest_market[market_key] = (rank, ex)
    for (_, market), (_, ex) in latest_market.items():
        buckets.setdefault(f"MARKET:{market}", []).append(ex)
        buckets.setdefault("GLOBAL", []).append(ex)
    return buckets


def build_model(rows: list[dict[str,Any]]) -> dict[str,Any]:
    buckets = examples_from_rows(rows); calibrators: dict[str,Any] = {}
    for key, examples in buckets.items():
        minimum = MIN_GLOBAL if key == "GLOBAL" else MIN_PHASE if key.startswith("PHASE:") else MIN_MARKET
        calibrators[key] = fit_calibrator(examples, minimum)
    return {"schema":"v13-baseball-calibration-model-v2","generated_at":datetime.now(timezone.utc).isoformat(),"baseball_only":True,
            "market_probability_used_as_feature":False,"calibrators":calibrators,"rows_seen":len(rows),
            "runtime_global_fallback_allowed":False}


def save_model(model: dict[str,Any], path: Path = MODEL_FILE) -> dict[str,Any]:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"); return model


def load_model(path: Path = MODEL_FILE) -> dict[str,Any]:
    if not path.exists():
        return {"schema":"v13-baseball-calibration-model-v2","calibrators":{},"status":"ABSENT","baseball_only":True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") not in {"v13-baseball-calibration-model-v1","v13-baseball-calibration-model-v2"} or data.get("baseball_only") is not True:
            return {"schema":"v13-baseball-calibration-model-v2","calibrators":{},"status":"INCOMPATIBLE","baseball_only":True}
        return data
    except Exception as exc:
        return {"schema":"v13-baseball-calibration-model-v2","calibrators":{},"status":"INVALID","error":type(exc).__name__,"baseball_only":True}


def evidence_counts(model: dict[str,Any], market: str, phase: str) -> dict[str,int]:
    cals = model.get("calibrators") or {}
    phase_key=f"PHASE:{phase.upper()}:{market.upper()}"; market_key=f"MARKET:{market.upper()}"
    return {"phase_n":int((cals.get(phase_key) or {}).get("n") or 0),
            "market_n":int((cals.get(market_key) or {}).get("n") or 0),
            "global_n":int((cals.get("GLOBAL") or {}).get("n") or 0)}


def choose_calibrator(model: dict[str,Any], market: str, phase: str) -> tuple[dict[str,Any], str]:
    cals = model.get("calibrators") or {}
    phase_key=f"PHASE:{phase.upper()}:{market.upper()}"; market_key=f"MARKET:{market.upper()}"
    counts = evidence_counts(model, market, phase)
    # Never calibrate one market from another market's GLOBAL bucket.
    for key in (phase_key, market_key):
        cal = cals.get(key) or {}
        if cal.get("active"):
            out=dict(cal); out.update(counts); return out,key
    evidence_n = counts["phase_n"] if counts["phase_n"] > 0 else counts["market_n"]
    return {"active":False,"method":"identity","n":evidence_n,**counts}, "identity"


def reliability_sigma(model: dict[str,Any], market: str, phase: str, p: float) -> tuple[float | None,str]:
    cals=model.get("calibrators") or {}
    for key in (f"PHASE:{phase.upper()}:{market.upper()}",f"MARKET:{market.upper()}"):
        bins=(cals.get(key) or {}).get("reliability_bins") or []
        for b in bins:
            if _num(b.get("lo")) <= p < _num(b.get("hi"),1.001):
                return _num(b.get("sigma"),0.0) or None,key
    return None,"none"


def calibrate(p: float, market: str, phase: str, model: dict[str,Any] | None = None) -> tuple[float,str,int]:
    model = load_model() if model is None else model
    cal, source = choose_calibrator(model, market, phase)
    return _apply(cal,p), source, int(cal.get("n") or 0)
