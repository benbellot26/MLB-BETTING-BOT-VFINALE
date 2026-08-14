from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from . import config, core, engine, selector, discord, journal

def _legacy_reference():
    p=Path("data/mlb_backtest_2026_report.json")
    if not p.exists():return None
    try:
        d=json.loads(p.read_text(encoding="utf-8"));return {"source":"historical frozen V10 benchmark only; never used for predictions","ml_accuracy":(d.get("v10_ml") or {}).get("accuracy"),"ml_brier":(d.get("v10_ml") or {}).get("brier"),"ml_logloss":(d.get("v10_ml") or {}).get("logloss"),"runline_proxy_hit_rate":(d.get("runline_proxy") or {}).get("hit_rate"),"historical_odds_used":(d.get("methodology") or {}).get("historical_odds_used")}
    except Exception:return None

def _row(result,run_id,analyzed_at):
    return {"schema":"v11-live-v2","engine_version":config.VERSION,"run_id":run_id,"analyzed_at":analyzed_at,"target_date":core.TARGET_DATE,"game_pk":result.get("game_pk"),"game_date":(result.get("game") or {}).get("gameDate"),"home":result["ctx"]["home"],"away":result["ctx"]["away"],"phase":result.get("phase"),"projected_home_runs":round(core.num(result.get("hmu")),4),"projected_away_runs":round(core.num(result.get("amu")),4),"p_home":round(core.num(result.get("p_home"),.5),6),"quality":round(core.num(result.get("quality")),4),"features":result.get("features"),"starters":{"home":result["ctx"].get("home_starter"),"away":result["ctx"].get("away_starter")},"lineups":{"home":result["ctx"].get("home_lineup"),"away":result["ctx"].get("away_lineup")},"sharp_ml":result.get("con"),"options":[{k:o.get(k) for k in ("market","name","point","p_structural","p_model","p_effective","p_market","refs","sharp_books","sharp_weight","confidence","selection_score","result","brier","logloss","sharp_brier","sharp_logloss")} | {"winamax_eval":o.get("winamax_eval")} for o in result.get("options") or []],"official_bets":journal.capture_bets(result),"result_status":"PENDING","winner":None,"home_score":None,"away_score":None,"settled_at":None}

def _send_summary(report):
    if not core.DISCORD_URL or int(report.get("settled_this_run") or 0)<=0:return
    met=report.get("performance") or {};fin=report.get("finance") or {};lines=[]
    for m in ("ML","RUNLINE","TOTAL"):
        x=(met.get("by_market") or {}).get(m)
        if x:lines.append(f"**{m}** : {x['wins']}/{x['n']} ({core.pct(x['accuracy'])}) • Brier {x['brier']:.4f} • LL {x['logloss']:.4f}")
    core.send_embed("📊 BILAN LIVE V11",[("🎯 Performance","\n".join(lines) if lines else "Pas encore assez de résultats."),("💰 Plan officiel",f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}** • DD max **{core.num(fin.get('max_drawdown_units')):.2f}u**"),("🧠 Moteur","100 % V11 en production : **ML + Run Line + Total + selector + combiné**. V10 n'est plus utilisé pour produire un pick.")],5763719)

def self_test():
    assert config.VERSION.startswith("11.");assert .5<engine.prob_home_win(5.0,4.0)<.8;fake={"p_effective":.60,"winamax_eval":{"price":2.0}};assert selector.required_price(fake)>1.60 and selector.value_gate(fake)["ok"]
    row={"result_status":"FINAL","home":"H","away":"A","home_score":4,"away_score":3};opt={"market":"RUNLINE","name":"A","point":1.0,"p_effective":.55};journal.settle_option(opt,row);assert opt["result"]=="PUSH"
    print("SELF-TEST V11 STANDALONE ALL MARKETS OK")

def main():
    if not core.ODDS_KEY:raise SystemExit("ODDS_API_KEY absente")
    rows=journal.load_rows();settled_now=journal.settle_rows(rows);games=core.mlb_schedule(core.TARGET_DATE);events=core.odds_api();matches=core.match_odds_events(games,events);results=[]
    for g in games:
        try:
            if core.parse_dt(g.get("gameDate"))<=core.NOW:continue
        except Exception:continue
        event=matches.get(str(g.get("gamePk")))
        if not event:continue
        try:results.append(engine.analyze(g,event))
        except Exception:core.logging.exception("Analyse V11 impossible gamePk=%s",g.get("gamePk"))
    portfolio,chosen,combo,pool=selector.allocate(results,core.UNIT);analyzed_at=datetime.now(timezone.utc).isoformat();run_id=hashlib.sha1(f"{analyzed_at}|{core.TARGET_DATE}|{config.VERSION}".encode()).hexdigest()[:16];new=[_row(r,run_id,analyzed_at) for r in results];cr=journal.combo_row(combo,run_id,analyzed_at,core.TARGET_DATE);rows.extend(new)
    if cr:rows.append(cr)
    journal.write_rows(rows)
    if core.discord_test() and results:
        for r in results:discord.send_game(r,portfolio)
        discord.send_top(results);discord.send_plan(chosen,combo,portfolio,pool)
    performance=journal.metrics(rows);finance=journal.finance_summary(rows);report={"version":config.VERSION,"run_id":run_id,"analyzed_at":analyzed_at,"target_date":core.TARGET_DATE,"remaining_games_analyzed":len(results),"settled_this_run":settled_now,"production":{"engine":"V11 standalone","ML":"V11","RUNLINE":"V11","TOTAL":"V11","selector":"V11","combo":"V11","v10_dependency":False},"performance":performance,"finance":finance,"legacy_v10_reference":_legacy_reference(),"methodology":{"runs_model":"team offense + opponent pitching + probable starter + lineup OPS + park + home advantage","distribution":"independent Poisson score matrix","sharp":"de-vig consensus blended with bounded 15-30% weight when available","execution":"Winamax exact price with EV/edge/safety value gate","claim":"V11 is sole production engine; superiority must be demonstrated by settled/backtest evidence, not assumed"}}
    journal.write_report(report);_send_summary(report);core.logging.info("V11 standalone terminé | games=%d settled=%d ML/RL/TOTAL=V11 ROI=%s",len(results),settled_now,core.pct(finance.get("roi")))
