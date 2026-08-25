from __future__ import annotations

"""Native end-to-end candidate builder for Pulsar V14."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, VERSION
from .acquisition import PregameSnapshot, collect_pregame
from .market_edge import diagnostics_from_snapshot
from .market_lines import canonical_market_snapshot, choose_total_line
from .mlb_inputs import NativeGameInputs, build_game_inputs
from .phase import infer_phase
from .pipeline import predict_from_structural

NATIVE_CANDIDATE = Path("runtime/v14/native_candidate.json")
Collector = Callable[..., PregameSnapshot]
InputBuilder = Callable[..., NativeGameInputs]


def _phase_quality_gate(native: NativeGameInputs, phase: str) -> None:
    quality = native.feature_row.get("data_quality") or {}
    if phase in {"LATE", "FINAL"} and quality.get("starter_complete") is not True:
        raise ValueError(f"{phase} snapshot requires both announced starting pitchers")
    if phase == "FINAL":
        home_count = int(quality.get("home_lineup_count") or 0)
        away_count = int(quality.get("away_lineup_count") or 0)
        if home_count < 9 or away_count < 9:
            raise ValueError("FINAL snapshot requires both confirmed 9/9 lineups")


def build_native_result(game: dict[str, Any], event: dict[str, Any], *, target_date: str, analyzed_at: str, input_builder: InputBuilder=build_game_inputs) -> dict[str, Any]:
    native=input_builder(game,target_date=target_date,analyzed_at=analyzed_at)
    line_meta=choose_total_line(event,as_of=analyzed_at)
    phase=infer_phase(analyzed_at=analyzed_at,game_date=native.structural.game_date,context=native.context)
    _phase_quality_gate(native,phase)
    feature_row=dict(native.feature_row); feature_row["phase"]=phase
    prediction=predict_from_structural(native.structural,analyzed_at=analyzed_at,home=native.home,away=native.away,total_line=float(line_meta["line"]),feature_row=feature_row,phase=phase)
    market_snapshot=canonical_market_snapshot(event,total_line=float(line_meta["line"]),as_of=analyzed_at)
    market_diagnostics=diagnostics_from_snapshot(prediction,market_snapshot)
    return {
        "game_pk":native.structural.game_pk,"game_date":native.structural.game_date,"analyzed_at":analyzed_at,"phase":phase,"home":native.home,"away":native.away,"ctx":native.context,
        "canonical_lines":{"TOTAL":float(line_meta["line"])},"line_selection":line_meta,"market_snapshot":market_snapshot,"market_diagnostics":market_diagnostics,
        "native_structural":{"game_pk":native.structural.game_pk,"game_date":native.structural.game_date,"venue":native.structural.venue,"structural_home_mu":native.structural.structural_home_mu,"structural_away_mu":native.structural.structural_away_mu,"static_park_factor":native.structural.static_park_factor,"debug":native.structural_debug},
        "v14_prediction":prediction,"model_generation":MODEL_GENERATION,"market_probability_used_as_feature":False,
    }


def build_candidate(target_date: str, *, analyzed_at: str|None=None, api_key: str|None=None, collector: Collector=collect_pregame, input_builder: InputBuilder=build_game_inputs) -> dict[str,Any]:
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); snapshot=collector(target_date,analyzed_at=at,api_key=api_key); results=[]; skipped=[]
    for game in snapshot.games:
        game_pk=str(game.get("gamePk") or ""); event=snapshot.matches.get(game_pk)
        if event is None:
            skipped.append({"game_pk":game_pk,"reason":"odds_event_unmatched"}); continue
        try: results.append(build_native_result(game,event,target_date=target_date,analyzed_at=at,input_builder=input_builder))
        except Exception as exc: skipped.append({"game_pk":game_pk,"reason":f"{type(exc).__name__}: {exc}"})
    return {
        "schema":"pulsar-v14-native-candidate-v2","version":VERSION,"model_generation":MODEL_GENERATION,"role":"CANDIDATE_NON_PUBLISHING","native_acquisition":True,"legacy_acquisition_adapter":False,"market_probability_used_as_feature":False,
        "target_date":target_date,"analyzed_at":at,"results":results,"skipped":skipped,
        "coverage":{"scheduled_future_games":len(snapshot.games),"matched_odds_games":len(snapshot.matches),"priced_games":len(results),"skipped_games":len(skipped)},
    }


def compare_with_legacy(candidate: dict[str,Any],legacy_payload: dict[str,Any]) -> dict[str,Any]:
    legacy_by_pk={str(r.get("game_pk") or (r.get("game") or {}).get("gamePk") or ""):r for r in legacy_payload.get("results") or []}; rows=[]
    for native in candidate.get("results") or []:
        game_pk=str(native.get("game_pk") or ""); legacy=legacy_by_pk.get(game_pk)
        if legacy is None: rows.append({"game_pk":game_pk,"status":"LEGACY_MISSING"}); continue
        features=legacy.get("features") or {}; lh,la=features.get("structural_home_mu"),features.get("structural_away_mu"); ns=native.get("native_structural") or {}; nh,na=ns.get("structural_home_mu"),ns.get("structural_away_mu")
        if None in {lh,la,nh,na}: rows.append({"game_pk":game_pk,"status":"STRUCTURAL_FIELDS_MISSING"}); continue
        hd=float(nh)-float(lh); ad=float(na)-float(la); rows.append({"game_pk":game_pk,"status":"COMPARABLE","native_home_mu":float(nh),"legacy_home_mu":float(lh),"home_delta":hd,"native_away_mu":float(na),"legacy_away_mu":float(la),"away_delta":ad,"max_abs_delta":max(abs(hd),abs(ad))})
    comparable=[r for r in rows if r.get("status")=="COMPARABLE"]; max_abs=max((r["max_abs_delta"] for r in comparable),default=None); mean_abs=sum((abs(r["home_delta"])+abs(r["away_delta"]))/2 for r in comparable)/len(comparable) if comparable else None
    return {"schema":"pulsar-v14-native-legacy-parity-v1","candidate_generation":candidate.get("model_generation"),"candidate_games":len(candidate.get("results") or []),"legacy_games":len(legacy_payload.get("results") or []),"comparable_games":len(comparable),"max_abs_structural_run_delta":max_abs,"mean_abs_structural_run_delta":mean_abs,"rows":rows,"cutover_authorized":False,"note":"Historical evidence only; not a production authorization mechanism."}


def persist_candidate(candidate: dict[str,Any],destination: Path|str=NATIVE_CANDIDATE) -> Path:
    target=Path(destination); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(candidate,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); return target


def main() -> None:
    import argparse
    parser=argparse.ArgumentParser(description="Build non-publishing native Pulsar V14 candidate"); parser.add_argument("target_date"); parser.add_argument("--destination",default=str(NATIVE_CANDIDATE)); parser.add_argument("--legacy-payload"); parser.add_argument("--parity-output",default="runtime/v14/native_legacy_parity.json"); args=parser.parse_args()
    candidate=build_candidate(args.target_date); path=persist_candidate(candidate,args.destination); print(f"PULSAR_V14_NATIVE_CANDIDATE games={len(candidate['results'])} path={path}")
    if args.legacy_payload:
        legacy=json.loads(Path(args.legacy_payload).read_text(encoding="utf-8")); report=compare_with_legacy(candidate,legacy); parity=Path(args.parity_output); parity.parent.mkdir(parents=True,exist_ok=True); parity.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); print(f"PULSAR_V14_NATIVE_PARITY comparable={report['comparable_games']} max_abs_delta={report['max_abs_structural_run_delta']}")

if __name__=="__main__": main()
