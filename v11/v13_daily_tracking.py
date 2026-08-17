from __future__ import annotations

import json, math, os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from . import config, core, storage

TRACK_FILE = Path(os.getenv("V13_TRACK_FILE", "data/v13_market_tracking.jsonl"))
REPORT_FILE = Path(os.getenv("V13_TRACK_REPORT", "data/v13_market_tracking_report.json"))


def _num(x, d=None):
    try:
        y=float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


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
    state={}
    for e in (_read() if events is None else events):
        k=e.get("tracking_key")
        if k:state.setdefault(k,{}).update(e)
    return state


def _key(r,o):
    return storage.bet_key(r.get("game_pk"),o.get("market"),o.get("name"),o.get("point"))


def _price(o):
    e=o.get("winamax_eval") or {}
    p=_num(e.get("price"))
    return p if p and p>1 else None


def _nominal_ev(o,price):
    if not price:return None
    p=_num(o.get("p_win"))
    push=max(0.0,min(.95,_num(o.get("p_push"),0.0) or 0.0))
    if p is None:
        pe=_num(o.get("p_effective"))
        p=(pe*(1-push)) if pe is not None else None
    if p is None:return None
    loss=max(0.0,1-p-push)
    return p*(price-1)-loss


def capture_results(results, analyzed_at=None, target_date=None):
    at=analyzed_at or datetime.now(timezone.utc).isoformat()
    rows=[]
    for r in results or []:
        game_date=(r.get("game") or {}).get("gameDate") or (r.get("event") or {}).get("commence_time")
        for o in r.get("options") or []:
            price=_price(o); e=o.get("winamax_eval") or {}; gate=e.get("v11_price_gate") or {}
            rows.append({
                "schema":"v13-market-tracking-v1","event_type":"MODEL_SNAPSHOT","tracking_key":_key(r,o),
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


def observe_closing(results, analyzed_at=None):
    at=analyzed_at or datetime.now(timezone.utc).isoformat(); now=_dt(at) or datetime.now(timezone.utc)
    known=fold(); rows=[]
    for r in results or []:
        start=_dt((r.get("game") or {}).get("gameDate") or (r.get("event") or {}).get("commence_time"))
        mins=(start-now).total_seconds()/60 if start else None
        for o in r.get("options") or []:
            k=_key(r,o)
            if k not in known:continue
            price=_price(o); sharp=o.get("p_market")
            row={"schema":"v13-market-tracking-v1","event_type":"MARKET_UPDATE","tracking_key":k,
                 "last_market_observed_at":at,"latest_winamax_price":price,"latest_sharp_fair":sharp,
                 "minutes_to_start":round(mins,2) if mins is not None else None}
            if mins is not None and 0 < mins <= config.CLOSING_CANDIDATE_WINDOW_MIN:
                row.update({"close_price":price,"close_sharp_fair":sharp,"close_observed_at":at,"close_minutes_to_start":round(mins,2)})
                base=_num(known[k].get("winamax_price"));
                if base and price:row["price_clv_pct"]=round(base/price-1,6)
                pm=_num(known[k].get("p_market")); ps=_num(sharp)
                if pm is not None and ps is not None:row["sharp_probability_move"]=round(ps-pm,6)
            rows.append(row)
    return _append(rows)


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
        o={"market":s.get("market"),"name":s.get("pick"),"point":s.get("point"),"p_effective":s.get("p_model")}
        journal.settle_option(o,r); res=o.get("result")
        if res not in {"WIN","LOSS","PUSH"}:continue
        price=_num(s.get("winamax_price")); pnl=None
        if price and price>1:
            pnl=price-1 if res=="WIN" else -1.0 if res=="LOSS" else 0.0
        out.append({"schema":"v13-market-tracking-v1","event_type":"SETTLED","tracking_key":k,"settled_at":at,
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
    xs=list(fold().values()); settled=[x for x in xs if x.get("settled_result") in {"WIN","LOSS","PUSH"}]
    by_market={}; by_edge={}
    for market in ("ML","RUNLINE","TOTAL"):
        ms=[x for x in settled if x.get("market")==market]
        priced=[x for x in ms if _num(x.get("winamax_price")) and x.get("flat_1u_pnl") is not None]
        pos=[x for x in priced if (_num(x.get("nominal_ev"),-999) or -999)>0]
        by_market[market]={"settled":len(ms),"priced":len(priced),"positive_nominal_ev":len(pos),
                           "positive_ev_wins":sum(x.get("settled_result")=="WIN" for x in pos),
                           "positive_ev_pnl_1u":round(sum(_num(x.get("flat_1u_pnl"),0) or 0 for x in pos),4)}
        bands={}
        for x in priced:
            b=_band(_num(x.get("nominal_ev"))); d=bands.setdefault(b,{"n":0,"wins":0,"losses":0,"pushes":0,"pnl_1u":0.0})
            d["n"]+=1; d["wins"]+=x.get("settled_result")=="WIN"; d["losses"]+=x.get("settled_result")=="LOSS"; d["pushes"]+=x.get("settled_result")=="PUSH"; d["pnl_1u"]+=_num(x.get("flat_1u_pnl"),0) or 0
        for d in bands.values():d["pnl_1u"]=round(d["pnl_1u"],4); d["roi_1u"]=round(d["pnl_1u"]/max(1,d["n"]-d["pushes"]),4)
        by_edge[market]=bands
    report={"schema":"v13-market-tracking-report-v1","generated_at":datetime.now(timezone.utc).isoformat(),
            "tracked_options":len(xs),"settled_options":len(settled),"by_market":by_market,"by_nominal_ev_band":by_edge,
            "methodology":{"unit_pnl":"descriptive flat 1u; complementary displayed sides are not a betting portfolio",
                           "closing":"last eligible pregame observation inside configured closing window",
                           "missing_price":"never imputed; unpriced RL/TOTAL remain usable for probability/sharp diagnostics only"}}
    REPORT_FILE.parent.mkdir(parents=True,exist_ok=True); REPORT_FILE.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    return report
