from __future__ import annotations

"""Inventory historical evidence without laundering legacy rows into V14.

The repository contains several useful evidence strata produced before the
current V14 model generation.  This module measures what is actually available,
audits strict pregame replay rows, and reports legacy market telemetry from the
retained archive branch when supplied by CI.

Nothing here can increment current-generation certification counters, activate a
calibrator, alter the champion, or authorize a bet.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID, VERSION
from .historical_dataset import load_verified, split_by_season

DEFAULT_REPLAY=Path("data/v13_historical_backfill.jsonl")
DEFAULT_REPLAY_REPORT=Path("data/v13_historical_backfill_report.json")
DEFAULT_RICH_REPORT=Path("data/mlb_backtest_2026_report.json")
DEFAULT_OUTPUT=Path("data/v14_legacy_evidence_inventory.json")


def _dt(value:Any)->datetime|None:
    if value in (None,""): return None
    try:
        out=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if out.tzinfo is None: out=out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:return None

def _load_json(path:Path|None)->dict[str,Any]:
    if path is None or not path.exists():return {}
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except Exception:return {}
    return value if isinstance(value,dict) else {}

def _iter_jsonl(path:Path|None)->Iterable[tuple[int,dict[str,Any]|None]]:
    if path is None or not path.exists():return
    with path.open("r",encoding="utf-8") as fh:
        for number,line in enumerate(fh,1):
            if not line.strip():continue
            try:value=json.loads(line)
            except Exception:
                yield number,None;continue
            yield number,value if isinstance(value,dict) else None

def _phase(row:dict[str,Any])->str:return str(row.get("phase") or row.get("observation_phase") or "UNKNOWN").upper()
def _generation(row:dict[str,Any])->str:
    contract=row.get("predictive_contract") or {}
    return str(row.get("model_generation") or row.get("model_generation_fingerprint") or contract.get("model_generation") or "UNKNOWN")
def _observation_at(row:dict[str,Any])->datetime|None:
    for key in ("observation_at","observed_at","analyzed_at","generated_at"):
        value=_dt(row.get(key))
        if value is not None:return value
    return None

def _game_date(row:dict[str,Any])->datetime|None:return _dt(row.get("game_date") or row.get("commence_time"))
def _settled(row:dict[str,Any])->bool:
    if row.get("result_status")=="SETTLED" or row.get("settled") is True:return True
    result=str(row.get("settled_result") or row.get("result") or "").upper()
    return result in {"WIN","LOSS","PUSH"}

def _replay_failures(row:dict[str,Any])->list[str]:
    failures=[]
    if not str(row.get("game_pk") or ""):failures.append("missing_game_pk")
    observed=_dt(row.get("analyzed_at"));game=_game_date(row)
    if observed is None or game is None:failures.append("missing_or_invalid_timestamp")
    elif observed>=game:failures.append("not_strictly_pregame")
    if row.get("point_in_time") is not True:failures.append("point_in_time_not_true")
    if row.get("features_from_postgame") is not False:failures.append("postgame_feature_boundary_not_explicit")
    if row.get("market_probability_used_as_baseball_feature") is not False:failures.append("market_feature_boundary_not_explicit")
    if not _settled(row):failures.append("not_settled")
    if not isinstance(row.get("options"),list) or not row.get("options"):failures.append("missing_options")
    return failures


def replay_inventory(path:Path=DEFAULT_REPLAY)->dict[str,Any]:
    rows=[];parse_errors=0;failure_counts=Counter()
    for _,row in _iter_jsonl(path):
        if row is None:parse_errors+=1;continue
        failures=_replay_failures(row)
        if failures:
            failure_counts.update(failures);continue
        rows.append(row)
    by_game:dict[str,list[dict[str,Any]]]=defaultdict(list)
    for row in rows:by_game[str(row["game_pk"])].append(row)
    independent=[]
    for game_rows in by_game.values():
        independent.append(max(game_rows,key=lambda r:(_dt(r.get("analyzed_at")) or datetime.min.replace(tzinfo=timezone.utc),_phase(r))))
    option_counts=Counter();sharp_paired=Counter();phases=Counter();generations=Counter()
    for row in rows:
        phases[_phase(row)]+=1;generations[_generation(row)]+=1
    for row in independent:
        for option in row.get("options") or []:
            market=str(option.get("market") or "UNKNOWN").upper();option_counts[market]+=1
            if option.get("p_market") is not None:sharp_paired[market]+=1
    return {"schema":"pulsar-v14-legacy-replay-inventory-v1","source":str(path),"source_exists":path.exists(),"valid_replay_rows":len(rows),"parse_errors":parse_errors,"invalid_rows":sum(failure_counts.values()),"failure_counts":dict(sorted(failure_counts.items())),"unique_games":len(by_game),"independent_latest_pregame_games":len(independent),"phase_rows":dict(sorted(phases.items())),"source_generations":dict(sorted(generations.items())),"independent_options_by_market":dict(sorted(option_counts.items())),"independent_sharp_paired_options_by_market":dict(sorted(sharp_paired.items())),"strict_pregame_contract":True,"exact_current_v14_replay_eligible":False,"exact_current_v14_replay_blocker":"committed artifact contains derived replay features/probabilities, not the complete raw source snapshot required by the current V14 input contract","research_use":"legacy feature-semantic parity, historical probability diagnostics and sharp comparison only"}


def market_tracking_inventory(path:Path|None)->dict[str,Any]:
    if path is None or not path.exists():return {"status":"UNAVAILABLE","source":str(path) if path else None}
    rows=0;parse_errors=0;settled=0;strict_pregame=0;game_ids=set();pregame_game_ids=set();markets=Counter();phases=Counter();generations=Counter();current_generation_rows=0
    for _,row in _iter_jsonl(path):
        if row is None:parse_errors+=1;continue
        states=row.get("options") if isinstance(row.get("options"),list) else [row]
        parent=row
        for state in states:
            if not isinstance(state,dict):continue
            merged={**parent,**state};rows+=1
            gid=str(merged.get("game_pk") or "")
            if gid:game_ids.add(gid)
            if _settled(merged):settled+=1
            market=str(merged.get("market") or "UNKNOWN").upper();markets[market]+=1
            phases[_phase(merged)]+=1;generation=_generation(merged);generations[generation]+=1
            if generation==MODEL_GENERATION:current_generation_rows+=1
            observed=_observation_at(merged);game=_game_date(merged)
            if observed is not None and game is not None and observed<game:
                strict_pregame+=1
                if gid:pregame_game_ids.add(gid)
    return {"status":"AVAILABLE","source":str(path),"expanded_rows":rows,"parse_errors":parse_errors,"settled_rows":settled,"unique_games":len(game_ids),"strictly_pregame_rows":strict_pregame,"strictly_pregame_unique_games":len(pregame_game_ids),"markets":dict(sorted(markets.items())),"phases":dict(sorted(phases.items())),"source_generations":dict(sorted(generations.items())),"current_v14_generation_rows":current_generation_rows,"certification_credit":0,"research_use":"legacy execution/market telemetry and data-quality diagnostics; generation-separated"}


def build(*,replay_path:Path=DEFAULT_REPLAY,replay_report_path:Path=DEFAULT_REPLAY_REPORT,rich_report_path:Path=DEFAULT_RICH_REPORT,market_report_path:Path|None=None,market_tracking_path:Path|None=None)->dict[str,Any]:
    pairs,dataset=load_verified();split=split_by_season(pairs);replay=replay_inventory(replay_path);replay_report=_load_json(replay_report_path);rich=_load_json(rich_report_path);market_report=_load_json(market_report_path);tracking=market_tracking_inventory(market_tracking_path)
    dataset_games=len(pairs);rich_games=int(rich.get("games") or 0);legacy_tracked=int(market_report.get("tracked_observations") or 0)
    return {"schema":"pulsar-v14-legacy-evidence-inventory-v1","generated_at":datetime.now(timezone.utc).isoformat(),"software_version":VERSION,"current_model_generation":MODEL_GENERATION,"current_probability_policy_id":PROBABILITY_POLICY_ID,"role":"RESEARCH_EVIDENCE_ONLY","research_only":True,"prospective":False,"certification_eligible":False,"champion_impact":False,"auto_activation":False,"current_certification_credit":{"games":0,"market_rows":0,"clv_rows":0,"reason":"legacy or reconstructed observations never satisfy exact current-generation prospective certification"},"tiers":{"strict_team_history":{"games":dataset_games,"split":{"tuning_2021_2024":len(split["tuning"]),"validation_2025":len(split["validation"]),"accumulating_holdout_2026":len(split["frozen_test"])},"integrity":dataset.get("integrity"),"audit":dataset.get("audit"),"use":"current V14 distribution/run research on strict PIT team-level inputs; advanced live-only features are unavailable historically"},"rich_2026_walk_forward":{"games":rich_games,"warm_games":int(rich.get("warm_games") or 0),"methodology":rich.get("methodology") or {},"use":"baseball-core ranking only; no historical odds/Statcast/weather in this reconstruction"},"exact_recorded_legacy_replays":{**replay,"reported_canonical_games":int(replay_report.get("canonical_games") or 0),"reported_source_replays":int(replay_report.get("source_replays") or 0)},"legacy_market_tracking":{"summary":market_report,"raw_inventory":tracking,"reported_tracked_observations":legacy_tracked,"use":"market and close diagnostics only; not current V14 probability evidence"}},"overlap_policy":"tiers overlap in games and must never be summed as independent observations","exact_current_v14_historical_replay":{"games":0,"status":"BLOCKED_BY_INCOMPLETE_RAW_HISTORICAL_INPUT_CONTRACT","reason":"older committed artifacts do not contain every raw source needed to reconstruct the current V14.5.4 live feature envelope exactly","safe_alternative":"use strict team-history holdouts for supported components, exact legacy replays for semantic diagnostics, and native V14 prospective rows as final authority"},"policy":{"legacy_generation_probabilities_never_relabelled_as_current":True,"historical_rows_never_feed_current_calibration":True,"historical_rows_never_feed_current_paper_clv":True,"native_v14_prospective_required_for_betting_certification":True}}


def write(output:Path|str=DEFAULT_OUTPUT,**kwargs:Any)->dict[str,Any]:
    artifact=build(**kwargs);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return artifact


def main()->None:
    parser=argparse.ArgumentParser(description="Inventory recoverable legacy MLB evidence without contaminating V14 certification")
    parser.add_argument("--replay",default=str(DEFAULT_REPLAY));parser.add_argument("--replay-report",default=str(DEFAULT_REPLAY_REPORT));parser.add_argument("--rich-report",default=str(DEFAULT_RICH_REPORT));parser.add_argument("--market-report");parser.add_argument("--market-tracking");parser.add_argument("--output",default=str(DEFAULT_OUTPUT));args=parser.parse_args()
    out=write(args.output,replay_path=Path(args.replay),replay_report_path=Path(args.replay_report),rich_report_path=Path(args.rich_report),market_report_path=Path(args.market_report) if args.market_report else None,market_tracking_path=Path(args.market_tracking) if args.market_tracking else None)
    print(json.dumps({"schema":out["schema"],"strict_team_history_games":out["tiers"]["strict_team_history"]["games"],"rich_2026_games":out["tiers"]["rich_2026_walk_forward"]["games"],"exact_replay_games":out["tiers"]["exact_recorded_legacy_replays"]["independent_latest_pregame_games"],"legacy_tracking_unique_games":((out["tiers"]["legacy_market_tracking"]["raw_inventory"] or {}).get("strictly_pregame_unique_games")),"current_certification_credit":out["current_certification_credit"]},sort_keys=True))


if __name__=="__main__":main()
