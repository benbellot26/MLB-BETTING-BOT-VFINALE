from __future__ import annotations

import argparse, json, math, os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import core, v13_daily_tracking as tracking, v13_tracking_sync

OUT = Path(os.getenv("V13_DAILY_POSTMORTEM_FILE", "data/v13_daily_postmortem.json"))
PARIS = ZoneInfo("Europe/Paris")


def _num(x, d=None):
    try:
        y=float(x)
        return y if math.isfinite(y) else d
    except Exception:return d


def _logloss(p,y):
    p=max(.001,min(.999,float(p)))
    return -(y*math.log(p)+(1-y)*math.log(1-p))


def _result_y(s):
    r=s.get("settled_result")
    return 1 if r=="WIN" else 0 if r=="LOSS" else None


def _independent_key(s):
    market=str(s.get("market") or "").upper()
    gid=str(s.get("game_pk") or "")
    point=s.get("point")
    if market=="ML": return (gid,market,"game")
    if market=="TOTAL": return (gid,market,str(point))
    if market=="RUNLINE": return (gid,market,str(abs(_num(point,0) or 0)))
    return (gid,market,str(point))


def _choose_independent(states):
    groups=defaultdict(list)
    for s in states:
        if _result_y(s) is None: continue
        groups[_independent_key(s)].append(s)
    chosen=[]
    for xs in groups.values():
        # Prefer the home side for team markets and Over for totals so the rule
        # is deterministic and never uses the outcome to choose the side.
        market=str(xs[0].get("market") or "").upper()
        pick=None
        if market=="TOTAL": pick=next((x for x in xs if str(x.get("pick") or "").lower()=="over"),None)
        else:
            home=str(xs[0].get("home") or "")
            pick=next((x for x in xs if str(x.get("pick") or "")==home),None)
        chosen.append(pick or sorted(xs,key=lambda x:str(x.get("pick") or ""))[0])
    return chosen


def _calibration_bins(rows, field):
    bins=[(0,.45),(.45,.50),(.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,1.001)]
    out=[]
    for lo,hi in bins:
        xs=[r for r in rows if _num(r.get(field)) is not None and lo<=_num(r.get(field))<hi]
        if not xs: continue
        out.append({"lo":lo,"hi":hi,"n":len(xs),"mean_p":round(sum(_num(x[field]) for x in xs)/len(xs),4),
                    "win_rate":round(sum(_result_y(x) for x in xs)/len(xs),4)})
    return out


def _market_metrics(rows):
    independent=_choose_independent(rows)
    model=[x for x in independent if _num(x.get("p_model")) is not None]
    sharp=[x for x in independent if _num(x.get("p_market")) is not None]
    def scores(xs,field):
        if not xs:return {"n":0,"brier":None,"logloss":None}
        b=sum((_num(x[field])-_result_y(x))**2 for x in xs)/len(xs)
        ll=sum(_logloss(_num(x[field]),_result_y(x)) for x in xs)/len(xs)
        return {"n":len(xs),"brier":round(b,6),"logloss":round(ll,6)}
    priced=[x for x in rows if _num(x.get("winamax_price")) and x.get("flat_1u_pnl") is not None]
    selected=[x for x in priced if x.get("official_selected")]
    rejected=[x for x in priced if not x.get("official_selected")]
    close=[x for x in rows if _num(x.get("close_sharp_fair")) is not None and _num(x.get("p_model")) is not None]
    clv=[_num(x.get("close_sharp_fair"))-_num(x.get("p_model")) for x in close]
    pos_rejected=[x for x in rejected if (_num(x.get("nominal_ev"),-999) or -999)>0]
    return {
        "independent_targets":len(independent),
        "model":scores(model,"p_model"),"sharp":scores(sharp,"p_market"),
        "calibration_model":_calibration_bins(model,"p_model"),
        "selected":{"n":len(selected),"wins":sum(x.get("settled_result")=="WIN" for x in selected),
                    "losses":sum(x.get("settled_result")=="LOSS" for x in selected),
                    "pushes":sum(x.get("settled_result")=="PUSH" for x in selected),
                    "pnl_1u":round(sum(_num(x.get("flat_1u_pnl"),0) or 0 for x in selected),4)},
        "rejected_priced":len(rejected),"positive_ev_rejected":len(pos_rejected),
        "positive_ev_rejected_wins":sum(x.get("settled_result")=="WIN" for x in pos_rejected),
        "mean_model_minus_close_sharp":round(-sum(clv)/len(clv),6) if clv else None,
        "closing_sharp_n":len(clv),
    }


def build(day=None):
    if day is None:
        day=(datetime.now(PARIS).date()-timedelta(days=1)).isoformat()
    states=[s for s in tracking.fold().values() if str(s.get("target_date") or "")==str(day) and s.get("settled_result") in {"WIN","LOSS","PUSH"}]
    by_market={m:_market_metrics([s for s in states if str(s.get("market") or "").upper()==m]) for m in ("ML","RUNLINE","TOTAL")}
    priced=[s for s in states if _num(s.get("winamax_price")) and s.get("flat_1u_pnl") is not None]
    selected=[s for s in priced if s.get("official_selected")]
    report={"schema":"v13-daily-postmortem-v1","generated_at":datetime.now(timezone.utc).isoformat(),"target_date":day,
            "settled_options":len(states),"priced_options":len(priced),"official_selected":len(selected),
            "official_pnl_1u":round(sum(_num(s.get("flat_1u_pnl"),0) or 0 for s in selected),4),"markets":by_market,
            "methodology":{"probability_scoring":"one deterministic independent side per game/line; complementary sides are not double-counted",
                           "portfolio_pnl":"official selections only; rejected options are diagnostic only",
                           "clv":"model probability minus latest valid pregame sharp fair probability"}}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    return report


def _fmt_metric(m):
    if not m.get("n"):return "n=0"
    return f"n={m['n']} • Brier {m['brier']:.4f} • LogLoss {m['logloss']:.4f}"


def discord_fields(report):
    fields=[]
    for market in ("ML","RUNLINE","TOTAL"):
        m=report["markets"][market]; selected=m["selected"]
        sharp=m["sharp"]; model=m["model"]
        delta=None if not model.get("n") or not sharp.get("n") else sharp["brier"]-model["brier"]
        fields.append((market,
            f"Model: {_fmt_metric(model)}\nSharp: {_fmt_metric(sharp)}\n"
            f"Brier edge vs sharp: {'—' if delta is None else f'{delta:+.4f}'}\n"
            f"Official: {selected['wins']}W-{selected['losses']}L-{selected['pushes']}P • P/L {selected['pnl_1u']:+.2f}u\n"
            f"Rejected +EV: {m['positive_ev_rejected']} ({m['positive_ev_rejected_wins']} wins) • Closing sharp n={m['closing_sharp_n']}"))
    return fields


def send(report):
    if not core.DISCORD_URL:return False
    title=f"📊 V13 DAILY POST-MORTEM — {report['target_date']}"
    desc=(f"{report['settled_options']} options settled • {report['priced_options']} priced • "
          f"{report['official_selected']} official • P/L {report['official_pnl_1u']:+.2f}u")
    return core.send_embed(title,discord_fields(report),5763719,desc)


def main():
    p=argparse.ArgumentParser(); p.add_argument("--date"); p.add_argument("--send",action="store_true"); p.add_argument("--sync",action="store_true"); a=p.parse_args()
    if a.sync:
        v13_tracking_sync.sync_from_journal(); v13_tracking_sync.settle_live_results()
    r=build(a.date)
    if a.send: r["discord_sent"]=bool(send(r))
    print(json.dumps(r,indent=2,sort_keys=True))


if __name__=="__main__":main()
