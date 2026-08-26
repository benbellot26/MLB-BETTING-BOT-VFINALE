from __future__ import annotations

"""Prospective native-live gate for the frozen historical distribution candidate.

Only a distribution shadow that was actually persisted in the prediction before
first pitch can contribute.  The validator never turns an old champion-only row
into prospective evidence by recomputing the challenger after settlement.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION
from .acquisition import parse_time
from .distribution_tuning import _evaluate, _paired, _public
from .historical_distribution_shadow import load as load_candidate
from .tracking import _read_jsonl

PREDICTIONS=Path("data/v14_predictions.jsonl")
OUTPUT=Path("data/v14_distribution_live_validation.json")
MIN_PROSPECTIVE_GAMES=200


def _dt(value:Any)->datetime:
    out=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _shadow(row:dict[str,Any])->dict[str,Any]:
    return (((row.get("training_features") or {}).get("research_challengers") or {}).get("historical_distribution_shadow") or {})


def _strictly_pregame(row:dict[str,Any])->bool:
    try:return parse_time(row.get("analyzed_at"))<parse_time(row.get("game_date"))
    except Exception:return False


def _params_match(left:dict[str,Any],right:dict[str,Any])->bool:
    try:
        return abs(float(left.get("dispersion"))-float(right.get("dispersion")))<1e-12 and abs(float(left.get("environment_sigma"))-float(right.get("environment_sigma")))<1e-12
    except Exception:return False


def _prospective_rows(rows:list[dict[str,Any]],evidence:dict[str,Any])->list[dict[str,Any]]:
    try:freeze=_dt(evidence.get("frozen_at"))
    except Exception:return []
    source_run_id=evidence.get("source_run_id");dataset_hash=((evidence.get("dataset") or {}).get("dataset_content_sha256"));params=evidence.get("candidate_parameters") or {};latest={}
    for row in rows:
        if row.get("model_generation")!=MODEL_GENERATION or row.get("settled") is not True or not _strictly_pregame(row):continue
        try:analyzed=_dt(row.get("analyzed_at"))
        except Exception:continue
        if analyzed<=freeze:continue
        shadow=_shadow(row)
        if shadow.get("status")!="READY_SHADOW":continue
        if shadow.get("evidence_run_id")!=source_run_id:continue
        if shadow.get("dataset_content_sha256")!=dataset_hash:continue
        if not _params_match(shadow.get("candidate_parameters") or {},params):continue
        if not isinstance(shadow.get("candidate_probabilities"),dict):continue
        if row.get("home_mu") is None or row.get("away_mu") is None or row.get("total_line") is None:continue
        gid=str(row.get("game_pk") or "")
        if not gid:continue
        previous=latest.get(gid)
        if previous is None or _dt(previous.get("analyzed_at"))<analyzed:latest[gid]=row
    return sorted(latest.values(),key=lambda r:(_dt(r.get("game_date")),_dt(r.get("analyzed_at")),str(r.get("game_pk") or "")))


def build(rows:list[dict[str,Any]],artifact:dict[str,Any]|None=None)->dict[str,Any]:
    evidence=load_candidate() if artifact is None else artifact
    base={"schema":"pulsar-v14-historical-distribution-live-validation-v2","role":"PROMOTION_EVIDENCE_ONLY","auto_activation":False,"champion_impact":False,"minimum_prospective_games":MIN_PROSPECTIVE_GAMES,"evidence_contract":"persisted READY_SHADOW before first pitch; exact source run, dataset hash and frozen parameters"}
    if not evidence:return {**base,"status":"COLLECTING","reason":"frozen historical distribution artifact unavailable","games":0}
    frozen_at=evidence.get("frozen_at")
    if not frozen_at:return {**base,"status":"COLLECTING","reason":"frozen_at missing","games":0}
    selected=_prospective_rows(rows,evidence);params=evidence.get("candidate_parameters") or {};champ=evidence.get("champion_parameters") or {}
    if len(selected)<MIN_PROSPECTIVE_GAMES:
        return {**base,"status":"COLLECTING","games":len(selected),"frozen_at":frozen_at,"candidate_source_run_id":evidence.get("source_run_id"),"dataset_content_sha256":((evidence.get("dataset") or {}).get("dataset_content_sha256")),"candidate_parameters":params,"reason":"insufficient persisted strictly prospective settled shadow games"}
    candidate=_evaluate(selected,float(params["dispersion"]),float(params["environment_sigma"]));champion=_evaluate(selected,float(champ["dispersion"]),float(champ["environment_sigma"]));paired=_paired(candidate,champion);score=paired.get("score_nll_gain") or {}
    market_nonreg=True
    for market in (paired.get("markets") or {}).values():
        b=market.get("brier_gain") or {};l=market.get("logloss_gain") or {}
        if int(b.get("n") or 0)<MIN_PROSPECTIVE_GAMES or b.get("ci95_lower") is None or float(b["ci95_lower"])<-.0015:market_nonreg=False
        if int(l.get("n") or 0)<MIN_PROSPECTIVE_GAMES or l.get("ci95_lower") is None or float(l["ci95_lower"])<-.003:market_nonreg=False
    passes=bool(int(score.get("n") or 0)>=MIN_PROSPECTIVE_GAMES and score.get("ci95_lower") is not None and float(score["ci95_lower"])>0 and market_nonreg)
    return {**base,"status":"PROMOTION_REVIEW" if passes else "REJECTED_NATIVE_LIVE","passes":passes,"games":len(selected),"frozen_at":frozen_at,"candidate_source_run_id":evidence.get("source_run_id"),"dataset_content_sha256":((evidence.get("dataset") or {}).get("dataset_content_sha256")),"candidate_parameters":params,"champion_parameters":champ,"candidate":_public(candidate),"champion":_public(champion),"paired":paired,"market_nonregression":market_nonreg,"promotion_gate":"persisted post-freeze native-live n>=200; paired score-NLL CI95 lower >0; each market Brier CI95 >= -0.0015 and LogLoss CI95 >= -0.003","note":"PROMOTION_REVIEW is not automatic activation; champion change remains deliberate and versioned."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=OUTPUT)->dict[str,Any]:
    artifact=build(_read_jsonl(predictions));target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return artifact


def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("--predictions",default=str(PREDICTIONS));parser.add_argument("--output",default=str(OUTPUT));args=parser.parse_args();out=write(args.predictions,args.output);print(f"PULSAR_V14_HISTORICAL_DISTRIBUTION_LIVE status={out.get('status')} games={out.get('games')}")


if __name__=="__main__":main()
