from __future__ import annotations

"""Native production runtime for Pulsar V14."""

import argparse
import json
from pathlib import Path
import time
from typing import Any

from . import MODEL_GENERATION
from .acquisition import resolve_target_date
from .discord import publication_gap_seconds, send_game
from .native_candidate import build_candidate, persist_candidate
from .native_payload import authorize_payload, build_native_discord_payload

V14_CANDIDATE=Path("runtime/v14/native_candidate.json")
V14_PAYLOAD=Path("runtime/v14/discord_payload.json")
MIN_PRICED_MATCHED_COVERAGE=.80
MIN_MATCHED_SCHEDULED_COVERAGE=.80


def validate_candidate_coverage(candidate:dict[str,Any])->None:
    coverage=candidate.get("coverage") or {}; scheduled=int(coverage.get("scheduled_future_games") or 0); matched=int(coverage.get("matched_odds_games") or 0); priced=int(coverage.get("priced_games") or 0)
    if priced<=0: raise RuntimeError("native V14 acquisition produced no priced games")
    if scheduled>0:
        match_ratio=matched/scheduled
        if match_ratio<MIN_MATCHED_SCHEDULED_COVERAGE: raise RuntimeError(f"native V14 odds/schedule coverage too low: {matched}/{scheduled}={match_ratio:.1%} < {MIN_MATCHED_SCHEDULED_COVERAGE:.0%}")
    if matched>0:
        ratio=priced/matched
        if ratio<MIN_PRICED_MATCHED_COVERAGE: raise RuntimeError(f"native V14 priced/matched coverage too low: {priced}/{matched}={ratio:.1%} < {MIN_PRICED_MATCHED_COVERAGE:.0%}")


def _candidate_market_certified(certification:dict[str,Any],candidate:dict[str,Any])->bool:
    canonical=str(candidate.get("canonical_market") or "")
    markets=certification.get("markets") or {}
    if not canonical or not markets: return False
    return ((markets.get(canonical) or {}).get("betting_certified") is True)


def validate_production_payload(payload:dict[str,Any])->None:
    if payload.get("role")!="PRODUCTION": raise ValueError("V14 payload is not production")
    if payload.get("publication_authorized") is not True: raise ValueError("V14 payload publication is not authorized")
    if payload.get("model_generation")!=MODEL_GENERATION: raise ValueError("V14 payload generation mismatch")
    if payload.get("native_acquisition") is not True: raise ValueError("V14 payload is not native acquisition")
    if payload.get("legacy_acquisition_adapter") is not False: raise ValueError("legacy acquisition leaked into V14 production")
    if payload.get("legacy_probability_used_for_publication") is not False: raise ValueError("legacy probability publication leak")
    if payload.get("market_probability_used_as_feature") is not False: raise ValueError("market probability feature leak")
    if payload.get("chosen"): raise ValueError("analytics payload contains recommendations")
    if (payload.get("combo") or {}).get("official"): raise ValueError("analytics payload contains official combo")

    top_cert=payload.get("betting_certification") or {}
    if top_cert and top_cert.get("model_generation")!=MODEL_GENERATION: raise ValueError("payload betting certification generation mismatch")
    for result in payload.get("results") or []:
        game_pk=result.get("game_pk")
        if result.get("model_generation")!=MODEL_GENERATION: raise ValueError(f"game {game_pk} is not V14")
        if result.get("native_acquisition") is not True: raise ValueError(f"game {game_pk} is not native acquisition")
        prediction=result.get("v14_prediction") or {}
        if prediction.get("model_generation")!=MODEL_GENERATION or prediction.get("role")!="PRODUCTION": raise ValueError(f"game {game_pk} missing V14 production prediction")
        if prediction.get("market_probability_used_as_feature") is not False: raise ValueError(f"game {game_pk} used market probability as model feature")
        surface=prediction.get("probabilities") or {}; pairs=((surface.get("away_ml"),surface.get("home_ml")),(surface.get("away_plus_1_5"),surface.get("home_minus_1_5")),(surface.get("home_plus_1_5"),surface.get("away_minus_1_5")),(surface.get("over"),surface.get("under")))
        for left,right in pairs:
            if left is None or right is None or abs(float(left)+float(right)-1.0)>1e-9: raise ValueError(f"game {game_pk} has invalid probability surface")
        if "market_snapshot" not in result or "market_diagnostics" not in result or "execution_market" not in result: raise ValueError(f"game {game_pk} missing market audit/execution state")

        certification=result.get("betting_certification") or top_cert or {}
        if certification and certification.get("model_generation")!=MODEL_GENERATION: raise ValueError(f"game {game_pk} certification generation mismatch")
        decision=result.get("decision") or {}
        for candidate in decision.get("candidates") or []:
            if candidate.get("status")!="BET": continue
            if certification.get("certified") is not True: raise ValueError(f"game {game_pk} emitted BET without global statistical certification")
            if not _candidate_market_certified(certification,candidate): raise ValueError(f"game {game_pk} emitted BET without market-specific statistical certification for {candidate.get('canonical_market')}")
            if candidate.get("edge_qualified") is not True or candidate.get("research_ready") is not True: raise ValueError(f"game {game_pk} emitted BET without qualified robust-edge evidence")
            if int(candidate.get("sharp_sportsbook_source_count") or 0)<1: raise ValueError(f"game {game_pk} emitted BET without a validated sharp sportsbook contributor")
            if not candidate.get("execution_book") or float(candidate.get("price") or 0)<=1: raise ValueError(f"game {game_pk} emitted BET without executable book/price")
        fallback=result.get("starter_fallback") or {}
        if fallback.get("degraded") and any(c.get("status")=="BET" for c in decision.get("candidates") or []): raise ValueError(f"game {game_pk} emitted BET with degraded starter data")


def build_persisted(*,target_date:str|None=None,destination:Path|str=V14_PAYLOAD,candidate_destination:Path|str=V14_CANDIDATE)->dict[str,Any]:
    date=target_date or resolve_target_date(); candidate=build_candidate(date); persist_candidate(candidate,candidate_destination); validate_candidate_coverage(candidate); unauthorized=build_native_discord_payload(candidate); payload=authorize_payload(unauthorized,production_authorized=True); payload["authorization_basis"]={"type":"software-production-contract","model_generation":MODEL_GENERATION,"priced_matched_coverage_gate":MIN_PRICED_MATCHED_COVERAGE,"matched_scheduled_coverage_gate":MIN_MATCHED_SCHEDULED_COVERAGE,"betting_certified":bool((payload.get("betting_certification") or {}).get("certified")),"note":"Publication is analytics/software authorization; betting requires the independent market-specific statistical certification gate."}; validate_production_payload(payload); target=Path(destination); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8"); print(f"PULSAR_V14_NATIVE_PRODUCTION date={date} games={len(payload['results'])} path={target}"); return payload


def send_persisted(*,path:Path|str=V14_PAYLOAD)->None:
    source=Path(path)
    if not source.exists(): raise SystemExit(f"V14 Discord payload absent: {source}")
    payload=json.loads(source.read_text(encoding="utf-8")); validate_production_payload(payload); results=list(payload.get("results") or []); ok=True; gap=publication_gap_seconds()
    for index,result in enumerate(results):
        ok=bool(send_game(result)) and ok
        if index+1<len(results) and gap>0: time.sleep(gap)
    if not ok: raise SystemExit("Pulsar V14 Discord publication incomplete")
    print(f"PULSAR_V14_DISCORD published_games={len(results)}")


def main()->None:
    parser=argparse.ArgumentParser(description="Native Pulsar V14 production runtime"); parser.add_argument("--send-persisted",action="store_true"); parser.add_argument("--target-date"); parser.add_argument("--destination",default=str(V14_PAYLOAD)); parser.add_argument("--candidate-destination",default=str(V14_CANDIDATE)); args=parser.parse_args()
    if args.send_persisted: send_persisted(path=args.destination)
    else: build_persisted(target_date=args.target_date,destination=args.destination,candidate_destination=args.candidate_destination)

if __name__=="__main__": main()
