#!/usr/bin/env python3
"""MLB Betting Bot V10 release-candidate integration.

This runner assembles every validated V10 block without modifying the stable
main branch. No source rewriting is performed.
"""
import os, sys, math

import v10_step4_runner as step4
from v10_market_calibration import build_states as build_market_cal_states, calibrate_tuple, self_test as market_cal_self_test
from v10_plan import build_plan, combo_metrics, combo_stake, self_test as plan_self_test, MIN_PLAN_CONF, MIN_COMBO_CONF
from v10_ledger import predictions_for_snapshot, settle_record_predictions, performance_report, self_test as ledger_self_test

core=step4.core
core.VERSION="10.0.0-rc1"
core.SCHEMA_VERSION=10
core.RECOMMENDATION_VERSION="model-first-mainline-calibrated-v5"
core.RUN_MODEL_MIN_GAMES=max(450,int(getattr(core,"RUN_MODEL_MIN_GAMES",450)))
core.CAL_MIN_GAMES=max(500,int(getattr(core,"CAL_MIN_GAMES",500)))

_MARKET_CAL_STATES=None
_LAST_PORTFOLIO={"allocated":0.0,"daily_cap":core.BANKROLL*core.MAX_DAILY_EXPOSURE_PCT,"remaining":core.BANKROLL*core.MAX_DAILY_EXPOSURE_PCT}

_original_analyze=core.analyze_base
_original_allocate=core.allocate_portfolio
_original_build_snapshot=core.build_snapshot
_original_sync_recommendations=core.sync_recommendations
_original_write_history=core.write_history
_original_performance=core.performance

def _market_states(hist):
    global _MARKET_CAL_STATES
    if _MARKET_CAL_STATES is None:
        _MARKET_CAL_STATES=build_market_cal_states(hist,core.CAL_MIN_GAMES)
        for phase,markets in _MARKET_CAL_STATES.items():
            for market,s in markets.items():
                core.logging.info("V10 MARKET CAL | %s/%s n=%d active=%s Brier=%s→%s LogLoss=%s→%s",phase,market,s["n"],s["active"],f"{s['brier_raw']:.4f}" if s["brier_raw"] is not None else "-",f"{s['brier_cal']:.4f}" if s["brier_cal"] is not None else "-",f"{s['logloss_raw']:.4f}" if s["logloss_raw"] is not None else "-",f"{s['logloss_cal']:.4f}" if s["logloss_cal"] is not None else "-")
    return _MARKET_CAL_STATES

def _refresh_execution(rec,result):
    e=rec.get("winamax_eval")
    if not e:return
    price=core.num(e.get("price"),0)
    if price<=1:return
    pw,pp,pl=rec["p_win"],rec["p_push"],rec["p_loss"];nonpush=pw+pl;pcond=pw/nonpush if nonpush else .5;edge=pcond-1/price;ev=pw*price+pp-1;fair=(1-pp)/pw if pw>0 else 99;cu,cs=core.stake_candidate(pw,pp,pl,price);reasons=[]
    if result["quality"]<core.MIN_QUALITY:reasons.append(f"qualité {result['quality']*10:.1f}/10 < {core.MIN_QUALITY*10:.1f}")
    if edge<core.MIN_EDGE:reasons.append(f"prix: edge {edge*100:+.1f} pts < {core.MIN_EDGE*100:.1f}")
    if ev<core.MIN_EV:reasons.append(f"prix: EV {ev*100:+.1f}% < {core.MIN_EV*100:.1f}%")
    if not reasons and cu<=0:reasons.append("Kelly prudent < 0.25u")
    e.update({"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":pcond,"fair":fair,"min_price":rec["min_price"],"edge":edge,"ev":ev,"quality":result["quality"],"qualified":not reasons,"reason":"OK" if not reasons else " ; ".join(reasons),"candidate_units":cu,"candidate_stake_eur":cs})

def _apply_market_calibration(result,hist):
    states=_market_states(hist);phase=result.get("phase","EARLY")
    for market,rec in (result.get("model_recs") or {}).items():
        if not rec:continue
        s=states.get(phase,{}).get(market,{});raw_pm=core.num(rec.get("p_model"),.5);rec["p_model_raw"]=raw_pm;rec["market_calibration_n"]=s.get("n",0);rec["market_calibration_active"]=bool(s.get("active"))
        if s.get("active") and s.get("model"):
            pw,pp,pl=calibrate_tuple(s["model"],core.num(rec.get("p_win"),raw_pm),core.num(rec.get("p_push"),0),core.num(rec.get("p_loss"),1-raw_pm));nonpush=pw+pl
            if nonpush>0:
                pm=pw/nonpush;rec.update({"p_model":pm,"p_win":pw,"p_push":pp,"p_loss":pl});rec["fair"]=(1-pp)/pw if pw>0 else 99;rec["min_price"]=core.min_acceptable_price(pw,pp,pl);rec["market_gap"]=pm-rec["p_market"] if rec.get("p_market") is not None else None;rec["confidence"]=core.model_signal_confidence(pm,result["quality"],rec.get("p_market"),rec.get("refs",0));_refresh_execution(rec,result)
    return result

def analyze_base_v10_final(game,event,delta,states,hist):
    result=_original_analyze(game,event,delta,states,hist);return _apply_market_calibration(result,hist)
core.analyze_base=analyze_base_v10_final

def allocate_portfolio_v10(results):
    global _LAST_PORTFOLIO
    _LAST_PORTFOLIO=_original_allocate(results);return _LAST_PORTFOLIO
core.allocate_portfolio=allocate_portfolio_v10

def build_snapshot_v10(result,record):
    snap=_original_build_snapshot(result,record);preds=predictions_for_snapshot(result,snap["snapshot_id"])
    for p in preds:p["analyzed_at"]=snap.get("analyzed_at");p["home"]=result["ctx"]["home"];p["away"]=result["ctx"]["away"]
    snap["predictions"]=preds;snap["schema_version"]=10;return snap
core.build_snapshot=build_snapshot_v10

def sync_recommendations_v10(record,evals,snap):
    out=_original_sync_recommendations(record,evals,snap);ledger=record.setdefault("predictions",[]);known={p.get("prediction_id") for p in ledger}
    for p in snap.get("predictions",[]) or []:
        if p.get("prediction_id") not in known:ledger.append(dict(p));known.add(p.get("prediction_id"))
    return out
core.sync_recommendations=sync_recommendations_v10

def _settle_all(hist):return sum(settle_record_predictions(r) for r in (hist or {}).values())
def write_history_v10(hist):
    changed=_settle_all(hist)
    if changed:core.logging.info("V10 PREDICTION LEDGER | %d prédictions réglées",changed)
    return _original_write_history(hist)
core.write_history=write_history_v10

def performance_v10(hist):
    base=_original_performance(hist);report=performance_report(hist);base["prediction_report"]=report;o=report["overall"]
    core.logging.info("V10 PRED METRICS | n=%d WL=%d pushes=%d accuracy=%s Brier=%s LogLoss=%s",o["n"],o["n_wl"],o["pushes"],core.pct(o["accuracy"]) if o["accuracy"] is not None else "-",f"{o['brier']:.4f}" if o["brier"] is not None else "-",f"{o['logloss']:.4f}" if o["logloss"] is not None else "-")
    for market,m in report["by_market"].items():core.logging.info("V10 PRED %s | n=%d accuracy=%s Brier=%s LogLoss=%s",market,m["n"],core.pct(m["accuracy"]) if m["accuracy"] is not None else "-",f"{m['brier']:.4f}" if m["brier"] is not None else "-",f"{m['logloss']:.4f}" if m["logloss"] is not None else "-")
    for phase,m in report["by_phase"].items():core.logging.info("V10 PRED %s | n=%d accuracy=%s Brier=%s LogLoss=%s",phase,m["n"],core.pct(m["accuracy"]) if m["accuracy"] is not None else "-",f"{m['brier']:.4f}" if m["brier"] is not None else "-",f"{m['logloss']:.4f}" if m["logloss"] is not None else "-")
    return base
core.performance=performance_v10

def _pick_text(item,index=None):
    r=item["result"];rec=item["rec"];market=rec["market"];pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if market=="RUNLINE" else f" {rec['point']:g}");label="ML" if market=="ML" else "RL" if market=="RUNLINE" else "TOTAL";emoji,band,_=core.confidence_band(rec["confidence"]);prefix=f"**#{index}** " if index else "• "
    return f"{prefix}{emoji} **{rec['name']}{pt} [{label}]**\n{r['ctx']['away']} @ {r['ctx']['home']} • phase {r['phase']}\nModèle **{core.pct(rec['p_model'])}** • confiance **{rec['confidence']:.1f}/10 — {band}** • fair {rec['fair']:.2f} • **cote mini {rec['min_price']:.2f}**\n{core.execution_status(rec,r['phase'])}"

def send_daily_plan_v10(results):
    singles,combo=build_plan(results);m=combo_metrics(combo);phase_note=" • ".join(sorted({x["result"]["phase"] for x in singles+combo})) if singles or combo else "N/A";simples="\n\n".join(_pick_text(x,i+1) for i,x in enumerate(singles)) if singles else f"**Aucun simple forcé.** Aucune sélection n'atteint le seuil V10 de {MIN_PLAN_CONF:.1f}/10."
    if combo:
        legs=[]
        for x in combo:
            r=x["result"];rec=x["rec"];market=rec["market"];pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if market=="RUNLINE" else f" {rec['point']:g}");price=core.num((rec.get("winamax_eval") or {}).get("price"),0);legs.append(f"• **{rec['name']}{pt}** — {r['ctx']['away']} @ {r['ctx']['home']} • conf {rec['confidence']:.1f}/10 • mini {rec['min_price']:.2f}"+(f" • Winamax {price:.2f}" if price>1 else " • cote Winamax à vérifier"))
        stake=combo_stake(combo,core.BANKROLL,core.UNIT,_LAST_PORTFOLIO.get("allocated",0),_LAST_PORTFOLIO.get("daily_cap",core.BANKROLL*core.MAX_DAILY_EXPOSURE_PCT),core.MIN_EV);status="✅ jouable" if stake>0 else "⚠️ surveillance / non jouable aux prix actuels";combo_text="\n".join(legs)+f"\n\nP(toutes gagnantes) **{core.pct(m['p_all_win'])}** • P(aucune perdante) **{core.pct(m['p_no_loss'])}**\nFair conditionnelle ≈ **{m['fair_conditional']:.2f}** • produit des cotes mini/jambe **{m['min_product']:.2f}**"
        if m.get("quoted_price") is not None:combo_text+=f"\nCote actuelle ≈ **{m['quoted_price']:.2f}** • EV avec pushes **{m['ev']*100:+.1f}%**"
        combo_text+=f"\n{status}"+(f" • mise prudente **{stake:.2f} €**" if stake>0 else "")
    else:combo_text=f"**Aucun combiné forcé.** Il faut au moins 2 matchs hors simples à ≥ {MIN_COMBO_CONF:.1f}/10."
    note="V10 choisit jusqu'à 3 simples, jamais 3 par obligation. Le combiné exclut tous les matchs des simples, gère les pushes et respecte l'exposition restante de la bankroll."
    return core.send_embed("🎟️ PLAN V10 — JUSQU'À 3 SIMPLES + COMBINÉ",[("🕒 État du run",f"{core.NOW.astimezone(core.PARIS).strftime('%d/%m/%Y %H:%M')} (Paris) • phases : {phase_note}"),("🎯 SIMPLES QUALIFIÉS",simples),("🧩 COMBINÉ HORS SIMPLES",combo_text),("🛡️ Règle V10",note)],5763719)
core.send_daily_plan=send_daily_plan_v10

def self_test():
    saved_version=core.VERSION;saved_rec=core.RECOMMENDATION_VERSION
    try:
        core.VERSION="10.0.0-step4";core.RECOMMENDATION_VERSION="model-first-mainline-confidence-v4";step4.self_test()
    finally:core.VERSION=saved_version;core.RECOMMENDATION_VERSION=saved_rec
    market_cal_self_test();plan_self_test();ledger_self_test();assert core.SCHEMA_VERSION==10 and core.RUN_MODEL_MIN_GAMES>=450 and core.CAL_MIN_GAMES>=500 and core.send_daily_plan is send_daily_plan_v10 and core.build_snapshot is build_snapshot_v10
    print("SELF-TEST MLB BETTING BOT V10 RC1 OK")

def main():
    core.logging.info("MLB BETTING BOT V10 RC1 | structural runs + phase ML + main lines + reliability confidence + market calibration + ledger + risk plan");step4.main()

if __name__=="__main__":
    try:
        if "--self-test" in sys.argv:self_test()
        else:main()
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception:core.logging.exception("ERREUR FATALE V10 RC1");raise
