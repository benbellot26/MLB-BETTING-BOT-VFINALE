from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract

MODEL_FILE = Path("data/v13_distribution_prior.json")
EXACT_FILE = Path("data/v13_historical_backfill.jsonl")
SCHEMA = "v13-distribution-prior-v1"
MIN_EXACT_FINAL = 20


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out=float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _historical_candidate_ok(data: dict[str,Any]) -> bool:
    required=(
        data.get("schema")==SCHEMA,
        str(data.get("phase_scope") or "").upper()=="FINAL",
        str(data.get("variant") or "")=="dispersion_only",
        data.get("market_data_used") is False,
        data.get("historical_odds_used") is False,
        int(data.get("warm_games") or 0)>=1600,
        int(data.get("validation_games") or 0)>=300,
        int(data.get("test_games") or 0)>=300,
        int(data.get("exact_replay_games") or 0)>=20,
        float(data.get("validation_nll_gain") or 0)>0,
        float(data.get("test_nll_gain") or 0)>0,
        float(data.get("exact_replay_nll_gain") or 0)>=0,
        2.0 <= float(data.get("dispersion") or 0) <= 10.0,
        abs(float(data.get("environment_sigma") or 0)-.08) < 1e-12,
    )
    return all(required)


def _nb_nll(mu: float, y: int, dispersion: float) -> float:
    r=max(.5,_num(dispersion,7.5)); mu=max(.01,_num(mu,.01)); y=max(0,int(y))
    p=r/(r+mu)
    return -(math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p))


def _exact_rows(path: Path = EXACT_FILE) -> list[dict[str,Any]]:
    """Current-generation FINAL rows with baselines frozen before the distribution candidate."""
    if not path.exists(): return []
    best={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if str(row.get("phase") or "").upper() != "FINAL": continue
        if not contract.row_is_predictively_compatible(row): continue
        if row.get("validation_baseline_model_generation") != contract.MODEL_GENERATION_FINGERPRINT: continue
        if row.get("home_score") is None or row.get("away_score") is None: continue
        if row.get("validation_baseline_home_runs") is None or row.get("validation_baseline_away_runs") is None: continue
        if row.get("validation_baseline_dispersion") is None: continue
        key=str(row.get("game_pk") or ""); rank=str(row.get("analyzed_at") or "")
        if key and (key not in best or rank>best[key][0]): best[key]=(rank,row)
    return [x[1] for x in sorted(best.values(),key=lambda x:str(x[1].get("game_date") or ""))]


def _transfer_eval(rows: list[dict[str,Any]], candidate_dispersion: float) -> dict[str,Any]:
    base=[]; candidate=[]
    for row in rows:
        baseline_disp=_num(row.get("validation_baseline_dispersion"),0.0)
        if baseline_disp <= 0: continue
        for side in ("home","away"):
            mu=_num(row.get(f"validation_baseline_{side}_runs"),0.0)
            score=row.get(f"{side}_score")
            if mu <= 0 or score is None: continue
            base.append(_nb_nll(mu,int(score),baseline_disp))
            candidate.append(_nb_nll(mu,int(score),candidate_dispersion))
    n=len(base)
    baseline=sum(base)/n if n else None
    cand=sum(candidate)/n if n else None
    return {
        "games":len(rows),"team_observations":n,
        "baseline_nb_nll":baseline,"candidate_nb_nll":cand,
        "nll_gain":baseline-cand if baseline is not None and cand is not None else None,
        "baseline_source":"persisted pre-distribution-candidate dispersion",
    }


def rebuild_transfer(path: Path = MODEL_FILE, exact_path: Path = EXACT_FILE) -> dict[str,Any]:
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema":SCHEMA,"active":False,"status":"ABSENT_OR_INVALID","error":type(exc).__name__}
    historical_ok=_historical_candidate_ok(data)
    rows=_exact_rows(exact_path)
    transfer=_transfer_eval(rows,_num(data.get("dispersion"),0.0))
    ready=len(rows)>=MIN_EXACT_FINAL
    passed=bool(ready and transfer.get("nll_gain") is not None and float(transfer["nll_gain"])>0)
    status="PASS_FINAL_ONLY" if passed else "FAIL_FINAL_ONLY" if ready else "COLLECTING_FINAL_ONLY"
    data.update({
        "historical_candidate_active":bool(historical_ok),
        "model_generation":contract.MODEL_GENERATION_FINGERPRINT,
        "exact_final_games":len(rows),
        "exact_transfer_required_games":MIN_EXACT_FINAL,
        "exact_transfer_status":status,
        "current_generation_transfer":transfer,
        "active":bool(historical_ok and passed),
        "activation_rule":"historical validation/test candidate must remain valid AND >=20 current-generation genuine FINAL replays, evaluated from a persisted pre-candidate dispersion baseline, must improve NB NLL",
        "transfer_caveat":"The historical dispersion is a candidate until it independently transfers to the exact current predictive generation.",
        "generation_gate":True,
        "independent_pre_candidate_baseline_required":True,
    })
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    return data


def load(path: Path = MODEL_FILE) -> dict[str, Any]:
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema":SCHEMA,"active":False,"status":"ABSENT_OR_INVALID","error":type(exc).__name__}
    historical_ok=_historical_candidate_ok(data)
    generation_ok=data.get("model_generation")==contract.MODEL_GENERATION_FINGERPRINT
    transfer_ok=(int(data.get("exact_final_games") or 0)>=int(data.get("exact_transfer_required_games") or MIN_EXACT_FINAL)
                 and data.get("exact_transfer_status")=="PASS_FINAL_ONLY")
    if not historical_ok:
        data["active"]=False; data["status"]="HISTORICAL_EVIDENCE_GATE_FAIL"; return data
    if not generation_ok:
        data["active"]=False; data["status"]="CURRENT_GENERATION_TRANSFER_REQUIRED"; return data
    if not transfer_ok:
        data["active"]=False; data["status"]="CURRENT_GENERATION_TRANSFER_COLLECTING"; return data
    if data.get("active") is not True:
        data["status"]="CURRENT_GENERATION_TRANSFER_NOT_ACTIVE"; return data
    data["status"]="ACTIVE_VALIDATED_CURRENT_GENERATION_FINAL_ONLY"
    return data


def apply(dispersion: float, env_sigma: float, phase: str, path: Path = MODEL_FILE) -> tuple[float,float,dict[str,Any]]:
    model=load(path)
    if str(phase or "").upper()!="FINAL" or not model.get("active"):
        return dispersion,env_sigma,{"active":False,"source":"none","status":model.get("status"),
                                    "model_generation":model.get("model_generation"),
                                    "expected_model_generation":contract.MODEL_GENERATION_FINGERPRINT,
                                    "exact_transfer_games":model.get("exact_final_games"),
                                    "exact_transfer_required_games":model.get("exact_transfer_required_games",MIN_EXACT_FINAL)}
    return float(model["dispersion"]),float(model["environment_sigma"]),{
        "active":True,
        "source":"v13-validated-historical-distribution",
        "variant":model.get("variant"),
        "warm_games":model.get("warm_games"),
        "validation_nll_gain":model.get("validation_nll_gain"),
        "test_nll_gain":model.get("test_nll_gain"),
        "current_generation_nll_gain":((model.get("current_generation_transfer") or {}).get("nll_gain")),
        "model_generation":model.get("model_generation"),
        "exact_transfer_games":model.get("exact_final_games"),
        "exact_transfer_status":model.get("exact_transfer_status"),
    }


def main() -> None:
    print(json.dumps(rebuild_transfer(),ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == "__main__":
    main()
