from __future__ import annotations
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
from . import config,core,selector,journal,storage,data_quality,pro_model
from . import engine_v12 as engine
from . import discord_v12 as discord


def _historical_reference():
    p=Path("data/mlb_backtest_2026_report.json")
    if not p.exists():return None
    try:
        d=json.loads(p.read_text(encoding="utf-8")); x=d.get("v10_ml") or {}
        return {"source":"frozen benchmark only; never used by V12 predictions","ml_accuracy":x.get("accuracy"),"ml_brier":x.get("brier"),"ml_logloss":x.get("logloss"),"historical_odds_used":(d.get("methodology") or {}).get("historical_odds_used")}
    except Exception:return None


def _row(r,run_id,at,snapshot=None):
    keys=("market","name","point","p_structural","p_model","p_effective","p_win","p_push","p_market","refs","sharp_books","sharp_weight","sharp_dispersion","sharp_robustness","sharp_effective_n","confidence","quality","model_uncertainty","calibration_source","data_quality","selection_score","result","brier","logloss","sharp_brier","sharp_logloss")
    return {"schema":config.SCHEMA_VERSION,"engine_version":config.VERSION,"run_id":run_id,"analyzed_at":at,"target_date":core.TARGET_DATE,
      "game_pk":r.get("game_pk"),"game_date":(r.get("game") or {}).get("gameDate"),"home":r["ctx"]["home"],"away":r["ctx"]["away"],"phase":r.get("phase"),
      "projected_home_runs":round(core.num(r.get("hmu")),4),"projected_away_runs":round(core.num(r.get("amu")),4),"p_home":round(core.num(r.get("p_home"),.5),6),
      "quality":round(core.num(r.get("quality")),4),"data_quality":data_quality.assess(r),"features":r.get("features"),
      "starters":{"home":r["ctx"].get("home_starter"),"away":r["ctx"].get("away_starter")},"lineups":{"home":r["ctx"].get("home_lineup"),"away":r["ctx"].get("away_lineup")},
      "sharp_ml":r.get("con"),"model":r.get("model"),"raw_snapshot":str(snapshot) if snapshot else None,
      "options":[{k:o.get(k) for k in keys}|{"winamax_eval":o.get("winamax_eval")} for o in r.get("options") or []],
      "official_bets":journal.capture_bets(r),"result_status":"PENDING","winner":None,"home_score":None,"away_score":None,"settled_at":None}


def _summary(rep):
    if not core.DISCORD_URL or int(rep.get("settled_this_run") or 0)<=0:return
    fin=rep.get("finance") or {}; clv=f" • CLV {100*core.num(fin.get('mean_clv_pct')):+.2f}%" if fin.get("clv_n") else ""
    core.send_embed("📊 BILAN LIVE V12",[("Ledger",f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}** • DD **{core.num(fin.get('max_drawdown_units')):.2f}u**{clv}"),("Modèle",f"**{config.VERSION}** • Champion actif: **{bool((rep.get('model') or {}).get('active'))}**")],5763719)


def self_test():
    assert config.VERSION.startswith("12.")
    assert .5<engine.prob_home_win(5,4)<.8
    hp,ap=engine.score_matrix(4.5,4); assert abs(sum(hp)-1)<1e-9 and abs(sum(ap)-1)<1e-9
    fake={"p_effective":.60,"p_win":.54,"p_push":.10,"model_uncertainty":.01,"winamax_eval":{"price":2.0}}
    assert selector.required_price(fake)>1 and "ev_at_price" in selector.value_gate(fake)
    assert storage.bet_key(1,"ML","New York Yankees",None)==storage.bet_key(1,"ML","New-York Yankees",None)
    print("SELF-TEST V12 PROFESSIONAL FOUNDATION OK")


def main():
    if not core.ODDS_KEY:raise SystemExit("ODDS_API_KEY absente")
    rows=journal.load_rows(); pending={(str(r.get("game_pk")),str(r.get("analyzed_at"))) for r in rows if r.get("schema")==config.SCHEMA_VERSION and r.get("result_status")!="FINAL" and r.get("game_pk")}
    journal.settle_rows(rows); settled_now=sum(1 for r in rows if (str(r.get("game_pk")),str(r.get("analyzed_at"))) in pending and r.get("result_status")=="FINAL")
    ledger_settled=storage.settle_from_journal(rows)
    games=core.mlb_schedule(core.TARGET_DATE); events=core.odds_api(); matches=core.match_odds_events(games,events)
    at=datetime.now(timezone.utc).isoformat(); run_id=hashlib.sha1(f"{at}|{core.TARGET_DATE}|{config.VERSION}".encode()).hexdigest()[:16]
    raw=storage.snapshot_run(games,events,run_id,at,core.TARGET_DATE); storage.capture_market_snapshot(events,run_id,at,core.TARGET_DATE)
    results=[]
    for g in games:
        try:
            if core.parse_dt(g.get("gameDate"))<=core.NOW:continue
        except Exception:continue
        e=matches.get(str(g.get("gamePk")))
        if not e:continue
        try:results.append(engine.analyze(g,e))
        except Exception:core.logging.exception("Analyse V12 impossible gamePk=%s",g.get("gamePk"))
    storage.update_clv(results,at); portfolio,chosen,combo,pool=selector.allocate(results,core.UNIT,core.BANKROLL,storage.open_exposure())
    storage.record_selected_bets(chosen,combo,run_id,at,core.TARGET_DATE)
    rows.extend(_row(r,run_id,at,raw) for r in results); cr=journal.combo_row(combo,run_id,at,core.TARGET_DATE)
    if cr:rows.append(cr)
    journal.write_rows(rows); health=data_quality.health_report(results,len(games),len(matches))
    if core.discord_test() and results:
        for r in results:discord.send_game(r,portfolio)
        discord.send_top(results); discord.send_plan(chosen,combo,portfolio,pool); discord.send_health(health)
    finance=storage.ledger_summary(); model=pro_model.load_model(); performance=journal.metrics(rows)
    report={"version":config.VERSION,"schema":config.SCHEMA_VERSION,"run_id":run_id,"analyzed_at":at,"target_date":core.TARGET_DATE,
      "scheduled_games":len(games),"matched_events":len(matches),"remaining_games_analyzed":len(results),"settled_this_run":settled_now,"ledger_settled_this_run":ledger_settled,
      "production":{"engine":"V12","ML":"V12","RUNLINE":"V12","TOTAL":"V12","selector":"V12","combo":"V12"},"performance":performance,"finance":finance,"data_health":health,
      "model":{"version":model.get("version"),"active":bool(model.get("active")),"run_dispersion":model.get("run_dispersion")},"historical_reference":_historical_reference(),
      "methodology":{"runs_model":"structural baseline + holdout-gated residual","distribution":"Negative Binomial with trainable dispersion artifact","sharp":"strict timestamps + de-vig + commissions + weighted consensus","calibration":"market-specific Champion/Challenger","execution":"all Winamax lines + uncertainty haircut","staking":"bankroll-aware fractional Kelly","ledger":"idempotent event ledger + CLV","raw_archive":str(raw),"claim":"No historical information is fabricated."}}
    journal.write_report(report); _summary(report); core.logging.info("V12 terminé | games=%d ROI=%s CLV=%s",len(results),core.pct(finance.get("roi")),core.pct(finance.get("mean_clv_pct")))

if __name__=="__main__":self_test() if "--self-test" in sys.argv else main()
