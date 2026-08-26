from __future__ import annotations

"""Fail-closed, market-specific betting decision diagnostics for Pulsar V14."""

import math
from typing import Any

BASE_MODEL_EDGE_PP={"ML":3.0,"RL":4.0,"TOTAL":4.0}
BASE_ROBUST_EDGE_PP={"ML":2.0,"RL":3.0,"TOTAL":3.0}
SELECTIONS={"ML":{"home":"home_ml","away":"away_ml"},"RL":{"home_-1.5":"home_minus_1_5","away_+1.5":"away_plus_1_5","away_-1.5":"away_minus_1_5","home_+1.5":"home_plus_1_5"},"TOTAL":{"over":"over","under":"under"}}
CALIBRATION_MARKET={"home_ml":"ML","away_ml":"ML","home_minus_1_5":"RL_HOME_-1.5","away_plus_1_5":"RL_HOME_-1.5","away_minus_1_5":"RL_AWAY_-1.5","home_plus_1_5":"RL_AWAY_-1.5","over":"TOTAL_OVER","under":"TOTAL_OVER"}


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _execution_rows(snapshot:dict[str,Any])->list[tuple[str,str,float,str|None]]:
    rows=[]; markets=snapshot.get("markets") or {}
    for market,mapping in SELECTIONS.items():
        block=markets.get(market) or {}; selections=block.get("selections") or {}; book=block.get("bookmaker")
        for label,key in mapping.items():
            price=_num((selections.get(label) or {}).get("price"))
            if price and price>1: rows.append((key,market,price,str(book) if book else None))
    return rows


def _calibration_ok(meta:dict[str,Any])->bool:
    return meta.get("accepted") is True or meta.get("active") is True


def _certified_market(certification:dict[str,Any],canonical_market:str)->bool:
    markets=certification.get("markets") or {}
    if markets: return ((markets.get(canonical_market) or {}).get("betting_certified") is True)
    # Backward-compatible fail-safe for legacy synthetic tests/artifacts.
    return certification.get("certified") is True


def _thresholds(market:str,interval:dict[str,Any],sharp_row:dict[str,Any])->tuple[float,float,dict[str,float]]:
    width=_num(interval.get("half_width_pp")) or 10.0; sharp_disp=_num(sharp_row.get("dispersion_pp")) or 0.0; sharp_range=_num(sharp_row.get("range_pp")) or 0.0
    # Wider model uncertainty and disagreement among sharp books demand more edge.
    uncertainty_penalty=max(0.0,(width-5.0)*0.12); disagreement_penalty=min(2.5,0.35*sharp_disp+0.08*sharp_range)
    model=BASE_MODEL_EDGE_PP[market]+uncertainty_penalty+disagreement_penalty; robust=BASE_ROBUST_EDGE_PP[market]+0.5*disagreement_penalty
    return model,robust,{"uncertainty_penalty_pp":uncertainty_penalty,"sharp_disagreement_penalty_pp":disagreement_penalty}


def evaluate(*,prediction:dict[str,Any],market_snapshot:dict[str,Any],sharp_market:dict[str,Any],certification:dict[str,Any],starter_degraded:bool=False)->dict[str,Any]:
    probs=prediction.get("probabilities") or {}; intervals=(prediction.get("probability_intervals") or {}).get("selections") or {}; calibration=prediction.get("calibration") or {}; sharp=sharp_market.get("selections") or {}
    freshness=market_snapshot.get("freshness_verified") is True and sharp_market.get("freshness_verified") is True; rows=[]
    for key,market,price,book in _execution_rows(market_snapshot):
        p=_num(probs.get(key))
        if p is None: continue
        interval=intervals.get(key) or {}; lower=_num(interval.get("lower")); lower=lower if lower is not None else max(0.0,p-.10); breakeven=1/price; sharp_row=sharp.get(key) or {}; sharp_p=_num(sharp_row.get("fair_probability")); model_edge=100*(p-breakeven); robust_edge=100*(lower-breakeven); sharp_edge=100*(p-sharp_p) if sharp_p is not None else None
        canonical=CALIBRATION_MARKET.get(key) or ""; cal_meta=(calibration.get("markets") or {}).get(canonical) or {}; blockers=[]
        if starter_degraded: blockers.append("starter_degraded")
        if not freshness: blockers.append("unverified_market_freshness")
        if not _calibration_ok(cal_meta): blockers.append("calibration_not_accepted")
        if sharp_p is None: blockers.append("sharp_consensus_missing")
        model_threshold,robust_threshold,penalties=_thresholds(market,interval,sharp_row)
        edge_qualified=model_edge>=model_threshold and robust_edge>=robust_threshold and sharp_edge is not None and sharp_edge>0
        research_ready=edge_qualified and not blockers
        market_certified=_certified_market(certification,canonical)
        if not market_certified: blockers.append(f"{canonical or market}_betting_not_certified")
        status="BET" if edge_qualified and not blockers else ("RESEARCH_ONLY" if research_ready else "NO_BET")
        rows.append({"selection":key,"canonical_market":canonical,"market":market,"execution_book":book,"price":price,"probability":p,"lower_probability":lower,"break_even_probability":breakeven,"model_edge_pp":model_edge,"robust_edge_pp":robust_edge,"sharp_edge_pp":sharp_edge,"sharp_dispersion_pp":_num(sharp_row.get("dispersion_pp")),"model_edge_threshold_pp":model_threshold,"robust_edge_threshold_pp":robust_threshold,**penalties,"edge_qualified":edge_qualified,"research_ready":research_ready,"market_betting_certified":market_certified,"status":status,"blockers":blockers})
    rows.sort(key=lambda r:r.get("robust_edge_pp") if r.get("robust_edge_pp") is not None else -999,reverse=True)
    return {"schema":"pulsar-v14-decision-diagnostics-v3","betting_certified":any(r.get("market_betting_certified") for r in rows),"starter_degraded":bool(starter_degraded),"market_freshness_verified":freshness,"recommendations_authorized":any(r.get("status")=="BET" for r in rows),"research_clv_collection_authorized":True,"threshold_policy":"market base + model uncertainty + sharp disagreement","candidates":rows,"best":rows[0] if rows else None}
