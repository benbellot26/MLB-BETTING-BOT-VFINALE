from __future__ import annotations

"""Bootstrap calibration-uncertainty challenger from settled V14 predictions.

This does not claim Bayesian/event-level credible intervals. It estimates the
uncertainty of calibration bias inside probability buckets using persisted,
settled prospective observations. It is research-only and cannot auto-activate.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .paired_inference import bootstrap_mean_ci
from .snapshot_policy import select_canonical

PREDICTIONS = Path("data/v14_predictions.jsonl")
OUTPUT = Path("data/v14_bootstrap_uncertainty_candidate.json")
MIN_MARKET_N = 400
MIN_BUCKET_N = 80
BUCKET_WIDTH = .10
MARKETS = {
    "ML": "home_ml",
    "RL_HOME_-1.5": "home_minus_1_5",
    "RL_AWAY_-1.5": "away_minus_1_5",
    "TOTAL_OVER": "over",
}


def _num(value: Any) -> float | None:
    try: out = float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _read(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists(): return []
    out=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if isinstance(row,dict): out.append(row)
    return out


def _outcome(row: dict[str, Any], market: str) -> int | None:
    if not row.get("settled"): return None
    h=_num(row.get("home_score")); a=_num(row.get("away_score"))
    if h is None or a is None: return None
    if market=="ML": return int(h>a)
    if market=="RL_HOME_-1.5": return int(h-a>=2)
    if market=="RL_AWAY_-1.5": return int(a-h>=2)
    line=_num(row.get("total_line"))
    if line is None or abs((h+a)-line)<1e-9: return None
    return int(h+a>line)


def _bucket(p: float) -> float:
    return min(.9, max(0.0, math.floor(float(p)/BUCKET_WIDTH)*BUCKET_WIDTH))


def _market(rows: list[dict[str, Any]], market: str, selection: str, phase: str) -> dict[str, Any]:
    buckets: dict[float,list[float]] = {}
    n=0
    for row in rows:
        y=_outcome(row,market); p=_num((row.get("probabilities") or {}).get(selection))
        if y is None or p is None: continue
        n+=1; buckets.setdefault(_bucket(p),[]).append(float(y)-p)
    cells=[]; ready_cells=0
    for low in sorted(buckets):
        residuals=buckets[low]; ci=bootstrap_mean_ci(residuals,label=f"uncertainty:{phase}:{market}:{low:.1f}")
        ready=len(residuals)>=MIN_BUCKET_N
        if ready: ready_cells+=1
        cells.append({
            "lower":low,"upper":min(1.0,low+BUCKET_WIDTH),"n":len(residuals),"ready":ready,
            "mean_calibration_bias":ci.get("mean"),"bias_ci95_lower":ci.get("ci95_lower"),"bias_ci95_upper":ci.get("ci95_upper"),
            "bootstrap_reps":ci.get("reps"),
        })
    return {
        "n":n,"status":"VALIDATION_READY" if n>=MIN_MARKET_N and ready_cells else "COLLECTING",
        "min_market_n":MIN_MARKET_N,"min_bucket_n":MIN_BUCKET_N,"ready_cells":ready_cells,"cells":cells,
    }


def build(path: Path | str = PREDICTIONS) -> dict[str, Any]:
    rows=[r for r in _read(path) if r.get("settled")]; selected=select_canonical(rows); phases={}
    for phase in ("EARLY","LATE","FINAL"):
        phase_rows=[by_phase[phase] for by_phase in selected.values() if phase in by_phase]
        phases[phase]={market:_market(phase_rows,market,selection,phase) for market,selection in MARKETS.items()}
    return {
        "schema":"pulsar-v14-bootstrap-uncertainty-challenger-v1","generated_at":datetime.now(timezone.utc).isoformat(),
        "role":"CHALLENGER_ONLY","auto_activation":False,"champion_impact":False,"network_calls":0,
        "claim":"bootstrap confidence interval for bucket-level calibration bias; not an event-level Bayesian credible interval",
        "snapshot_policy":"canonical observed phases only","phases":phases,
    }


def write(predictions: Path | str=PREDICTIONS, output: Path | str=OUTPUT) -> dict[str,Any]:
    out=build(predictions); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out


def main()->None:
    parser=argparse.ArgumentParser(description="Build research-only bootstrap uncertainty challenger"); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(OUTPUT)); args=parser.parse_args(); out=write(args.predictions,args.output)
    print(json.dumps({"schema":out["schema"],"role":out["role"],"network_calls":0},sort_keys=True))


if __name__=="__main__": main()
