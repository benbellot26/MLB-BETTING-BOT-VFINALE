from __future__ import annotations

import json
from datetime import datetime, timezone
from . import core, journal
from . import v13_daily_tracking as tracking


def _latest_pregame_rows():
    """Return latest immutable pregame row per game and phase.

    EARLY/LATE/FINAL remain separate model observations in the journal. Promotion
    statistics later collapse them to one unique game when a pooled sample is
    required, so storage fidelity and statistical independence are both kept.
    """
    best={}
    for r in journal.load_rows():
        if not r.get("game_pk") or not r.get("options"):continue
        an=tracking._dt(r.get("analyzed_at")); start=tracking._dt(r.get("game_date"))
        if not an or not start or an>=start:continue
        phase=str(r.get("phase") or "EARLY").upper()
        key=(str(r.get("game_pk")),phase); rank=str(r.get("analyzed_at") or "")
        if key not in best or rank>best[key][0]:best[key]=(rank,r)
    return [x[1] for x in best.values()]


def sync_from_journal():
    state=tracking.fold(); rows=[]
    for r in _latest_pregame_rows():
        phase=str(r.get("phase") or "EARLY").upper()
        model_generation=r.get("model_generation") or r.get("model_generation_fingerprint")
        predictive_contract=r.get("predictive_contract") or {}
        for o in r.get("options") or []:
            k=tracking._key(r,o)
            existing=state.get(k)
            if existing is not None:
                # Old tracking rows predate generation identity. The persisted
                # journal still contains the immutable source snapshot, so it is
                # safe to attest missing identity metadata without changing the
                # probability or market observation itself.
                if (not existing.get("model_generation") or not existing.get("predictive_contract")) and model_generation and predictive_contract:
                    rows.append({"schema":"v13-market-tracking-v4","event_type":"MODEL_IDENTITY_ATTESTATION",
                                 "tracking_key":k,"model_generation":model_generation,
                                 "predictive_contract":predictive_contract,"identity_source":"persisted-v13-journal"})
                continue
            e=o.get("winamax_eval") or {}; gate=e.get("v11_price_gate") or {}
            price=tracking._num(e.get("price")); price=price if price and price>1 else None
            calibrated=o.get("p_baseball_calibrated",o.get("p_effective"))
            predictive=o.get("p_predictive_final",calibrated)
            rows.append({"schema":"v13-market-tracking-v4","event_type":"MODEL_SNAPSHOT","tracking_key":k,
                "market_key":tracking._market_key(r,o),"observation_at":r.get("analyzed_at"),"observation_phase":phase,
                "source":"persisted-v13-journal","source_run_id":r.get("run_id"),"observed_at":r.get("analyzed_at"),
                "target_date":r.get("target_date"),"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),
                "model_generation":model_generation,"predictive_contract":predictive_contract,
                "home":r.get("home"),"away":r.get("away"),"phase":r.get("phase"),"market":o.get("market"),
                "pick":o.get("name"),"point":o.get("point"),"canonical":bool(o.get("is_canonical_line")),
                "p_model":calibrated,"p_baseball_calibrated":calibrated,"p_raw":o.get("p_baseball_raw",o.get("p_model")),
                "p_posterior":o.get("p_posterior"),"p_predictive_final":predictive,
                "probability_product":o.get("probability_product"),
                "posterior_weight_v13":o.get("posterior_weight_v13"),
                "posterior_weight_source_v13":o.get("posterior_weight_source_v13"),
                "posterior_weight_games_v13":o.get("posterior_weight_games_v13"),
                "predictive_final_source":o.get("predictive_final_source"),"predictive_final_status":o.get("predictive_final_status"),
                "calibration_source_v13":o.get("calibration_source_v13"),
                "probability_interval_low":o.get("probability_interval_low"),"probability_interval_high":o.get("probability_interval_high"),
                "p_market":o.get("p_market"),"model_market_gap":o.get("model_market_gap"),"model_uncertainty":o.get("model_uncertainty"),
                "p_win":o.get("p_win"),"p_push":o.get("p_push"),"winamax_price":price,
                "nominal_ev":tracking._nominal_ev(o,price),"conservative_ev":gate.get("ev_at_price"),
                "required_price":gate.get("required_price"),"official_selected":bool(e.get("official_selected")),
                "official_reason":e.get("official_reason"),"data_quality":o.get("data_quality"),"selection_score":o.get("selection_score")})
    return tracking._append(rows)


def settle_live_results(now=None):
    now=now or datetime.now(timezone.utc); state=tracking.fold(); days=set()
    for s in state.values():
        if s.get("settled_result") in {"WIN","LOSS","PUSH"}:continue
        start=tracking._dt(s.get("game_date"))
        if start and start < now:days.add(str(s.get("target_date") or start.date().isoformat()))
    finals=[]
    for day in sorted(days):
        try: games=core.mlb_schedule(day)
        except Exception:continue
        for g in games or []:
            status=g.get("status") or {}; final=(str(status.get("abstractGameState") or "").lower()=="final" or str(status.get("codedGameState") or "").upper()=="F")
            if not final:continue
            teams=g.get("teams") or {}; hs=(teams.get("home") or {}).get("score"); aps=(teams.get("away") or {}).get("score")
            if hs is None or aps is None:continue
            home=((teams.get("home") or {}).get("team") or {}).get("name"); away=((teams.get("away") or {}).get("team") or {}).get("name")
            finals.append({"game_pk":g.get("gamePk"),"result_status":"FINAL","analyzed_at":now.isoformat(),"home":home,"away":away,"home_score":hs,"away_score":aps})
    return tracking.settle_from_journal(finals, settled_at=now.isoformat()) if finals else 0


def main():
    synced=sync_from_journal(); polled=0
    if core.ODDS_KEY and tracking.needs_market_poll():
        try:polled=tracking.snapshot_market()
        except Exception as exc:core.logging.warning("V13 tracking market poll failed: %s",exc)
    settled=settle_live_results(); report=tracking.write_report()
    print(json.dumps({"synced_model_options":synced,"market_updates":polled,"settled":settled,"tracked_observations":report.get("tracked_observations"),"settled_observations":report.get("settled_observations")},indent=2))


if __name__=="__main__":main()
