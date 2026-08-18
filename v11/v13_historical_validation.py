from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import calibration_baseball_v13 as calibration
from . import probability_contract_v13 as contract
from . import v13_posterior_policy as posterior_policy
from . import v13_train

BACKFILL = Path(os.getenv("V13_BACKFILL_FILE", "data/v13_historical_backfill.jsonl"))
OUT = Path(os.getenv("V13_HISTORICAL_VALIDATION_FILE", "data/v13_historical_validation.json"))
BLOCK_GAMES = int(os.getenv("V13_HISTORICAL_VALIDATION_BLOCK_GAMES", "50") or 50)


def _num(x: Any, d: float | None = None) -> float | None:
    try:
        y=float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _norm(x: Any) -> str:
    return "".join(c.lower() for c in str(x or "") if c.isalnum())


def _logloss(p: float, y: int) -> float:
    p=max(.001,min(.999,float(p)))
    return -(y*math.log(p)+(1-y)*math.log(1-p))


def _load(path: Path = BACKFILL) -> list[dict[str,Any]]:
    if not path.exists():
        return []
    out=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:r=json.loads(line)
        except Exception:continue
        if not isinstance(r,dict):continue
        if r.get("point_in_time") is not True or r.get("features_from_postgame") is True:continue
        if not contract.row_is_predictively_compatible(r):continue
        if r.get("validation_baseline_model_generation") != contract.MODEL_GENERATION_FINGERPRINT:continue
        out.append(r)
    return out


def _canonical_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    best={}
    for r in rows:
        key=(str(r.get("game_pk") or ""),str(r.get("phase") or "EARLY").upper())
        rank=str(r.get("analyzed_at") or "")
        if key not in best or rank>best[key][0]:best[key]=(rank,r)
    return sorted((x[1] for x in best.values()),key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or ""),str(r.get("phase") or "")))


def _canonical_option(row: dict[str,Any], market: str) -> dict[str,Any] | None:
    candidates=[o for o in row.get("options") or []
                if str(o.get("market") or "").upper()==market
                and o.get("result") in {"WIN","LOSS"}
                and o.get("p_replay_baseline_raw") is not None]
    if not candidates:return None
    marked=[o for o in candidates if o.get("is_canonical_line")]
    pool=marked or candidates
    home=_norm(row.get("home"))
    if market=="ML":
        return next((o for o in pool if _norm(o.get("name"))==home),pool[0])
    if market=="RUNLINE":
        homes=[o for o in pool if _norm(o.get("name"))==home]
        return min(homes or pool,key=lambda o:abs(abs(float(o.get("point") or 0))-1.5))
    overs=[o for o in pool if str(o.get("name") or "").lower()=="over"]
    return (overs or pool)[0]


def _empty_model() -> dict[str,Any]:
    return {"schema":"v13-baseball-calibration-model-v2","baseball_only":True,"calibrators":{},"status":"HISTORICAL_WALK_FORWARD_IDENTITY"}


def _training_model(prior_rows: list[dict[str,Any]]) -> dict[str,Any]:
    eligible=v13_train.eligible_exact_replay_rows(prior_rows)
    if not eligible:return _empty_model()
    return v13_train.enforce_strict_activation(calibration.build_model(eligible))


def _observation(row: dict[str,Any], opt: dict[str,Any], model: dict[str,Any], block: int,
                 train_games: int, prior_observations: list[dict[str,Any]]) -> dict[str,Any]:
    market=str(opt.get("market") or "").upper(); phase=str(row.get("phase") or "EARLY").upper()
    raw=float(opt["p_replay_baseline_raw"])
    baseball,source,n=calibration.calibrate(raw,market,phase,model)
    p_market=_num(opt.get("p_market"))
    learned=posterior_policy.prior_only_weight(prior_observations,market,phase)
    posterior_weight=max(0.0,min(1.0,float(learned.get("weight") or 0.0)))
    posterior=None if p_market is None else posterior_policy.blend(baseball,float(p_market),posterior_weight)
    return {
        "game_pk":row.get("game_pk"),"game_date":row.get("game_date"),"phase":phase,
        "market":market,"pick":opt.get("name"),"point":opt.get("point"),
        "settled_result":opt.get("result"),"p_raw":round(raw,6),
        "p_baseball_calibrated":round(baseball,6),
        "p_market":None if p_market is None else round(float(p_market),6),
        "p_posterior":None if posterior is None else round(posterior,6),
        "posterior_weight":round(posterior_weight,6),
        "posterior_weight_source":learned.get("source") or learned.get("status"),
        "posterior_weight_train_games":int(learned.get("games") or 0),
        "recorded_legacy_sharp_weight":round(max(0.0,min(1.0,_num(opt.get("sharp_weight"),0.0) or 0.0)),6),
        "calibration_source":source,"calibration_n":int(n),
        "evidence_origin":"exact-replay-blocked-walk-forward","validation_block":block,
        "training_games_before_block":train_games,
        "replay_probability_conditioning":opt.get("replay_probability_conditioning") or "WIN_GIVEN_NO_PUSH",
    }


def _score(rows: list[dict[str,Any]], field: str) -> dict[str,Any]:
    xs=[r for r in rows if _num(r.get(field)) is not None and r.get("settled_result") in {"WIN","LOSS"}]
    if not xs:return {"n":0,"unique_games":0,"brier":None,"logloss":None}
    vals=[]
    for r in xs:
        p=float(r[field]); y=1 if r["settled_result"]=="WIN" else 0
        vals.append((p,y))
    return {"n":len(vals),"unique_games":len({str(r.get("game_pk")) for r in xs}),
            "brier":round(sum((p-y)**2 for p,y in vals)/len(vals),6),
            "logloss":round(sum(_logloss(p,y) for p,y in vals)/len(vals),6)}


def _comparison(rows: list[dict[str,Any]]) -> dict[str,Any]:
    paired=[r for r in rows if _num(r.get("p_baseball_calibrated")) is not None and _num(r.get("p_posterior")) is not None]
    base=_score(paired,"p_baseball_calibrated"); post=_score(paired,"p_posterior"); sharp=_score(paired,"p_market")
    games=len({str(r.get("game_pk")) for r in paired})
    return {"n":len(paired),"unique_games":games,"baseball":base,"posterior":post,"sharp":sharp,
            "brier_improvement":None if not paired else round(base["brier"]-post["brier"],6),
            "logloss_improvement":None if not paired else round(base["logloss"]-post["logloss"],6)}


def _market_views(observations: list[dict[str,Any]], market: str) -> tuple[dict[str,Any],dict[str,Any],dict[str,Any]]:
    rows=[r for r in observations if r.get("market")==market]
    pooled=posterior_policy.latest_phase_per_game(rows)
    by_phase={phase:_comparison(posterior_policy.one_per_game_phase(rows,phase)) for phase in ("EARLY","LATE","FINAL")}
    all_phases=_comparison(rows)
    return _comparison(pooled),by_phase,all_phases


def build(path: Path = BACKFILL, out_path: Path = OUT) -> dict[str,Any]:
    rows=_canonical_rows(_load(path))
    by_game=defaultdict(list)
    for r in rows:by_game[str(r.get("game_pk") or "")].append(r)
    games=sorted(by_game,key=lambda gid:(str((by_game[gid][0] or {}).get("game_date") or ""),gid))
    observations=[]; prior_rows=[]
    for start in range(0,len(games),max(1,BLOCK_GAMES)):
        block_games=games[start:start+max(1,BLOCK_GAMES)]
        model=_training_model(prior_rows)
        block_index=start//max(1,BLOCK_GAMES)
        train_games=len({str(x.get("game_pk")) for x in prior_rows})
        # Freeze prior posterior observations before the block so no game in the
        # current block can influence another game's market weight.
        prior_observations=list(observations)
        for gid in block_games:
            for row in by_game[gid]:
                for market in ("ML","RUNLINE","TOTAL"):
                    opt=_canonical_option(row,market)
                    if opt is not None:
                        observations.append(_observation(row,opt,model,block_index,train_games,prior_observations))
        for gid in block_games:prior_rows.extend(by_game[gid])
    comparisons={};comparisons_by_phase={};all_phase_diagnostics={}
    for market in ("ML","RUNLINE","TOTAL"):
        pooled,by_phase,all_phases=_market_views(observations,market)
        comparisons[market]=pooled
        comparisons_by_phase[market]=by_phase
        all_phase_diagnostics[market]=all_phases
    report={
        "schema":"v13-historical-probability-validation-v2",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "model_generation":contract.MODEL_GENERATION_FINGERPRINT,
        "source":"exact archived pregame source replays",
        "block_games":max(1,BLOCK_GAMES),
        "canonical_games":len(games),"canonical_rows":len(rows),"observations":observations,
        # Backward-compatible top-level comparisons now mean one latest phase per
        # unique game, so n can no longer be inflated by EARLY/LATE/FINAL repeats.
        "comparisons":comparisons,
        "comparisons_by_phase":comparisons_by_phase,
        "comparisons_all_phase_observations_diagnostic_only":all_phase_diagnostics,
        "promotion_sample_unit":"unique game; pooled comparison keeps one latest pregame phase per game",
        "methodology":{
            "walk_forward":"blocked chronological by whole game; all phases of a game remain in the same holdout block so its final result can never train another phase of the same game",
            "baseball_probability":"p_replay_baseline_raw = P(WIN | no PUSH), then only calibration fitted on strictly earlier game blocks",
            "posterior":"Sharp blend weight is learned from strictly earlier out-of-sample game observations on a 0..100% grid; phase-specific evidence is preferred and pooled market evidence is fallback; insufficient evidence means 0% Sharp",
            "promotion_independence":"pooled promotion uses one latest phase per unique game; EARLY/LATE/FINAL are also reported separately and never summed as independent matches",
            "market_missing":"rows without a recorded historical sharp probability remain usable for baseball calibration but do not count toward posterior promotion evidence",
            "leakage":"current layered replay probabilities, final scores and future blocks are excluded from feature/calibration/market-weight generation",
        },
    }
    out_path.parent.mkdir(parents=True,exist_ok=True); out_path.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument("--input",default=str(BACKFILL));p.add_argument("--output",default=str(OUT));a=p.parse_args()
    print(json.dumps(build(Path(a.input),Path(a.output)),indent=2,sort_keys=True))


if __name__=="__main__":main()
