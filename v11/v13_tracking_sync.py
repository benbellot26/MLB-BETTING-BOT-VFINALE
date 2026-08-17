from __future__ import annotations

import json
from datetime import datetime, timezone
from . import core, journal
from . import v13_daily_tracking as tracking


def _latest_pregame_rows():
    """Return latest immutable pregame row per game and phase.

    EARLY/LATE/FINAL must remain separate evidence streams. The pre-V13.5.1
    implementation kept only the latest row per game and silently discarded
    earlier phases during sync.
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
        for o in r.get("options") or []:
            k=tracking._key(r,o)
            if k in state:continue
            e=o.get("winamax_eval") or {}; gate=e.get("v11_price_gate") or {}
            price=tracking._num(e.get("price")); price=price if price and price>1 else None
            rows.append({"schema":"v13-market-tracking-v3","event_type":"MODEL_SNAPSHOT","tracking_key":k,
                "market_key":tracking._market_key(r,o),"observation_at":r.get("analyzed_at"),"observation_phase":phase,
                "source":"persisted-v13-journal","source_run_id":r.get("run_id"),"observed_at":r.get("analyzed_at"),
                "target_date":r.get("target_date"),"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),
                "home":r.get("home"),"away":r.get("away"),"phase":r.get("phase"),"market":o.get("market"),
                "pick":o.get("name"),"point":o.get("point"),"canonical":bool(o.get("is_canonical_line")),
                "p_model":o.get("p_baseball_calibrated",o.get("p_effective")),"p_raw":o.get("p_baseball_raw",o.get("p_model")),
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
