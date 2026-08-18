from __future__ import annotations

import argparse, json, math, os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import core, v13_daily_tracking as tracking, v13_tracking_sync

OUT = Path(os.getenv("V13_DAILY_POSTMORTEM_FILE", "data/v13_daily_postmortem.json"))
PARIS = ZoneInfo("Europe/Paris")
PROMOTION_MIN_N = 300
PROMOTION_MIN_BRIER_GAIN = .001
PROMOTION_MIN_LOGLOSS_GAIN = .002


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


def _prob(row, field):
    value=row.get(field)
    if value is None and field=="p_baseball_calibrated": value=row.get("p_model")
    if value is None and field=="p_predictive_final": value=row.get("p_baseball_calibrated",row.get("p_model"))
    return _num(value)


def _independent_key(s):
    market=str(s.get("market") or "").upper()
    gid=str(s.get("game_pk") or "")
    point=s.get("point")
    if market=="ML": return (gid,market,"game")
    if market=="TOTAL": return (gid,market,str(point))
    if market=="RUNLINE": return (gid,market,str(abs(_num(point,0) or 0)))
    return (gid,market,str(point))


def _obs_rank(s):
    return str(s.get("observation_at") or s.get("observed_at") or "")


def _choose_side(xs):
    market=str(xs[0].get("market") or "").upper()
    if market=="TOTAL":
        pick=next((x for x in xs if str(x.get("pick") or "").lower()=="over"),None)
    else:
        home=str(xs[0].get("home") or "")
        pick=next((x for x in xs if str(x.get("pick") or "")==home),None)
    return pick or sorted(xs,key=lambda x:str(x.get("pick") or ""))[0]


def _choose_independent(states, phase=None):
    """One deterministic latest forecast per independent target."""
    groups=defaultdict(list)
    for s in states:
        if _result_y(s) is None: continue
        if phase and str(s.get("phase") or "").upper()!=str(phase).upper(): continue
        groups[_independent_key(s)].append(s)
    chosen=[]
    for xs in groups.values():
        latest=max(_obs_rank(x) for x in xs)
        same=[x for x in xs if _obs_rank(x)==latest]
        chosen.append(_choose_side(same))
    return chosen


def _calibration_bins(rows, field):
    bins=[(0,.45),(.45,.50),(.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,1.001)]
    out=[]
    for lo,hi in bins:
        xs=[r for r in rows if _prob(r,field) is not None and lo<=_prob(r,field)<hi]
        if not xs: continue
        out.append({"lo":lo,"hi":hi,"n":len(xs),"mean_p":round(sum(_prob(x,field) for x in xs)/len(xs),4),
                    "win_rate":round(sum(_result_y(x) for x in xs)/len(xs),4)})
    return out


def _ece(rows, field):
    bins=[]
    for i in range(10):
        lo=i/10; hi=(i+1)/10 if i<9 else 1.001
        xs=[r for r in rows if _prob(r,field) is not None and lo<=_prob(r,field)<hi]
        if xs: bins.append(xs)
    n=sum(len(xs) for xs in bins)
    if not n:return None
    total=0.0
    for xs in bins:
        mean_p=sum(_prob(x,field) for x in xs)/len(xs)
        win_rate=sum(_result_y(x) for x in xs)/len(xs)
        total+=(len(xs)/n)*abs(mean_p-win_rate)
    return round(total,6)


def _scores(rows, field):
    xs=[x for x in rows if _prob(x,field) is not None and _result_y(x) is not None]
    if not xs:return {"n":0,"brier":None,"logloss":None,"ece":None,"mean_p":None,"hit_rate":None}
    b=sum((_prob(x,field)-_result_y(x))**2 for x in xs)/len(xs)
    ll=sum(_logloss(_prob(x,field),_result_y(x)) for x in xs)/len(xs)
    return {"n":len(xs),"brier":round(b,6),"logloss":round(ll,6),"ece":_ece(xs,field),
            "mean_p":round(sum(_prob(x,field) for x in xs)/len(xs),6),
            "hit_rate":round(sum(_result_y(x) for x in xs)/len(xs),6)}


def _paired_improvement(rows, baseline_field, candidate_field):
    paired=[x for x in rows if _prob(x,baseline_field) is not None and _prob(x,candidate_field) is not None and _result_y(x) is not None]
    if not paired:return {"n":0,"brier_improvement":None,"logloss_improvement":None}
    base=_scores(paired,baseline_field); candidate=_scores(paired,candidate_field)
    return {"n":len(paired),
            "brier_improvement":round(base["brier"]-candidate["brier"],6),
            "logloss_improvement":round(base["logloss"]-candidate["logloss"],6)}


def _promotion_readiness(comparison):
    n=int(comparison.get("n") or 0)
    bg=_num(comparison.get("brier_improvement")); lg=_num(comparison.get("logloss_improvement"))
    if n<PROMOTION_MIN_N:
        return {"status":"COLLECTING","n":n,"required_n":PROMOTION_MIN_N,"eligible":False}
    passed=(bg is not None and lg is not None and bg>=PROMOTION_MIN_BRIER_GAIN and lg>=PROMOTION_MIN_LOGLOSS_GAIN)
    return {"status":"PROMOTION_CANDIDATE" if passed else "KEEP_BASEBALL_PRIMARY","n":n,"required_n":PROMOTION_MIN_N,
            "eligible":bool(passed),"required_brier_gain":PROMOTION_MIN_BRIER_GAIN,"required_logloss_gain":PROMOTION_MIN_LOGLOSS_GAIN}


def _metrics_from_independent(independent, all_rows):
    raw=_scores(independent,"p_raw")
    baseball=_scores(independent,"p_baseball_calibrated")
    posterior=_scores(independent,"p_posterior")
    predictive=_scores(independent,"p_predictive_final")
    sharp=_scores(independent,"p_market")
    posterior_cmp=_paired_improvement(independent,"p_baseball_calibrated","p_posterior")
    sharp_cmp=_paired_improvement(independent,"p_baseball_calibrated","p_market")
    predictive_cmp=_paired_improvement(independent,"p_baseball_calibrated","p_predictive_final")
    priced=[x for x in all_rows if _num(x.get("winamax_price")) and x.get("flat_1u_pnl") is not None]
    selected=[x for x in priced if x.get("official_selected")]
    rejected=[x for x in priced if not x.get("official_selected")]
    close=[x for x in independent if _num(x.get("close_sharp_fair")) is not None and _prob(x,"p_predictive_final") is not None]
    clv=[_num(x.get("close_sharp_fair"))-_prob(x,"p_predictive_final") for x in close]
    pos_rejected=[x for x in rejected if (_num(x.get("nominal_ev"),-999) or -999)>0]
    return {
        "independent_targets":len(independent),
        "model":baseball,
        "raw":raw,
        "baseball":baseball,
        "posterior":posterior,
        "predictive_final":predictive,
        "sharp":sharp,
        "comparisons":{
            "posterior_vs_baseball":posterior_cmp,
            "sharp_vs_baseball":sharp_cmp,
            "predictive_final_vs_baseball":predictive_cmp,
        },
        "posterior_promotion":_promotion_readiness(posterior_cmp),
        "calibration_model":_calibration_bins(independent,"p_baseball_calibrated"),
        "calibration_predictive_final":_calibration_bins(independent,"p_predictive_final"),
        "selected":{"n":len(selected),"wins":sum(x.get("settled_result")=="WIN" for x in selected),
                    "losses":sum(x.get("settled_result")=="LOSS" for x in selected),
                    "pushes":sum(x.get("settled_result")=="PUSH" for x in selected),
                    "pnl_1u":round(sum(_num(x.get("flat_1u_pnl"),0) or 0 for x in selected),4)},
        "rejected_priced":len(rejected),"positive_ev_rejected":len(pos_rejected),
        "positive_ev_rejected_wins":sum(x.get("settled_result")=="WIN" for x in pos_rejected),
        "mean_predictive_minus_close_sharp":round(-sum(clv)/len(clv),6) if clv else None,
        "mean_model_minus_close_sharp":round(-sum(clv)/len(clv),6) if clv else None,
        "closing_sharp_n":len(clv),
    }


def _market_metrics(rows):
    overall=_metrics_from_independent(_choose_independent(rows),rows)
    overall["by_phase"]={}
    for phase in ("EARLY","LATE","FINAL"):
        phase_rows=[x for x in rows if str(x.get("phase") or "").upper()==phase]
        overall["by_phase"][phase]=_metrics_from_independent(_choose_independent(rows,phase),phase_rows)
    return overall


def build(day=None):
    if day is None:
        day=(datetime.now(PARIS).date()-timedelta(days=1)).isoformat()
    states=[s for s in tracking.fold().values() if str(s.get("target_date") or "")==str(day) and s.get("settled_result") in {"WIN","LOSS","PUSH"}]
    by_market={m:_market_metrics([s for s in states if str(s.get("market") or "").upper()==m]) for m in ("ML","RUNLINE","TOTAL")}
    priced=[s for s in states if _num(s.get("winamax_price")) and s.get("flat_1u_pnl") is not None]
    selected=[s for s in priced if s.get("official_selected")]
    report={"schema":"v13-daily-postmortem-v2","generated_at":datetime.now(timezone.utc).isoformat(),"target_date":day,
            "settled_observations":len(states),"priced_observations":len(priced),
            "settled_options":len(states),"priced_options":len(priced),
            "official_selected":len(selected),"official_pnl_1u":round(sum(_num(s.get("flat_1u_pnl"),0) or 0 for s in selected),4),
            "markets":by_market,
            "methodology":{"probability_scoring":"latest deterministic independent side per game/line; raw, calibrated baseball, posterior shadow, primary predictive and sharp are scored on settled outcomes",
                           "posterior_promotion":f"shadow only until paired n>={PROMOTION_MIN_N}, Brier gain>={PROMOTION_MIN_BRIER_GAIN:.3f} and LogLoss gain>={PROMOTION_MIN_LOGLOSS_GAIN:.3f}; promotion is never automatic from a tiny sample",
                           "portfolio_pnl":"official selections only; rejected options are diagnostic only",
                           "clv":"primary predictive probability minus latest valid pregame sharp fair probability"}}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    return report


def _fmt_metric(m):
    if not m.get("n"):return "n=0"
    ece="—" if m.get("ece") is None else f"{m['ece']:.4f}"
    return f"n={m['n']} • Brier {m['brier']:.4f} • LogLoss {m['logloss']:.4f} • ECE {ece}"


def _fmt_gain(c):
    if not c.get("n"):return "n=0"
    return f"n={c['n']} • ΔB {c['brier_improvement']:+.4f} • ΔLL {c['logloss_improvement']:+.4f}"


def discord_fields(report):
    fields=[]
    for market in ("ML","RUNLINE","TOTAL"):
        m=report["markets"][market]; selected=m["selected"]
        promotion=m.get("posterior_promotion") or {}
        phases=[]
        for phase in ("EARLY","LATE","FINAL"):
            pm=(m.get("by_phase") or {}).get(phase,{}).get("predictive_final") or {}
            if pm.get("n"): phases.append(f"{phase} n={pm['n']} Brier={pm['brier']:.4f}")
        phase_text=" • ".join(phases) if phases else "aucune phase scorée"
        fields.append((market,
            f"Principal: {_fmt_metric(m['predictive_final'])}\n"
            f"Baseball calibré: {_fmt_metric(m['baseball'])}\n"
            f"Posterior shadow: {_fmt_metric(m['posterior'])}\n"
            f"Sharp: {_fmt_metric(m['sharp'])}\n"
            f"Posterior vs baseball: {_fmt_gain(m['comparisons']['posterior_vs_baseball'])}\n"
            f"Statut posterior: **{promotion.get('status') or 'COLLECTING'}** ({promotion.get('n',0)}/{promotion.get('required_n',PROMOTION_MIN_N)})\n"
            f"Phases principal: {phase_text}\n"
            f"Économie secondaire: {selected['wins']}W-{selected['losses']}L-{selected['pushes']}P • P/L {selected['pnl_1u']:+.2f}u • Closing sharp n={m['closing_sharp_n']}"))
    return fields


def send(report):
    if not core.DISCORD_URL:return False
    title=f"📊 V13 PREDICTIVE POST-MORTEM — {report['target_date']}"
    desc=(f"{report['settled_observations']} observations settled • scoring probabiliste prioritaire • "
          f"{report['priced_observations']} observations avec cote d'exécution")
    return core.send_embed(title,discord_fields(report),5763719,desc)


def main():
    p=argparse.ArgumentParser(); p.add_argument("--date"); p.add_argument("--send",action="store_true"); p.add_argument("--sync",action="store_true"); a=p.parse_args()
    if a.sync:
        v13_tracking_sync.sync_from_journal(); v13_tracking_sync.settle_live_results()
    r=build(a.date)
    if a.send: r["discord_sent"]=bool(send(r))
    print(json.dumps(r,indent=2,sort_keys=True))


if __name__=="__main__":main()
