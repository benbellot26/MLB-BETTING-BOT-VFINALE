from __future__ import annotations

"""Fail-closed, market-specific betting decision diagnostics for Pulsar V14.

Research diagnostics may be produced in every pregame phase. Executable BET
authorization is stricter: the currently certified evidence contract is FINAL
inside the exact 10-60 minute pregame strategy window, and Pinnacle no-vig is
the primary sharp benchmark. The multi-book sharp consensus remains a secondary
robustness/disagreement diagnostic.

Shadow calibration remains research metadata only. The current published
probability policy is code-frozen, so an unaccepted/collecting shadow calibrator
must never block prospective paper-CLV collection or an otherwise strictly
certified executable decision.
"""

from datetime import datetime, timezone
import math
from typing import Any

from .certification_timing import (
    CERTIFICATION_PHASE,
    FINAL_MAX_MINUTES_TO_GAME,
    FINAL_MIN_MINUTES_TO_GAME,
    is_betting_strategy_snapshot,
    minutes_to_game,
)

BASE_MODEL_EDGE_PP={"ML":3.0,"RL":4.0,"TOTAL":4.0}
BASE_ROBUST_EDGE_PP={"ML":2.0,"RL":3.0,"TOTAL":3.0}
MIN_ROBUST_SHARP_EDGE_PP={"ML":0.5,"RL":0.75,"TOTAL":0.75}
MAX_ABSOLUTE_SHARP_DIVERGENCE_PP=15.0
MAX_SINGLE_SOURCE_SHARP_DIVERGENCE_PP=10.0
BETTING_CERTIFICATION_PHASE=CERTIFICATION_PHASE
PRIMARY_SHARP_BOOK="pinnacle"
SELECTIONS={"ML":{"home":"home_ml","away":"away_ml"},"RL":{"home_-1.5":"home_minus_1_5","away_+1.5":"away_plus_1_5","away_-1.5":"away_minus_1_5","home_+1.5":"home_plus_1_5"},"TOTAL":{"over":"over","under":"under"}}
CALIBRATION_MARKET={"home_ml":"ML","away_ml":"ML","home_minus_1_5":"RL_HOME_-1.5","away_plus_1_5":"RL_HOME_-1.5","away_minus_1_5":"RL_AWAY_-1.5","home_plus_1_5":"RL_AWAY_-1.5","over":"TOTAL_OVER","under":"TOTAL_OVER"}


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _verified_event_timestamp(snapshot:dict[str,Any])->bool:
    value=snapshot.get("commence_time")
    if not value:return False
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        dt.astimezone(timezone.utc)
        return True
    except Exception:return False


def _execution_rows(snapshot:dict[str,Any],execution_market:dict[str,Any]|None=None)->list[tuple[str,str,float,str|None]]:
    best=(execution_market or {}).get("selections") or {}
    if best:
        market_for={key:market for market,mapping in SELECTIONS.items() for key in mapping.values()}; rows=[]
        for key,raw in best.items():
            price=_num((raw or {}).get("price")); market=market_for.get(key)
            if price and price>1 and market: rows.append((key,market,price,str((raw or {}).get("bookmaker") or "") or None))
        if rows:return rows
    rows=[]; markets=snapshot.get("markets") or {}
    for market,mapping in SELECTIONS.items():
        block=markets.get(market) or {}; selections=block.get("selections") or {}; book=block.get("bookmaker")
        for label,key in mapping.items():
            price=_num((selections.get(label) or {}).get("price"))
            if price and price>1:rows.append((key,market,price,str(book) if book else None))
    return rows


def _pinnacle_probability(sharp_row:dict[str,Any])->float|None:
    """Return the persisted Pinnacle sportsbook no-vig contributor probability."""
    for contributor in sharp_row.get("contributors") or []:
        if str(contributor.get("bookmaker") or "").lower()!=PRIMARY_SHARP_BOOK:continue
        if str(contributor.get("source_type") or "").upper()!="SPORTSBOOK":continue
        probability=_num(contributor.get("fair_probability"))
        if probability is not None and 0<probability<1:return probability
    return None


def _calibration_ok(meta:dict[str,Any])->bool:return meta.get("accepted") is True or meta.get("active") is True


def _certified_market(certification:dict[str,Any],canonical_market:str)->bool:
    markets=certification.get("markets") or {}
    if markets:return ((markets.get(canonical_market) or {}).get("betting_certified") is True)
    return certification.get("certified") is True


def _thresholds(market:str,interval:dict[str,Any],sharp_row:dict[str,Any])->tuple[float,float,dict[str,float]]:
    width=_num(interval.get("half_width_pp")) or 10.0; sharp_disp=_num(sharp_row.get("dispersion_pp")) or 0.0; sharp_range=_num(sharp_row.get("range_pp")) or 0.0
    uncertainty_penalty=max(0.0,(width-5.0)*.12); disagreement_penalty=min(2.5,.35*sharp_disp+.08*sharp_range)
    return BASE_MODEL_EDGE_PP[market]+uncertainty_penalty+disagreement_penalty,BASE_ROBUST_EDGE_PP[market]+.5*disagreement_penalty,{"uncertainty_penalty_pp":uncertainty_penalty,"sharp_disagreement_penalty_pp":disagreement_penalty}


def evaluate(*,prediction:dict[str,Any],market_snapshot:dict[str,Any],sharp_market:dict[str,Any],certification:dict[str,Any],starter_degraded:bool=False,execution_market:dict[str,Any]|None=None)->dict[str,Any]:
    probs=prediction.get("probabilities") or {}; intervals=(prediction.get("probability_intervals") or {}).get("selections") or {}; calibration=prediction.get("calibration") or {}; sharp=sharp_market.get("selections") or {}
    phase=str(prediction.get("phase") or "").upper(); betting_phase_ok=phase==BETTING_CERTIFICATION_PHASE; betting_timing_ok=is_betting_strategy_snapshot(prediction); game_minutes=minutes_to_game(prediction)
    freshness=market_snapshot.get("freshness_verified") is True and sharp_market.get("freshness_verified") is True and ((execution_market or {}).get("freshness_verified") is not False); event_timestamp_verified=_verified_event_timestamp(market_snapshot); rows=[]
    for key,market,price,book in _execution_rows(market_snapshot,execution_market):
        p=_num(probs.get(key))
        if p is None:continue
        interval=intervals.get(key) or {}; lower=_num(interval.get("lower")); lower=lower if lower is not None else max(0.0,p-.10); breakeven=1/price; sharp_row=sharp.get(key) or {}; sharp_p=_num(sharp_row.get("fair_probability")); pinnacle_p=_pinnacle_probability(sharp_row)
        model_edge=100*(p-breakeven); robust_edge=100*(lower-breakeven); sharp_edge=100*(p-sharp_p) if sharp_p is not None else None; robust_sharp_edge=100*(lower-sharp_p) if sharp_p is not None else None; primary_sharp_edge=100*(p-pinnacle_p) if pinnacle_p is not None else None; robust_primary_sharp_edge=100*(lower-pinnacle_p) if pinnacle_p is not None else None
        canonical=CALIBRATION_MARKET.get(key) or ""; cal_meta=(calibration.get("markets") or {}).get(canonical) or {}; blockers=[]
        shadow_calibration_accepted=_calibration_ok(cal_meta); shadow_calibration_status=str(cal_meta.get("status") or "COLLECTING")
        if starter_degraded:blockers.append("starter_degraded")
        if not freshness:blockers.append("unverified_market_freshness")
        if sharp_p is None:blockers.append("sharp_consensus_missing")
        source_count=int(sharp_row.get("source_count") or 0); sportsbook_source_count=int(sharp_row.get("sportsbook_source_count") or 0); exchange_proxy_source_count=int(sharp_row.get("exchange_proxy_source_count") or 0)
        if sharp_edge is not None and abs(sharp_edge)>MAX_ABSOLUTE_SHARP_DIVERGENCE_PP:blockers.append("extreme_model_sharp_divergence")
        elif sharp_edge is not None and source_count<2 and abs(sharp_edge)>MAX_SINGLE_SOURCE_SHARP_DIVERGENCE_PP:blockers.append("extreme_single_source_sharp_divergence")
        model_threshold,robust_threshold,penalties=_thresholds(market,interval,sharp_row); robust_sharp_threshold=MIN_ROBUST_SHARP_EDGE_PP[market]
        edge_qualified=(model_edge>=model_threshold and robust_edge>=robust_threshold and sharp_edge is not None and sharp_edge>0 and robust_sharp_edge is not None and robust_sharp_edge>=robust_sharp_threshold)
        research_ready=edge_qualified and not blockers
        # Betting-only gates are intentionally added after research_ready so a
        # high-quality row outside the executable strategy can still earn research evidence.
        if not betting_phase_ok:blockers.append("betting_phase_not_final")
        if not betting_timing_ok:blockers.append("betting_timing_outside_certified_window")
        if not event_timestamp_verified:blockers.append("odds_event_timestamp_missing_for_bet")
        if sportsbook_source_count<1:blockers.append("sharp_sportsbook_source_missing_for_bet")
        if pinnacle_p is None:blockers.append("pinnacle_primary_sharp_missing_for_bet")
        primary_edge_qualified=(primary_sharp_edge is not None and primary_sharp_edge>0 and robust_primary_sharp_edge is not None and robust_primary_sharp_edge>=robust_sharp_threshold)
        if pinnacle_p is not None and not primary_edge_qualified:blockers.append("pinnacle_primary_edge_not_qualified")
        market_certified=_certified_market(certification,canonical)
        if not market_certified:
            blockers.append("betting_not_certified"); blockers.append(f"{canonical or market}_betting_not_certified")
        betting_edge_qualified=edge_qualified and primary_edge_qualified
        status="BET" if betting_edge_qualified and not blockers else ("RESEARCH_ONLY" if research_ready else "NO_BET")
        rows.append({"selection":key,"canonical_market":canonical,"market":market,"phase":phase or None,"execution_book":book,"execution_source":"LINE_SHOPPED" if (execution_market or {}).get("selections") else "CANONICAL_FALLBACK","price":price,"probability":p,"lower_probability":lower,"break_even_probability":breakeven,"model_edge_pp":model_edge,"robust_edge_pp":robust_edge,"sharp_probability":sharp_p,"sharp_edge_pp":sharp_edge,"robust_sharp_edge_pp":robust_sharp_edge,"primary_sharp_benchmark":"PINNACLE_NO_VIG","pinnacle_probability":pinnacle_p,"primary_sharp_edge_pp":primary_sharp_edge,"robust_primary_sharp_edge_pp":robust_primary_sharp_edge,"primary_edge_qualified":primary_edge_qualified,"betting_edge_qualified":betting_edge_qualified,"sharp_source_count":source_count,"sharp_sportsbook_source_count":sportsbook_source_count,"sharp_exchange_proxy_source_count":exchange_proxy_source_count,"sharp_dispersion_pp":_num(sharp_row.get("dispersion_pp")),"shadow_calibration_status":shadow_calibration_status,"shadow_calibration_accepted":shadow_calibration_accepted,"shadow_calibration_role":"DIAGNOSTIC_ONLY","odds_event_timestamp_verified":event_timestamp_verified,"betting_phase_required":BETTING_CERTIFICATION_PHASE,"betting_phase_ok":betting_phase_ok,"betting_timing_ok":betting_timing_ok,"minutes_to_game":game_minutes,"betting_window_min_minutes_to_game":FINAL_MIN_MINUTES_TO_GAME,"betting_window_max_minutes_to_game":FINAL_MAX_MINUTES_TO_GAME,"model_edge_threshold_pp":model_threshold,"robust_edge_threshold_pp":robust_threshold,"robust_sharp_edge_threshold_pp":robust_sharp_threshold,**penalties,"edge_qualified":edge_qualified,"research_ready":research_ready,"market_betting_certified":market_certified,"status":status,"blockers":blockers})
    rows.sort(key=lambda r:r.get("robust_edge_pp") if r.get("robust_edge_pp") is not None else -999,reverse=True)
    return {"schema":"pulsar-v14-decision-diagnostics-v10","betting_certified":any(r.get("market_betting_certified") for r in rows),"starter_degraded":bool(starter_degraded),"phase":phase or None,"betting_phase_required":BETTING_CERTIFICATION_PHASE,"betting_phase_ok":betting_phase_ok,"betting_timing_ok":betting_timing_ok,"minutes_to_game":game_minutes,"betting_window_minutes_to_game":{"min":FINAL_MIN_MINUTES_TO_GAME,"max":FINAL_MAX_MINUTES_TO_GAME},"market_freshness_verified":freshness,"odds_event_timestamp_verified":event_timestamp_verified,"recommendations_authorized":any(r.get("status")=="BET" for r in rows),"research_clv_collection_authorized":True,"shadow_calibration_can_block_decision":False,"primary_sharp_benchmark":"PINNACLE_NO_VIG","secondary_sharp_benchmark":"WEIGHTED_SHARP_CONSENSUS","threshold_policy":"research: market base + model uncertainty + consensus disagreement/lower-bound edge; shadow calibration is diagnostic only; BET: FINAL + MLB prediction timestamp 10-60m before first pitch + timestamped Odds event + sportsbook source + certified market + positive robust lower-bound edge versus Pinnacle no-vig","line_shopping_used":bool((execution_market or {}).get("selections")),"candidates":rows,"best":rows[0] if rows else None}
