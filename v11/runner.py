from __future__ import annotations
import hashlib
from datetime import datetime, timezone
import bot as core
from . import config
from .features import live_ml_features, snapshot_features, point_in_time_snapshot, build_previous_game_index, operational_features
from .models import load_model, apply_ml_heads, patch_ml_options, attach_market_challengers
from .selector import allocate
from .journal import load_rows, write_rows, settle_rows, capture_official_bets, comparison_summary, finance_summary, write_report, settle_bet
from .champion import evaluate_all

def _send_comparison(report):
    if not core.DISCORD_URL or int(report.get("settled_this_run") or 0)<=0:return
    c=report.get("comparison") or {}; f=report.get("official_finance") or {}
    def pct(x):return "—" if x is None else f"{100*float(x):.1f}%"
    n=int(c.get("settled_games") or 0); net=int(c.get("v11_net_corrections") or 0); grade="\n".join(f"**{k}** {v['wins']}/{v['n']} ({pct(v['accuracy'])})" for k,v in (c.get("by_grade") or {}).items()) or "—"; pnl=f.get("profit_units"); pnl_txt="—" if pnl is None else f"{float(pnl):+.2f}u"
    fields=[("🏆 Direction",f"V10 **{int(c.get('v10_wins') or 0)}/{n} ({pct(c.get('v10_accuracy'))})**\nV11.3 **{int(c.get('v11_3_wins') or 0)}/{n} ({pct(c.get('v11_3_accuracy'))})**\nNet corrections **{net:+d}**"),("🎯 Calibration",f"Brier V10 **{c.get('v10_brier','—')}** → V11.2 **{c.get('v11_2_brier','—')}**\nLogLoss V10 **{c.get('v10_logloss','—')}** → V11.2 **{c.get('v11_2_logloss','—')}**"),("⭐ Grades",grade),("💰 Plan Officiel",f"{int(f.get('wins') or 0)}V-{int(f.get('losses') or 0)}D-{int(f.get('pushes') or 0)}P • **{pnl_txt}** • ROI **{pct(f.get('roi'))}**"),("🧪 Challengers","RL/Total restent shadow tant qu'ils ne passent pas les gates chronologiques + live. Aucun abaissement automatique des seuils.")]
    try:core.send_embed("📊 BILAN LIVE — V10 vs V11",fields,5763719 if net>=0 else 15548997)
    except Exception:core.logging.exception("Discord bilan V11 impossible")

def self_test():
    model=load_model(); assert model["validation"]["wins"]==271 and model["validation"]["holdout_n"]==451
    from .models import v11_2_probability,v11_3_direction_probability
    f={"lineup_relative":.5,"regular_overlap":.2,"lineup_abs":.7,"lineup_cov_diff":0,"lineup_x_uncertainty":.4,"lineup_available":1}
    assert 0<v11_2_probability(.55,f,model)<1 and 0<v11_3_direction_probability(.55,f,model)<1
    from .selector import required_price
    assert required_price(core,{"p_effective":.60,"p_push":0,"winamax_eval":{"price":1.8}})>1.60
    row={"result_status":"FINAL","home":"H","away":"A","home_score":4,"away_score":3}; bet={"market":"RUNLINE","pick":"A","point":1.0,"units":1,"winamax_price":1.9,"status":"PENDING"}; assert settle_bet(bet,row) and bet["status"]=="PUSH"
    print("SELF-TEST V11 PACKAGE OK")

def main():
    if not core.ODDS_KEY:raise SystemExit("ODDS_API_KEY absente")
    model=load_model(); rows=load_rows(); settled_now=settle_rows(core,rows); discord_ok=core.discord_test(); hist=core.load_history(); core.settle_history(hist)
    run_state=core.run_model_state(hist); disp_state=core.dispersion_state(hist); engine="learned-runs" if run_state.get("active") else "base-runs"; cal_state=core.calibration_state(hist,engine); skill=core.skill_state(hist,engine); states=(run_state,disp_state,cal_state,skill)
    core.savant_league(); games=core.mlb_schedule(core.TARGET_DATE); events=core.odds_api(); matches=core.match_odds_events(games,events); results=[]; now=core.NOW
    for game in games:
        if core.parse_dt(game["gameDate"])<=now:continue
        pair=matches.get(str(game["gamePk"]))
        if not pair:continue
        try:
            r=core.analyze_base(game,pair[0],pair[1],states,hist); r["disp_state"]=disp_state; core.attach_model_recommendations(r); ml_features=live_ml_features(core,r); apply_ml_heads(r,ml_features,model); patch_ml_options(core,r); fs=snapshot_features(core,r); attach_market_challengers(core,r,fs,model); r["v11_feature_snapshot"]=fs; results.append(r)
        except Exception:core.logging.exception("V11 analyse impossible gamePk=%s",game.get("gamePk"))
    previous_index=build_previous_game_index(core,core.TARGET_DATE,results)
    for r in results:
        try:operational_features(core,r,previous_index)
        except Exception:core.logging.exception("V11 operational features impossible gamePk=%s",r.get("game_pk"))
    portfolio,chosen,combo=allocate(core,results) if results else ({"daily_cap":0,"allocated":0,"remaining":0,"game_cap":0},[],{})
    analyzed_at=datetime.now(timezone.utc).isoformat(); run_id=hashlib.sha1(f"{analyzed_at}|{core.TARGET_DATE}|{config.VERSION}".encode()).hexdigest()[:16]; new=[]
    for r in results:
        row=dict(r["v11_3"]); row.update({"run_id":run_id,"analyzed_at":analyzed_at,"target_date":core.TARGET_DATE,"official_bets":capture_official_bets(core,r),"v11_market_challengers":r.get("v11_market_challengers"),"v11_feature_snapshot":r.get("v11_feature_snapshot"),"v11_operational_features":r.get("v11_operational_features"),"point_in_time":point_in_time_snapshot(core,r,analyzed_at)}); new.append(row)
    rows.extend(new); write_rows(rows)
    if discord_ok and results:
        for r in results:core.send_game(r,{},portfolio)
        core.send_top_messages(results,skill); core.send_daily_plan(results)
    comparison=comparison_summary(rows); finance=finance_summary(rows); challenger_evidence=evaluate_all(rows)
    report={"version":config.VERSION,"run_id":run_id,"analyzed_at":analyzed_at,"target_date":core.TARGET_DATE,"model":model,"remaining_games_analyzed":len(new),"settled_this_run":settled_now,"comparison":comparison,"official_finance":finance,"challenger_evidence":challenger_evidence,"production":{"ML":"V11.3 direction + V11.2 probability","RUNLINE":"V10.0.15 until V11 challenger gate passes","TOTAL":"V10.0.15 until V11 challenger gate passes","selector":"V11 value-gated","price_gate":True},"challenger_policy":{"auto_promotion":False,"requires_walk_forward":True,"requires_live_confirmation":True,"gates":{"min_holdout_n":config.MIN_HOLDOUT_N,"min_live_n":config.MIN_LIVE_N,"min_brier_gain":config.MIN_BRIER_GAIN,"min_gain_probability":config.MIN_GAIN_PROB}},"point_in_time_archive":True,"operational_shadow_features":["starter prior stats","bullpen previous-game usage","rest days","travel km","timezone shift approximation","extra innings","doubleheader"],"top_picks":[{k:r.get(k) for k in ("game_pk","away","home","base_v10_pick","v11_3_pick","v11_3_direction_score","v11_2_probability_for_pick","grade","rank_score","phase")} for r in sorted(new,key=lambda x:x.get("rank_score",0),reverse=True)[:5]]}
    write_report(report); _send_comparison(report); core.logging.info("V11 terminé | games=%d settled=%d V10=%s V11=%s ROI=%s",len(new),settled_now,f"{100*comparison.get('v10_accuracy',0):.1f}%" if comparison.get("v10_accuracy") is not None else "-",f"{100*comparison.get('v11_3_accuracy',0):.1f}%" if comparison.get("v11_3_accuracy") is not None else "-",f"{100*finance.get('roi',0):+.1f}%" if finance.get("roi") is not None else "-")
