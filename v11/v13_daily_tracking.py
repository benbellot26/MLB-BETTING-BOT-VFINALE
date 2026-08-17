from __future__ import annotations

import argparse, json, math, os
from datetime import datetime, timezone
from pathlib import Path
from . import config, core, storage, market

TRACK_FILE = Path(os.getenv("V13_TRACK_FILE", "data/v13_market_tracking.jsonl"))
REPORT_FILE = Path(os.getenv("V13_TRACK_REPORT", "data/v13_market_tracking_report.json"))


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
    """Fold event-sourced state per immutable model observation.

    Since V13.5.1, MODEL_SNAPSHOT tracking keys include phase + run/as-of. Market
    updates and settlement events therefore enrich one exact forecast instead of
    overwriting another EARLY/LATE/FINAL forecast for the same bet line.
    Legacy pre-V13.5.1 keys remain readable for backward compatibility.
    """
    state={}
    for e in (_read() if events is None else events):
        k=e.get("tracking_key")
        if k:state.setdefault(k,{}).update(e)
    return state


def _market_key(r,o):
    return storage.bet_key(r.get("game_pk"),o.get("market"),o.get("name"),o.get("point"))


def _observation_token(r):
    phase=str(r.get("phase") or "UNKNOWN").upper()
    run=str(r.get("run_id") or "")
    at=str(r.get("as_of") or r.get("analyzed_at") or "")
    token=run or at
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
        for o in r.get("options") or []:
            price=_price(o); e=o.get("winamax_eval") or {}; gate=e.get("v11_price_gate") or {}
            rows.append({"schema":"v13-market-tracking-v3","event_type":"MODEL_SNAPSHOT","tracking_key":_key(r,o),
                "market_key":_market_key(r,o),"observation_at":observation_at,"observation_phase":phase,
                "observed_at":at,"target_date":target_date or core.TARGET_DATE,"game_pk":r.get("game_pk"),"game_date":game_date,
                "home":(r.get("ctx") or {}).get("home"),"away":(r.get("ctx") or {}).get("away"),"phase":r.get("phase"),
                "market":o.get("market"),"pick":o.get("name"),"point":o.get("point"),"canonical":bool(o.get("is_canonical_line")),
                "p_model":o.get("p_baseball_calibrated",o.get("p_effective")),"p_raw":o.get("p_baseball_raw",o.get("p_model")),
                "p_market":o.get("p_market"),"model_market_gap":o.get("model_market_gap"),"model_uncertainty":o.get("model_uncertainty"),
                "p_win":o.get("p_win"),"p_push":o.get("p_push"),"winamax_price":price,"nominal_ev":_nominal_ev(o,price),
                "conservative_ev":gate.get("ev_at_price"),"required_price":gate.get("required_price"),
                "official_selected":bool(e.get("official_selected")),"official_reason":e.get("official_reason"),
                "data_quality":o.get("data_quality"),"selection_score":o.get("selection_score")})
    return _append(rows)


def _market_update(k, known, at, mins, price, sharp):
    row={"schema":"v13-market-tracking-v3","event_type":"MARKET_UPDATE","tracking_key":k,
         "last_market_observed_at":at,"minutes_to_start":round(mins,2) if mins is not None else None}
    if price is not None: row["latest_winamax_price"] = price
    if sharp is not None: row["latest_sharp_fair"] = sharp
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


def observe_closing(results, analyzed_at=None):
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); now=_dt(at) or datetime.now(timezone.utc); known=fold(); rows=[]
    for r in results or []:
        start=_dt((r.get("game") or {}).get("gameDate") or (r.get("event") or {}).get("commence_time")); mins=(start-now).total_seconds()/60 if start else None
        for o in r.get("options") or []:
            k=_key(r,o)
            if k in known:rows.append(_market_update(k,known[k],at,mins,_price(o),o.get("p_market")))
    return _append(rows)


def needs_market_poll(now=None, horizon_min=150):
    now=now or datetime.now(timezone.utc)
    for s in fold().values():
        if s.get("settled_result") in {"WIN","LOSS","PUSH"}:continue
        start=_dt(s.get("game_date"))
        if not start:continue
        mins=(start-now).total_seconds()/60
        if 0 < mins <= horizon_min:return True
    return False


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
    if not needs_market_poll(now):return 0
    events=core.odds_api(); state=fold(); rows=[]
    for k,s in state.items():
        if s.get("settled_result") in {"WIN","LOSS","PUSH"}:continue
        start=_dt(s.get("game_date")); mins=(start-now).total_seconds()/60 if start else None
        if mins is None or mins<=0 or mins>150:continue
        e=_event_for_state(events,s)
        if not e:continue
        price=_winamax_price_from_event(e,s); sharp=None
        try:
            sharp=(market.sharp_consensus(e,str(s.get("market") or ""),s.get("pick"),s.get("point"),as_of=at) or {}).get("p")
        except Exception:sharp=None
        rows.append(_market_update(k,s,at,mins,price,sharp))
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
        out.append({"schema":"v13-market-tracking-v3","event_type":"SETTLED","tracking_key":k,"settled_at":at,
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
        by_market[market_name]={"settled":len(ms),"priced":len(priced),"positive_nominal_ev":len(pos),"positive_ev_wins":sum(x.get("settled_result")=="WIN" for x in pos),"positive_ev_pnl_1u":round(sum(_num(x.get("flat_1u_pnl"),0) or 0 for x in pos),4),"closing_price_observed":sum(x.get("close_price") is not None for x in ms),"closing_sharp_observed":sum(x.get("close_sharp_fair") is not None for x in ms)}
        bands={}
        for x in priced:
            b=_band(_num(x.get("nominal_ev"))); d=bands.setdefault(b,{"n":0,"wins":0,"losses":0,"pushes":0,"pnl_1u":0.0})
            d["n"]+=1; d["wins"]+=x.get("settled_result")=="WIN"; d["losses"]+=x.get("settled_result")=="LOSS"; d["pushes"]+=x.get("settled_result")=="PUSH"; d["pnl_1u"]+=_num(x.get("flat_1u_pnl"),0) or 0
        for d in bands.values():d["pnl_1u"]=round(d["pnl_1u"],4); d["roi_1u"]=round(d["pnl_1u"]/max(1,d["n"]-d["pushes"]),4)
        by_edge[market_name]=bands
    report={"schema":"v13-market-tracking-report-v3","generated_at":datetime.now(timezone.utc).isoformat(),"tracked_observations":len(xs),"settled_observations":len(settled),"by_market":by_market,"by_nominal_ev_band":by_edge,"methodology":{"observation_identity":"immutable game/market/side/line + phase + run/as-of; later phases never overwrite earlier forecasts","unit_pnl":"descriptive flat 1u; complementary displayed sides are not a betting portfolio","closing":"last valid eligible pregame observation inside configured closing window; missing API fields never erase a valid close","missing_price":"never imputed; absent Winamax RL/TOTAL prices remain unpriced and are still tracked against sharp probability"}}
    REPORT_FILE.parent.mkdir(parents=True,exist_ok=True); REPORT_FILE.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8"); return report


def main():
    p=argparse.ArgumentParser(); p.add_argument("--needs-poll",action="store_true"); p.add_argument("--snapshot-market",action="store_true"); p.add_argument("--report",action="store_true"); a=p.parse_args()
    if a.needs_poll: print("true" if needs_market_poll() else "false")
    elif a.snapshot_market: print(json.dumps({"market_updates":snapshot_market()}))
    elif a.report: print(json.dumps(write_report(),indent=2))


if __name__=="__main__":main()
