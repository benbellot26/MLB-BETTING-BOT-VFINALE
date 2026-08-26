from __future__ import annotations

"""Native end-to-end candidate builder for Pulsar V14."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, VERSION
from .acquisition import PregameSnapshot
from .acquisition_strict import collect_pregame_strict
from .certification import load_status as load_certification_status
from .decision import evaluate as decision_diagnostics
from .market_edge import diagnostics_from_snapshot
from .market_lines import canonical_market_snapshot, choose_total_line
from .mlb_inputs import NativeGameInputs, build_game_inputs
from .phase import infer_phase
from .pipeline import predict_from_structural
from .sharp_market import sharp_consensus
from .starter_fallback import degraded_sides_from_evidence, degradation_summary, neutralize_probable_pitchers
from .starter_integrity import starter_integrity_evidence
from .statcast_shadow import build_shadow_features
from .uncertainty import intervals as probability_intervals

NATIVE_CANDIDATE = Path("runtime/v14/native_candidate.json")
Collector = Callable[..., PregameSnapshot]
InputBuilder = Callable[..., NativeGameInputs]
StarterEvidenceBuilder = Callable[[dict[str, Any]], dict[str, Any]]


def _phase_quality_gate(native: NativeGameInputs, phase: str) -> None:
    quality = native.feature_row.get("data_quality") or {}
    starter_ok = quality.get("starter_complete") is True or quality.get("starter_degraded") is True
    if phase in {"LATE", "FINAL"} and not starter_ok:
        raise ValueError(f"{phase} snapshot requires confirmed starters or neutral starter fallback")
    if phase == "FINAL":
        home_count = int(quality.get("home_lineup_count") or 0)
        away_count = int(quality.get("away_lineup_count") or 0)
        if home_count < 9 or away_count < 9:
            raise ValueError("FINAL snapshot requires both confirmed 9/9 lineups")


def _compact_training_features(feature_row: dict[str, Any], prediction: dict[str, Any], statcast_shadow: dict[str, Any]) -> dict[str, Any]:
    """Persist only PIT covariates needed for future residual challengers."""
    ctx = feature_row.get("context") or {}
    features = feature_row.get("features") or {}
    quality = feature_row.get("data_quality") or {}
    return {
        "schema": "pulsar-v14-training-features-v2",
        "as_of": feature_row.get("as_of"),
        "point_in_time": feature_row.get("point_in_time") is True,
        "base_run_projection": prediction.get("base_run_projection") or {},
        "context_adjustment": prediction.get("context_adjustment") or {},
        "home_starter": ctx.get("home_starter") or {},
        "away_starter": ctx.get("away_starter") or {},
        "home_lineup": {k: (ctx.get("home_lineup") or {}).get(k) for k in ("count", "weighted_ops", "coverage", "status")},
        "away_lineup": {k: (ctx.get("away_lineup") or {}).get(k) for k in ("count", "weighted_ops", "coverage", "status")},
        "bullpen": features.get("bullpen") or {},
        "operational": features.get("operational") or {},
        "environment": features.get("environment") or {},
        "statcast_shadow": statcast_shadow,
        "data_quality": quality,
    }


def build_native_result(
    game: dict[str, Any],
    event: dict[str, Any],
    *,
    target_date: str,
    analyzed_at: str,
    input_builder: InputBuilder=build_game_inputs,
    starter_evidence_builder: StarterEvidenceBuilder=starter_integrity_evidence,
) -> dict[str, Any]:
    native=input_builder(game,target_date=target_date,analyzed_at=analyzed_at)
    line_meta=choose_total_line(event,as_of=analyzed_at)
    phase=infer_phase(analyzed_at=analyzed_at,game_date=native.structural.game_date,context=native.context)

    starter_integrity=starter_evidence_builder(game)
    degraded_sides=degraded_sides_from_evidence(starter_integrity,phase)
    fallback=degradation_summary(starter_integrity,degraded_sides)

    # Preserve full-slate analytics coverage: conflicts never silently trust a
    # stale pitcher. Affected sides are rebuilt with a neutral starter, while
    # the decision layer later blocks the game from actionable betting.
    if degraded_sides:
        sanitized_game=neutralize_probable_pitchers(game,degraded_sides)
        native=input_builder(sanitized_game,target_date=target_date,analyzed_at=analyzed_at)
        phase=infer_phase(analyzed_at=analyzed_at,game_date=native.structural.game_date,context=native.context)

    feature_row=dict(native.feature_row)
    feature_row["phase"]=phase
    feature_row["starter_integrity"]=starter_integrity
    quality=dict(feature_row.get("data_quality") or {})
    quality["starter_degraded"]=bool(degraded_sides)
    quality["starter_degraded_sides"]=list(degraded_sides)
    quality["starter_fallback_mode"]=fallback.get("mode")
    feature_row["data_quality"]=quality

    gated=NativeGameInputs(
        structural=native.structural,home=native.home,away=native.away,
        context=native.context,feature_row=feature_row,structural_debug=native.structural_debug,
    )
    _phase_quality_gate(gated,phase)

    # Statcast is collected as a PIT shadow feature only. It becomes eligible
    # for champion use only through a later OOS challenger promotion.
    statcast=build_shadow_features(feature_row,target_date=target_date)

    prediction=predict_from_structural(native.structural,analyzed_at=analyzed_at,home=native.home,away=native.away,total_line=float(line_meta["line"]),feature_row=feature_row,phase=phase)
    market_snapshot=canonical_market_snapshot(event,total_line=float(line_meta["line"]),as_of=analyzed_at)
    # Once the actual market freshness is known, refresh the decision-safety
    # intervals. This never feeds market probability back into the model.
    prediction["probability_intervals"]=probability_intervals(
        prediction.get("probabilities") or {},
        prediction.get("calibration") or {},
        data_quality=quality,
        starter_degraded=bool(degraded_sides),
        market_fresh=market_snapshot.get("freshness_verified"),
    )
    market_diagnostics=diagnostics_from_snapshot(prediction,market_snapshot)
    sharp=sharp_consensus(event,total_line=float(line_meta["line"]),as_of=analyzed_at)
    certification=load_certification_status()
    decision=decision_diagnostics(
        prediction=prediction,
        market_snapshot=market_snapshot,
        sharp_market=sharp,
        certification=certification,
        starter_degraded=bool(degraded_sides),
    )
    context=dict(native.context); context["starter_integrity"]=starter_integrity; context["starter_fallback"]=fallback
    return {
        "game_pk":native.structural.game_pk,"game_date":native.structural.game_date,"analyzed_at":analyzed_at,"phase":phase,"home":native.home,"away":native.away,"ctx":context,
        "canonical_lines":{"TOTAL":float(line_meta["line"])},"line_selection":line_meta,"market_snapshot":market_snapshot,"market_diagnostics":market_diagnostics,
        "sharp_market":sharp,"betting_certification":certification,"decision":decision,
        "native_structural":{"game_pk":native.structural.game_pk,"game_date":native.structural.game_date,"venue":native.structural.venue,"structural_home_mu":native.structural.structural_home_mu,"structural_away_mu":native.structural.structural_away_mu,"static_park_factor":native.structural.static_park_factor,"debug":native.structural_debug},
        "training_features":_compact_training_features(feature_row,prediction,statcast),
        "statcast_shadow":statcast,
        "starter_fallback":fallback,"v14_prediction":prediction,"model_generation":MODEL_GENERATION,"market_probability_used_as_feature":False,
    }


def build_candidate(
    target_date: str, *, analyzed_at: str|None=None, api_key: str|None=None,
    collector: Collector=collect_pregame_strict, input_builder: InputBuilder=build_game_inputs,
    starter_evidence_builder: StarterEvidenceBuilder=starter_integrity_evidence,
) -> dict[str,Any]:
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); snapshot=collector(target_date,analyzed_at=at,api_key=api_key); results=[]; skipped=[]
    for game in snapshot.games:
        game_pk=str(game.get("gamePk") or ""); event=snapshot.matches.get(game_pk)
        if event is None:
            skipped.append({"game_pk":game_pk,"reason":"odds_event_unmatched"}); continue
        try:
            results.append(build_native_result(game,event,target_date=target_date,analyzed_at=at,input_builder=input_builder,starter_evidence_builder=starter_evidence_builder))
        except Exception as exc:
            skipped.append({"game_pk":game_pk,"reason":f"{type(exc).__name__}: {exc}"})
    return {
        "schema":"pulsar-v14-native-candidate-v3","version":VERSION,"model_generation":MODEL_GENERATION,"role":"CANDIDATE_NON_PUBLISHING","native_acquisition":True,"legacy_acquisition_adapter":False,"market_probability_used_as_feature":False,
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
