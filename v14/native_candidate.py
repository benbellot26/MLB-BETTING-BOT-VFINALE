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
from .defense_baserunning_challenger import build as defense_baserunning_shadow
from .environment_physics_challenger import evaluate as environment_physics_shadow
from .execution_market import best_execution
from .historical_distribution_shadow import evaluate as historical_distribution_shadow
from .historical_pit import source_contract
from .historical_team_shadow import evaluate as historical_team_run_shadow
from .market_edge import diagnostics_from_snapshot
from .market_lines import canonical_market_snapshot, choose_total_line
from .mlb_inputs import COORD, NativeGameInputs, build_game_inputs
from .phase import infer_phase
from .pipeline import predict_from_structural
from .pitch_matchup_challenger import build as pitch_matchup_shadow
from .run_decomposition_challenger import build as run_decomposition_shadow
from .sharp_market import sharp_consensus
from .starter_fallback import degraded_sides_from_evidence, degradation_summary, neutralize_probable_pitchers
from .starter_integrity import starter_integrity_evidence
from .starter_recent_usage import enrich_starter
from .starter_usage_challenger import estimate as starter_usage_shadow
from .statcast_shadow import build_shadow_features, load_priors as load_statcast_priors
from .team_history_shadow import live_artifact as live_team_history, matchup as team_history_matchup
from .true_talent_challenger import build as true_talent_shadow
from .uncertainty import intervals as probability_intervals
from .venue_park_challenger import resolve as venue_park_shadow
from .weather_live_shadow import fetch as live_weather_shadow, merge_environment

NATIVE_CANDIDATE=Path("runtime/v14/native_candidate.json")
Collector=Callable[...,PregameSnapshot]
InputBuilder=Callable[...,NativeGameInputs]
StarterEvidenceBuilder=Callable[[dict[str,Any]],dict[str,Any]]
TeamHistoryBuilder=Callable[[str],dict[str,Any]]


def _empty_team_history(target_date:str,reason:str)->dict[str,Any]:
    return {"schema":"pulsar-v14-native-team-history-v1","role":"SHADOW_ONLY","champion_impact":False,"point_in_time":True,"target_date":target_date,"status":"COLLECTING","reason":reason,"teams":{}}


def _empty_weather(reason:str)->dict[str,Any]:
    return {"schema":"pulsar-v14-live-weather-shadow-v2","role":"SHADOW_ONLY","status":"COLLECTING","auto_activation":False,"champion_impact":False,"point_in_time":True,"reason":reason,"market_probability_used_as_feature":False}


def _phase_quality_gate(native:NativeGameInputs,phase:str)->None:
    quality=native.feature_row.get("data_quality") or {}; starter_ok=quality.get("starter_complete") is True or quality.get("starter_degraded") is True
    if phase in {"LATE","FINAL"} and not starter_ok: raise ValueError(f"{phase} snapshot requires confirmed starters or neutral starter fallback")
    if phase=="FINAL" and (int(quality.get("home_lineup_count") or 0)<9 or int(quality.get("away_lineup_count") or 0)<9): raise ValueError("FINAL snapshot requires both confirmed 9/9 lineups")


def _pitching_factor(statcast_side:dict[str,Any],component:str)->float|None:
    row=statcast_side.get(component) or {}; value=row.get("xwoba_allowed")
    try: value=float(value)
    except Exception: return None
    return max(.70,min(1.35,value/.320))


def _research_challenger_evidence(feature_row:dict[str,Any],*,game:dict[str,Any],target_date:str,statcast:dict[str,Any],team_history:dict[str,Any]|None=None,enable_live_weather:bool=False)->dict[str,Any]:
    ctx=feature_row.get("context") or {}; features=feature_row.get("features") or {}; operational=features.get("operational") or {}; game_date=game.get("gameDate")
    home_starter=enrich_starter(ctx.get("home_starter") or {},game_date); away_starter=enrich_starter(ctx.get("away_starter") or {},game_date); home_usage=starter_usage_shadow(home_starter); away_usage=starter_usage_shadow(away_starter)
    teams=game.get("teams") or {}; home_team=((teams.get("home") or {}).get("team") or {}); away_team=((teams.get("away") or {}).get("team") or {}); home_id=home_team.get("id"); away_id=away_team.get("id")
    defense=defense_baserunning_shadow(home_team_id=home_id,away_team_id=away_id,target_date=target_date); venue=game.get("venue") or {}; park=venue_park_shadow(venue_id=venue.get("id"),venue_name=venue.get("name"),target_date=target_date,legacy_team_factor=(feature_row.get("static_park_factor") or ((feature_row.get("debug") or {}).get("static_park_factor"))))
    home_def=(defense.get("home") or {}); away_def=(defense.get("away") or {})
    home_decomp=run_decomposition_shadow(starter_usage=home_usage,starter_factor=_pitching_factor(statcast.get("home") or {},"starter"),bullpen_factor=_pitching_factor(statcast.get("home") or {},"bullpen"),defense_factor=home_def.get("defense_factor")); away_decomp=run_decomposition_shadow(starter_usage=away_usage,starter_factor=_pitching_factor(statcast.get("away") or {},"starter"),bullpen_factor=_pitching_factor(statcast.get("away") or {},"bullpen"),defense_factor=away_def.get("defense_factor"))
    recent={"home":{"status":home_starter.get("recent_starts_status"),"n":home_starter.get("recent_starts_n"),"starts":home_starter.get("recent_starts") or []},"away":{"status":away_starter.get("recent_starts_status"),"n":away_starter.get("recent_starts_n"),"starts":away_starter.get("recent_starts") or []},"point_in_time":True}
    team_history_evidence=team_history_matchup(team_history or {},home_id,away_id) if team_history else {"schema":"pulsar-v14-native-team-history-matchup-v1","role":"SHADOW_ONLY","champion_impact":False,"point_in_time":True,"status":"COLLECTING","reason":"team_history_artifact_unavailable"}
    home_name=str(home_team.get("name") or ""); coords=COORD.get(home_name)
    if enable_live_weather:
        latitude,longitude=coords if coords else (None,None); weather=live_weather_shadow(latitude,longitude,venue_id=venue.get("id"),game_date=str(game_date or ""),analyzed_at=str(feature_row.get("as_of") or ""))
    else:
        weather=_empty_weather("nonproduction dependencies injected; prospective weather network acquisition skipped")
    enriched_environment=merge_environment(features.get("environment") or {},weather)
    return {"schema":"pulsar-v14-research-challenger-evidence-v7","champion_impact":False,"home_starter_usage":home_usage,"away_starter_usage":away_usage,"starter_recent_workload":recent,"team_history":team_history_evidence,"weather_forecast_shadow":weather,"advanced_environment":enriched_environment,"environment_physics":environment_physics_shadow(enriched_environment),"timezone_exact":{"home":((operational.get("home") or {}).get("timezone_shift_exact_evidence") or {}),"away":((operational.get("away") or {}).get("timezone_shift_exact_evidence") or {})},"venue_park":park,"defense_baserunning":defense,"run_decomposition":{"home_defense":home_decomp,"away_defense":away_decomp},"market_probability_used_as_feature":False}


def _prediction_feature_row(feature_row:dict[str,Any],research:dict[str,Any])->dict[str,Any]:
    """Reuse the already-fetched prospective weather in the probability snapshot."""
    out=dict(feature_row); features=dict(out.get("features") or {}); enriched=research.get("advanced_environment")
    if isinstance(enriched,dict) and enriched:
        features["environment"]=dict(enriched); out["features"]=features
    weather=research.get("weather_forecast_shadow") or {}
    if isinstance(weather,dict) and weather.get("status")=="READY_SHADOW" and weather.get("point_in_time") is True:
        provenance=dict(out.get("feature_provenance") or {})
        provenance["advanced_weather"]={"point_in_time":True,"retrieval_timestamp_attested":True,"source_timestamp_attested":True,"postgame_identity":False,"source":weather.get("source"),"forecast_valid_time":weather.get("forecast_valid_time")}
        out["feature_provenance"]=provenance
    return out


def _compact_training_features(feature_row:dict[str,Any],prediction:dict[str,Any],statcast:dict[str,Any],research:dict[str,Any],pitch_matchup:dict[str,Any],true_talent:dict[str,Any],*,analyzed_at:str,game_date:str)->dict[str,Any]:
    ctx=feature_row.get("context") or {}; features=feature_row.get("features") or {}; quality=feature_row.get("data_quality") or {}; pit=source_contract(captured_at=analyzed_at,effective_cutoff=game_date,source_type="mlb_stats_season_live",prospective=True)
    return {"schema":"pulsar-v14-training-features-v8","as_of":feature_row.get("as_of"),"point_in_time":feature_row.get("point_in_time") is True,"capture_mode":"PROSPECTIVE_LIVE_SNAPSHOT","pit_source_contract":pit,"base_run_projection":prediction.get("base_run_projection") or {},"context_adjustment":prediction.get("context_adjustment") or {},"advanced_stats_adjustment":prediction.get("advanced_stats_adjustment") or {},"home_starter":ctx.get("home_starter") or {},"away_starter":ctx.get("away_starter") or {},"home_lineup":{k:(ctx.get("home_lineup") or {}).get(k) for k in ("count","weighted_ops","coverage","status","players")},"away_lineup":{k:(ctx.get("away_lineup") or {}).get(k) for k in ("count","weighted_ops","coverage","status","players")},"bullpen":features.get("bullpen") or {},"operational":features.get("operational") or {},"environment":features.get("environment") or {},"statcast_shadow":statcast,"pitch_matchup_shadow":pitch_matchup,"true_talent_shadow":true_talent,"research_challengers":research,"data_quality":quality}


def build_native_result(game:dict[str,Any],event:dict[str,Any],*,target_date:str,analyzed_at:str,input_builder:InputBuilder=build_game_inputs,starter_evidence_builder:StarterEvidenceBuilder=starter_integrity_evidence,team_history:dict[str,Any]|None=None)->dict[str,Any]:
    native=input_builder(game,target_date=target_date,analyzed_at=analyzed_at); line_meta=choose_total_line(event,as_of=analyzed_at); phase=infer_phase(analyzed_at=analyzed_at,game_date=native.structural.game_date,context=native.context); starter_integrity=starter_evidence_builder(game); degraded_sides=degraded_sides_from_evidence(starter_integrity,phase); fallback=degradation_summary(starter_integrity,degraded_sides)
    if degraded_sides:
        native=input_builder(neutralize_probable_pitchers(game,degraded_sides),target_date=target_date,analyzed_at=analyzed_at); phase=infer_phase(analyzed_at=analyzed_at,game_date=native.structural.game_date,context=native.context)
    feature_row=dict(native.feature_row); feature_row["phase"]=phase; feature_row["starter_integrity"]=starter_integrity; feature_row["static_park_factor"]=native.structural.static_park_factor; quality=dict(feature_row.get("data_quality") or {}); quality["starter_degraded"]=bool(degraded_sides); quality["starter_degraded_sides"]=list(degraded_sides); quality["starter_fallback_mode"]=fallback.get("mode"); feature_row["data_quality"]=quality
    gated=NativeGameInputs(structural=native.structural,home=native.home,away=native.away,context=native.context,feature_row=feature_row,structural_debug=native.structural_debug); _phase_quality_gate(gated,phase)
    priors=load_statcast_priors(); statcast=build_shadow_features(feature_row,target_date=target_date,artifact=priors if priors else None); pitch_matchup=pitch_matchup_shadow(feature_row,statcast,priors) if priors else {"schema":"pulsar-v14-pitch-matchup-challenger-v1","role":"CHALLENGER_ONLY","auto_activation":False,"status":"COLLECTING","reason":"statcast artifact unavailable"}; research=_research_challenger_evidence(feature_row,game=game,target_date=target_date,statcast=statcast,team_history=team_history,enable_live_weather=(input_builder is build_game_inputs)); true_talent=true_talent_shadow(statcast=statcast,pitch_matchup=pitch_matchup,research=research)
    prediction_row=_prediction_feature_row(feature_row,research)
    prediction=predict_from_structural(native.structural,analyzed_at=analyzed_at,home=native.home,away=native.away,total_line=float(line_meta["line"]),feature_row=prediction_row,phase=phase)
    team_shadow=historical_team_run_shadow(prediction,research.get("team_history") or {}); distribution_shadow=historical_distribution_shadow(prediction); research=dict(research); research["historical_team_run_shadow"]=team_shadow; research["historical_distribution_shadow"]=distribution_shadow
    market_snapshot=canonical_market_snapshot(event,total_line=float(line_meta["line"]),as_of=analyzed_at); prediction["probability_intervals"]=probability_intervals(prediction.get("probabilities") or {},prediction.get("calibration") or {},data_quality=quality,starter_degraded=bool(degraded_sides),market_fresh=market_snapshot.get("freshness_verified")); market_diagnostics=diagnostics_from_snapshot(prediction,market_snapshot); sharp=sharp_consensus(event,total_line=float(line_meta["line"]),as_of=analyzed_at); execution=best_execution(event,total_line=float(line_meta["line"]),as_of=analyzed_at); certification=load_certification_status(); decision=decision_diagnostics(prediction=prediction,market_snapshot=market_snapshot,sharp_market=sharp,certification=certification,starter_degraded=bool(degraded_sides),execution_market=execution)
    context=dict(native.context); context["starter_integrity"]=starter_integrity; context["starter_fallback"]=fallback
    return {"game_pk":native.structural.game_pk,"odds_event_id":event.get("id"),"game_date":native.structural.game_date,"analyzed_at":analyzed_at,"phase":phase,"home":native.home,"away":native.away,"ctx":context,"canonical_lines":{"TOTAL":float(line_meta["line"])},"line_selection":line_meta,"market_snapshot":market_snapshot,"execution_market":execution,"market_diagnostics":market_diagnostics,"sharp_market":sharp,"betting_certification":certification,"decision":decision,"native_structural":{"game_pk":native.structural.game_pk,"game_date":native.structural.game_date,"venue":native.structural.venue,"structural_home_mu":native.structural.structural_home_mu,"structural_away_mu":native.structural.structural_away_mu,"static_park_factor":native.structural.static_park_factor,"debug":native.structural_debug},"training_features":_compact_training_features(prediction_row,prediction,statcast,research,pitch_matchup,true_talent,analyzed_at=analyzed_at,game_date=native.structural.game_date),"statcast_shadow":statcast,"research_challengers":research,"historical_team_run_shadow":team_shadow,"historical_distribution_shadow":distribution_shadow,"pitch_matchup_shadow":pitch_matchup,"true_talent_shadow":true_talent,"starter_fallback":fallback,"v14_prediction":prediction,"model_generation":MODEL_GENERATION,"market_probability_used_as_feature":False}


def build_candidate(target_date:str,*,analyzed_at:str|None=None,api_key:str|None=None,collector:Collector=collect_pregame_strict,input_builder:InputBuilder=build_game_inputs,starter_evidence_builder:StarterEvidenceBuilder=starter_integrity_evidence,team_history_builder:TeamHistoryBuilder|None=None)->dict[str,Any]:
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); snapshot=collector(target_date,analyzed_at=at,api_key=api_key); results=[]; skipped=[]
    if team_history_builder is not None:
        team_history=team_history_builder(target_date)
    elif collector is collect_pregame_strict and input_builder is build_game_inputs:
        team_history=live_team_history(target_date)
    else:
        team_history=_empty_team_history(target_date,"nonproduction dependencies injected; network shadow acquisition skipped")
    for game in snapshot.games:
        game_pk=str(game.get("gamePk") or ""); event=snapshot.matches.get(game_pk)
        if event is None: skipped.append({"game_pk":game_pk,"reason":"odds_event_unmatched"}); continue
        try: results.append(build_native_result(game,event,target_date=target_date,analyzed_at=at,input_builder=input_builder,starter_evidence_builder=starter_evidence_builder,team_history=team_history))
        except Exception as exc: skipped.append({"game_pk":game_pk,"reason":f"{type(exc).__name__}: {exc}"})
    return {"schema":"pulsar-v14-native-candidate-v6","version":VERSION,"model_generation":MODEL_GENERATION,"role":"CANDIDATE_NON_PUBLISHING","native_acquisition":True,"legacy_acquisition_adapter":False,"market_probability_used_as_feature":False,"target_date":target_date,"analyzed_at":at,"team_history_shadow_status":team_history.get("status") or "READY_SHADOW","results":results,"skipped":skipped,"coverage":{"scheduled_future_games":len(snapshot.games),"matched_odds_games":len(snapshot.matches),"priced_games":len(results),"skipped_games":len(skipped)}}


def compare_with_legacy(candidate:dict[str,Any],legacy_payload:dict[str,Any])->dict[str,Any]:
    legacy_by_pk={str(r.get("game_pk") or (r.get("game") or {}).get("gamePk") or ""):r for r in legacy_payload.get("results") or []}; rows=[]
    for native in candidate.get("results") or []:
        game_pk=str(native.get("game_pk") or ""); legacy=legacy_by_pk.get(game_pk)
        if legacy is None: rows.append({"game_pk":game_pk,"status":"LEGACY_MISSING"}); continue
        features=legacy.get("features") or {}; lh,la=features.get("structural_home_mu"),features.get("structural_away_mu"); ns=native.get("native_structural") or {}; nh,na=ns.get("structural_home_mu"),ns.get("structural_away_mu")
        if None in {lh,la,nh,na}: rows.append({"game_pk":game_pk,"status":"STRUCTURAL_FIELDS_MISSING"}); continue
        hd=float(nh)-float(lh); ad=float(na)-float(la); rows.append({"game_pk":game_pk,"status":"COMPARABLE","native_home_mu":float(nh),"legacy_home_mu":float(lh),"home_delta":hd,"native_away_mu":float(na),"legacy_away_mu":float(la),"away_delta":ad,"max_abs_delta":max(abs(hd),abs(ad))})
    comparable=[r for r in rows if r.get("status")=="COMPARABLE"]; max_abs=max((r["max_abs_delta"] for r in comparable),default=None); mean_abs=sum((abs(r["home_delta"])+abs(r["away_delta"]))/2 for r in comparable)/len(comparable) if comparable else None
    return {"schema":"pulsar-v14-native-legacy-parity-v1","candidate_generation":candidate.get("model_generation"),"candidate_games":len(candidate.get("results") or []),"legacy_games":len(legacy_payload.get("results") or []),"comparable_games":len(comparable),"max_abs_structural_run_delta":max_abs,"mean_abs_structural_run_delta":mean_abs,"rows":rows,"cutover_authorized":False,"note":"Historical evidence only; not a production authorization mechanism."}


def persist_candidate(candidate:dict[str,Any],destination:Path|str=NATIVE_CANDIDATE)->Path:
    target=Path(destination); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(candidate,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); return target


def main()->None:
    import argparse
    parser=argparse.ArgumentParser(description="Build non-publishing native Pulsar V14 candidate"); parser.add_argument("target_date"); parser.add_argument("--destination",default=str(NATIVE_CANDIDATE)); parser.add_argument("--legacy-payload"); parser.add_argument("--parity-output",default="runtime/v14/native_legacy_parity.json"); args=parser.parse_args(); candidate=build_candidate(args.target_date); path=persist_candidate(candidate,args.destination); print(f"PULSAR_V14_NATIVE_CANDIDATE games={len(candidate['results'])} path={path}")
    if args.legacy_payload:
        legacy=json.loads(Path(args.legacy_payload).read_text(encoding="utf-8")); report=compare_with_legacy(candidate,legacy); parity=Path(args.parity_output); parity.parent.mkdir(parents=True,exist_ok=True); parity.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); print(f"PULSAR_V14_NATIVE_PARITY comparable={report['comparable_games']} max_abs_delta={report['max_abs_structural_run_delta']}")


if __name__=="__main__": main()
