from __future__ import annotations

import argparse, json, math, os
from datetime import datetime, timezone
from pathlib import Path
from . import config, core, storage, market

TRACK_FILE = Path(os.getenv("V13_TRACK_FILE", "data/v13_market_tracking.jsonl"))
REPORT_FILE = Path(os.getenv("V13_TRACK_REPORT", "data/v13_market_tracking_report.json"))
T60_MIN = float(os.getenv("V13_TRACK_T60_MIN", "45") or 45)
T60_MAX = float(os.getenv("V13_TRACK_T60_MAX", "75") or 75)


def _num(x, d=None):
    try:
        y=float(x)
        return y if math.isfinite(y) else d
    except Exception:return d


def _dt(x):
    try:return datetime.fromisoformat(str(x).replace("Z","+00:00"))
    except Exception:return None


def _append(rows):
    rows=list(rows)
    if not rows:return 0
    TRACK_FILE.parent.mkdir(parents=True,exist_ok=True)
    with TRACK_FILE.open("a",encoding="utf-8") as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    return len(rows)


def _read():
    if not TRACK_FILE.exists():return []
    out=[]
    for line in TRACK_FILE.read_text(encoding="utf-8").splitlines():
        try:
            r=json.loads(line)
            if isinstance(r,dict):out.append(r)
        except Exception:pass
    return out


def fold(events=None):
    """Fold event-sourced state per immutable model observation."""
    state={}
    for e in (_read() if events is None else events):
        k=e.get("tracking_key")
        if k:state.setdefault(k,{}).update(e)
    return state


def _market_key(r,o):
    return storage.bet_key(r.get("game_pk"),o.get("market"),o.get("name"),o.get("point"))


def _observation_token(r):
    phase=str(r.get("phase") or "UNKNOWN").upper()
    at=str(r.get("as_of") or r.get("analyzed_at") or "")
    run=str(r.get("run_id") or "")
    token=at or run
    return phase, token


def _key(r,o):
    base=_market_key(r,o)
    phase,token=_observation_token(r)
    return f"{base}|obs:{phase}:{token}" if token else base


def _price(o):
    p=_num((o.get("winamax_eval") or {}).get("price"))
    return p if p and p>1 else None


def _nominal_ev(o,price):
    if not price:return None
    p=_num(o.get("p_win")); push=max(0.0,min(.95,_num(o.get("p_push"),0.0) or 0.0))
    if p is None:
        pe=_num(o.get("p_effective")); p=(pe*(1-push)) if pe is not None else None
    if p is None:return None
    return p*(price-1)-max(0.0,1-p-push)


def capture_results(results, analyzed_at=None, target_date=None):
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); rows=[]
    for r in results or []:
        game_date=(r.get("game") or {}).get("gameDate") or (r.get("event") or {}).get("commence_time")
        observation_at=str(r.get("as_of") or at)
        phase=str(r.get("phase") or "EARLY").upper()
        key_ctx=dict(r); key_ctx.setdefault("analyzed_at",observation_at)
        model_generation=r.get("model_generation") or r.get("model_generation_fingerprint")
        predictive_contract=r.get("predictive_contract") or {}
        for o in r.get("options") or []:
            price=_price(o); e=o.get("winamax_eval") or {}; gate=e.get("v11_price_gate") or {}
            calibrated=o.get("p_baseball_calibrated",o.get("p_effective"))
            predictive_final=o.get("p_predictive_final",calibrated)
            rows.append({"schema":"v13-market-tracking-v4","event_type":"MODEL_SNAPSHOT","tracking_key":_key(key_ctx,o),
                "market_key":_market_key(r,o),"observation_at":observation_at,"observation_phase":phase,
                "observed_at":at,"target_date":target_date or core.TARGET_DATE,"game_pk":r.get("game_pk"),"game_date":game_date,
                "model_generation":model_generation,"predictive_contract":predictive_contract,
                "home":(r.get("ctx") or {}).get("home"),"away":(r.get("ctx") or {}).get("away"),"phase":r.get("phase"),
                "market":o.get("market"),"pick":o.get("name"),"point":o.get("point"),"canonical":bool(o.get("is_canonical_line")),
                "p_model":calibrated,"p_baseball_calibrated":calibrated,"p_raw":o.get("p_baseball_raw",o.get("p_model")),
                "p_posterior":o.get("p_posterior"),"p_predictive_final":predictive_final,
                "probability_product":o.get("probability_product"),
                "posterior_weight_v13":o.get("posterior_weight_v13"),
                "posterior_weight_source_v13":o.get("posterior_weight_source_v13"),
                "posterior_weight_games_v13":o.get("posterior_weight_games_v13"),
                "predictive_final_source":o.get("predictive_final_source"),"predictive_final_status":o.get("predictive_final_status"),
                "calibration_source_v13":o.get("calibration_source_v13"),
                "probability_interval_low":o.get("probability_interval_low"),"probability_interval_high":o.get("probability_interval_high"),
                "p_market":o.get("p_market"),"model_market_gap":o.get("model_market_gap"),"model_uncertainty":o.get("model_uncertainty"),
                "p_win":o.get("p_win"),"p_push":o.get("p_push"),"winamax_price":price,"nominal_ev":_nominal_ev(o,price),
                "conservative_ev":gate.get("ev_at_price"),"required_price":gate.get("required_price"),
                "official_selected":bool(e.get("official_selected")),"official_reason":e.get("official_reason"),
                "data_quality":o.get("data_quality"),"selection_score":o.get("selection_score")})
    return _append(rows)


def _market_update(k, known, at, mins, price, sharp, poll_reason=None):
    row={"schema":"v13-market-tracking-v4","event_type":"MARKET_UPDATE","tracking_key":k,
         "last_market_observed_at":at,"minutes_to_start":round(mins,2) if mins is not None else None,
         "market_poll_reason":poll_reason}
    if price is not None: row["latest_winamax_price"] = price
    if sharp is not None: row["latest_sharp_fair"] = sharp
    if poll_reason=="t60" and (price is not None or sharp is not None):
        row["t60_observed_at"]=at; row["t60_minutes_to_start"]=round(mins,2) if mins is not None else None
        if price is not None: row["t60_price"]=price
        if sharp is not None: row["t60_sharp_fair"]=sharp
    close_window=float(getattr(config,"CLOSING_CANDIDATE_WINDOW_MIN",20) or 20)
    if mins is not None and 0 < mins <= close_window and (price is not None or sharp is not None):
        row["close_observed_at"]=at; row["close_minutes_to_start"]=round(mins,2)
        if price is not None:
            row["close_price"]=price
            base=_num(known.get("winamax_price"))
            if base:row["price_clv_pct"]=round(base/price-1,6)
        if sharp is not None:
            row["close_sharp_fair"]=sharp
            pm=_num(known.get("p_market")); ps=_num(sharp)
            if pm is not None and ps is not None:row["sharp_probability_move"]=round(ps-pm,6)
    return row


def _matching_observation_keys(known, r, o):
    direct=_key(r,o)
    if direct in known:return [direct]
    base=_market_key(r,o); phase=str(r.get("phase") or "").upper()
    matches=[k for k,s in known.items() if (s.get("market_key") or k.split("|obs:",1)[0])==base
             and (not phase or str(s.get("phase") or s.get("observation_phase") or "").upper()==phase)]
    return matches


def observe_closing(results, analyzed_at=None):
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); now=_dt(at) or datetime.now(timezone.utc); known=fold(); rows=[]
    for r in results or []:
        start=_dt((r.get("game") or {}).get("gameDate") or (r.get("event") or {}).get("commence_time")); mins=(start-now).total_seconds()/60 if start else None
        for o in r.get("options") or []:
            for k in _matching_observation_keys(known,r,o):
                reason=_poll_reason_for_state(known[k],now)
                rows.append(_market_update(k,known[k],at,mins,_price(o),o.get("p_market"),reason))
    return _append(rows)


def _poll_reason_for_state(state, now=None, horizon_min=150):
    now=now or datetime.now(timezone.utc)
    if state.get("settled_result") in {"WIN","LOSS","PUSH"}:return None
    start=_dt(state.get("game_date"))
    if not start:return None
    mins=(start-now).total_seconds()/60
    if mins<=0 or mins>horizon_min:return None
    close_window=float(getattr(config,"CLOSING_CANDIDATE_WINDOW_MIN",20) or 20)
    if 0 < mins <= close_window and not state.get("close_observed_at"):
        return "close"
    if T60_MIN <= mins <= T60_MAX and not state.get("t60_observed_at"):
        return "t60"
    return None


def needs_market_poll(now=None, horizon_min=150):
    now=now or datetime.now(timezone.utc)
    return any(_poll_reason_for_state(s,now,horizon_min) for s in fold().values())


def _event_for_state(events,s):
    h,a=core.norm_name(s.get("home")),core.norm_name(s.get("away"))
    for e in events or []:
        if core.norm_name(e.get("home_team"))==h and core.norm_name(e.get("away_team"))==a:return e
    return None


def _winamax_price_from_event(event,s):
    key={"ML":"h2h","RUNLINE":"spreads","TOTAL":"totals"}.get(str(s.get("market") or "").upper())
    if not key:return None
    point=_num(s.get("point")); pick=core.norm_name(s.get("pick"))
    for b in event.get("bookmakers") or []:
        if b.get("key")!=core.WINAMAX_KEY:continue
        for m in b.get("markets") or []:
            if m.get("key")!=key:continue
            for o in m.get("outcomes") or []:
                if core.norm_name(o.get("name"))!=pick:continue
                if key!="h2h" and (point is None or abs((_num(o.get("point"),999) or 999)-point)>1e-9):continue
                p=_num(o.get("price"));
                if p and p>1:return p
    return None


def snapshot_market(analyzed_at=None):
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); now=_dt(at) or datetime.now(timezone.utc)
    state=fold(); due={k:_poll_reason_for_state(s,now) for k,s in state.items()}
    due={k:v for k,v in due.items() if v}
    if not due:return 0
    # One paid Odds API call serves every game currently due for T-60/close.
    events=core.odds_api(); rows=[]
    for k,reason in due.items():
        s=state[k]
        start=_dt(s.get("game_date")); mins=(start-now).total_seconds()/60 if start else None
        e=_event_for_state(events,s)
        if not e:continue
        price=_winamax_price_from_event(e,s); sharp=None
        try:
            sharp=(market.sharp_consensus(e,str(s.get("market") or ""),s.get("pick"),s.get("point"),as_of=at) or {}).get("p")
        except Exception:sharp=None
        rows.append(_market_update(k,s,at,mins,price,sharp,reason))
    n=_append(rows); write_report(); return n


def settle_from_journal(journal_rows, settled_at=None):
    at=settled_at or datetime.now(timezone.utc).isoformat(); finals={}
    for r in journal_rows or []:
        if r.get("result_status")!="FINAL" or not r.get("game_pk"):continue
        gid=str(r["game_pk"]); rank=str(r.get("analyzed_at") or "")
        if gid not in finals or rank>finals[gid][0]:finals[gid]=(rank,r)
    state=fold(); out=[]
    from . import journal
    for k,s in state.items():
        if s.get("settled_result") in {"WIN","LOSS","PUSH"}:continue
        r=(finals.get(str(s.get("game_pk"))) or (None,None))[1]
        if not r:continue
        o={"market":s.get("market"),"name":s.get("pick"),"point":s.get("point"),"p_effective":s.get("p_model")}; journal.settle_option(o,r); res=o.get("result")
        if res not in {"WIN","LOSS","PUSH"}:continue
        price=_num(s.get("winamax_price")); pnl=(price-1 if res=="WIN" else -1.0 if res=="LOSS" else 0.0) if price and price>1 else None
        out.append({"schema":"v13-market-tracking-v4","event_type":"SETTLED","tracking_key":k,"settled_at":at,
                    "settled_result":res,"flat_1u_pnl":pnl,"home_score":r.get("home_score"),"away_score":r.get("away_score")})
    n=_append(out); write_report(); return n


def _band(ev):
    if ev is None:return "unpriced"
    x=100*ev
    if x<0:return "<0%"
    if x<1:return "0-1%"
    if x<3:return "1-3%"
    if x<5:return "3-5%"
    if x<10:return "5-10%"
    return ">=10%"


def write_report():
    xs=list(fold().values()); settled=[x for x in xs if x.get("settled_result") in {"WIN","LOSS","PUSH"}]; by_market={}; by_edge={}
    for market_name in ("ML","RUNLINE","TOTAL"):
        ms=[x for x in settled if x.get("market")==market_name]; priced=[x for x in ms if _num(x.get("winamax_price")) and x.get("flat_1u_pnl") is not None]
        pos=[x for x in priced if (_num(x.get("nominal_ev"),-999) or -999)>0]
        by_market[market_name]={"settled":len(ms),"priced":len(priced),"positive_nominal_ev":len(pos),"positive_ev_wins":sum(x.get("settled_result")=="WIN" for x in pos),"positive_ev_pnl_1u":round(sum(_num(x.get("flat_1u_pnl"),0) or 0 for x in pos),4),"t60_sharp_observed":sum(x.get("t60_sharp_fair") is not None for x in ms),"closing_price_observed":sum(x.get("close_price") is not None for x in ms),"closing_sharp_observed":sum(x.get("close_sharp_fair") is not None for x in ms)}
        bands={}
        for x in priced:
            b=_band(_num(x.get("nominal_ev"))); d=bands.setdefault(b,{"n":0,"wins":0,"losses":0,"pushes":0,"pnl_1u":0.0})
            d["n"]+=1; d["wins"]+=x.get("settled_result")=="WIN"; d["losses"]+=x.get("settled_result")=="LOSS"; d["pushes"]+=x.get("settled_result")=="PUSH"; d["pnl_1u"]+=_num(x.get("flat_1u_pnl"),0) or 0
        for d in bands.values():d["pnl_1u"]=round(d["pnl_1u"],4); d["roi_1u"]=round(d["pnl_1u"]/max(1,d["n"]-d["pushes"]),4)
        by_edge[market_name]=bands
    report={"schema":"v13-market-tracking-report-v4","generated_at":datetime.now(timezone.utc).isoformat(),
            "tracked_observations":len(xs),"settled_observations":len(settled),"tracked_options":len(xs),"settled_options":len(settled),
            "by_market":by_market,"by_nominal_ev_band":by_edge,
            "methodology":{"observation_identity":"immutable game/market/side/line + phase + analysis as-of; later phases never overwrite earlier forecasts","unit_pnl":"descriptive flat 1u; complementary displayed sides are not a betting portfolio","closing":"paid market polling is checkpoint-based: one T-60 window and one close window per tracked observation, batched in a single Odds API request across all games due at that time","missing_price":"never imputed; absent Winamax RL/TOTAL prices remain unpriced and are still tracked against sharp probability","probability_products":"raw baseball, calibrated baseball, learned-weight posterior shadow, and primary predictive probability are persisted separately","generation_identity":"every new model snapshot persists model_generation and predictive_contract; legacy rows remain historical-only"}}
    REPORT_FILE.parent.mkdir(parents=True,exist_ok=True); REPORT_FILE.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8"); return report


def main():
    p=argparse.ArgumentParser(); p.add_argument("--needs-poll",action="store_true"); p.add_argument("--snapshot-market",action="store_true"); p.add_argument("--report",action="store_true"); a=p.parse_args()
    if a.needs_poll: print("true" if needs_market_poll() else "false")
    elif a.snapshot_market: print(json.dumps({"market_updates":snapshot_market()}))
    elif a.report: print(json.dumps(write_report(),indent=2))


if __name__=="__main__":main()