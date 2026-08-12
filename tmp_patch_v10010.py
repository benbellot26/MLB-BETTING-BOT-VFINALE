from pathlib import Path

p=Path('bot.py')
text=p.read_text(encoding='utf-8')
tag='# ==================== V10.0.10 LIVE JOURNAL ====================='
if tag in text:
    raise SystemExit(0)
marker='\nif __name__=="__main__":\n'
if marker not in text:
    raise SystemExit('final __main__ marker not found')

block=r'''
# ==================== V10.0.10 LIVE JOURNAL =====================
# Observation-only layer: no change to baseball projections, effective
# probabilities, Slate Score or staking rules. Every model proposal from every
# run is persisted and later settled independently of what the user actually bets.
_V1009_SELF_TEST_010=v10_self_test

VERSION="10.0.10"
JOURNAL_VERSION="live-proposals-v1"
JOURNAL_FILE=Path(os.getenv("JOURNAL_FILE","data/mlb_bet_journal_v1.jsonl"))


def v1010_load_journal():
    if not JOURNAL_FILE.exists():return []
    rows=[];bad=[]
    for i,line in enumerate(JOURNAL_FILE.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        try:
            r=json.loads(line)
            if not r.get("journal_id") or r.get("journal_version")!=JOURNAL_VERSION:raise ValueError("schema/version")
            rows.append(r)
        except Exception as e:bad.append((i,str(e)))
    if bad:raise RuntimeError(f"Journal live invalide: {len(bad)} ligne(s), première={bad[0]}")
    return rows


def v1010_write_journal(rows):
    write_jsonl(JOURNAL_FILE,rows)


def v1010_profit(result,stake,price):
    stake=num(stake,0);price=num(price,0)
    if result=="W" and stake>0 and price>1:return round(stake*(price-1),4)
    if result=="L" and stake>0:return -round(stake,4)
    if result=="P" and stake>0:return 0.0
    return None


def v1010_make_run_rows(results,run_id=None,analyzed_at=None):
    analyzed_at=analyzed_at or NOW.isoformat()
    run_id=run_id or hashlib.sha1(f"{analyzed_at}|{TARGET_DATE}|{VERSION}".encode()).hexdigest()[:16]
    out=[]
    for r in results:
        ctx=r.get("ctx") or {};phase=r.get("phase","EARLY")
        for market in V10_MARKETS:
            rec=(r.get("model_recs") or {}).get(market)
            if not rec:continue
            e=rec.get("winamax_eval") or {}
            try:c=v1007_candidate(r,rec,True)
            except Exception:c={"eligible":False,"reasons":["candidate evaluation unavailable"],"score":0,"profile":None}
            point=rec.get("point")
            jid_src=f"{run_id}|{r.get('game_pk')}|{market}|{norm_name(rec.get('name'))}|{point}"
            journal_id=hashlib.sha1(jid_src.encode()).hexdigest()
            price=num(e.get("price"),0)
            official=bool(e.get("official_selected"));preview=bool(e.get("official_preview_units"))
            official_units=int(num(e.get("official_units",e.get("units",0)),0)) if official else 0
            official_stake=round(official_units*UNIT,2)
            official_reason=e.get("official_reason") or ("retenu dans le plan officiel" if official else "non retenu")
            reasons=list(c.get("reasons") or [])
            if not official and official_reason and official_reason not in reasons:reasons.append(str(official_reason))
            out.append({
                "journal_version":JOURNAL_VERSION,"journal_id":journal_id,"run_id":run_id,"bot_version":VERSION,
                "analyzed_at":analyzed_at,"target_date":TARGET_DATE,"game_pk":r.get("game_pk"),"game_date":(r.get("game") or {}).get("gameDate"),
                "home":ctx.get("home"),"away":ctx.get("away"),"phase":phase,"seconds_to_game":round(num(r.get("seconds"),0),1),
                "market":market,"pick":rec.get("name"),"point":point,"model_proposed":True,
                "p_model_raw":round(num(rec.get("p_model"),.5),6),"p_effective":round(num(rec.get("p_effective",rec.get("p_model")),.5),6),
                "confidence":round(num(rec.get("confidence"),0),3),"quality":round(num(r.get("quality"),0),4),"refs":int(num(rec.get("refs"),0)),
                "p_market":round(num(rec.get("p_market"),0),6) if rec.get("p_market") is not None else None,
                "market_gap":round(num(rec.get("market_gap"),0),6) if rec.get("market_gap") is not None else None,
                "fair_raw":round(num(rec.get("fair"),0),4) if rec.get("fair") is not None else None,
                "fair_effective":round(num(rec.get("fair_effective",rec.get("fair")),0),4) if rec.get("fair_effective",rec.get("fair")) is not None else None,
                "min_price_raw":round(num(rec.get("min_price"),0),4) if rec.get("min_price") is not None else None,
                "min_price_effective":round(num(rec.get("min_price_effective",rec.get("min_price")),0),4) if rec.get("min_price_effective",rec.get("min_price")) is not None else None,
                "winamax_price":round(price,4) if price>1 else None,"edge_effective":round(num(e.get("edge"),0),6) if price>1 else None,"ev_effective":round(num(e.get("ev"),0),6) if price>1 else None,
                "eligible_before_slate":bool(c.get("eligible")),"candidate_score":round(num(c.get("score"),0),2),"risk_profile":c.get("profile"),
                "official_selected":official,"official_units":official_units,"official_stake_eur":official_stake,"official_reason":official_reason,
                "preview_selected":preview,"rejection_reasons":reasons,"selection_status":"OFFICIAL" if official else "PREVIEW" if preview else "REJECTED",
                "slate_score":round(num(r.get("slate_score"),0),2),"slate_grade":r.get("slate_grade"),
                "stability_alert":r.get("stability_alert"),"stability_delta":round(num(r.get("stability_delta"),0),6),"p_structural_raw":round(num(r.get("p_structural_raw"),.5),6),
                "home_lineup_confirmed":bool((ctx.get("home_lineup") or {}).get("confirmed")),"home_lineup_count":int(num((ctx.get("home_lineup") or {}).get("count"),0)),
                "away_lineup_confirmed":bool((ctx.get("away_lineup") or {}).get("confirmed")),"away_lineup_count":int(num((ctx.get("away_lineup") or {}).get("count"),0)),
                "home_starter":ctx.get("home_sp"),"away_starter":ctx.get("away_sp"),"unit_eur":round(UNIT,4),
                "result_status":"PENDING","result":None,"home_score":None,"away_score":None,"settled_at":None,
                "hypothetical_profit_1u_eur":None,"official_profit_eur":None
            })
    return out


def v1010_append_run(journal,results):
    rows=v1010_make_run_rows(results);known={r.get("journal_id") for r in journal};added=0
    for row in rows:
        if row["journal_id"] in known:continue
        journal.append(row);known.add(row["journal_id"]);added+=1
    return added


def v1010_settle_journal(journal,hist):
    changed=0
    for row in journal:
        if row.get("result") in ("W","L","P"):continue
        rec=hist.get(str(row.get("game_pk")))
        if not rec or rec.get("status")!="FINAL":continue
        hs=rec.get("home_score");as_=rec.get("away_score")
        if hs is None or as_ is None:continue
        res=v10_settle_market(row.get("market"),row.get("pick"),row.get("point"),row.get("home",""),row.get("away",""),hs,as_)
        if res not in ("W","L","P"):continue
        price=num(row.get("winamax_price"),0);unit=num(row.get("unit_eur"),UNIT);official_stake=num(row.get("official_stake_eur"),0)
        row.update({"result_status":"SETTLED","result":res,"home_score":int(num(hs)),"away_score":int(num(as_)),"settled_at":NOW.isoformat(),
                    "hypothetical_profit_1u_eur":v1010_profit(res,unit,price) if price>1 else None,
                    "official_profit_eur":v1010_profit(res,official_stake,price) if row.get("official_selected") and price>1 else None})
        changed+=1
    return changed


def v1010_journal_metrics(journal):
    settled=[r for r in journal if r.get("result") in ("W","L","P")]
    priced=[r for r in settled if num(r.get("winamax_price"),0)>1 and r.get("hypothetical_profit_1u_eur") is not None]
    official=[r for r in settled if r.get("official_selected") and r.get("official_profit_eur") is not None]
    hyp_profit=sum(num(r.get("hypothetical_profit_1u_eur")) for r in priced);hyp_stake=sum(num(r.get("unit_eur"),UNIT) for r in priced if r.get("result")!="P")
    off_profit=sum(num(r.get("official_profit_eur")) for r in official);off_stake=sum(num(r.get("official_stake_eur")) for r in official if r.get("result")!="P")
    return {"rows":len(journal),"settled":len(settled),"priced":len(priced),"official_settled":len(official),"hyp_profit":hyp_profit,"hyp_roi":hyp_profit/hyp_stake if hyp_stake else None,"official_profit":off_profit,"official_roi":off_profit/off_stake if off_stake else None}


def v1010_log_journal(journal,added=0,settled_now=0):
    m=v1010_journal_metrics(journal)
    logging.info("V10.0.10 LIVE JOURNAL | rows=%d +%d | settled=%d (+%d) | priced=%d hypROI=%s | official_settled=%d officialROI=%s",
                 m["rows"],added,m["settled"],settled_now,m["priced"],pct(m["hyp_roi"]) if m["hyp_roi"] is not None else "-",m["official_settled"],pct(m["official_roi"]) if m["official_roi"] is not None else "-")


def main():
    logging.info("="*68);logging.info("MLB BETTING BOT V%s | date MLB=%s",VERSION,TARGET_DATE);logging.info("="*68)
    if not ODDS_KEY:raise SystemExit("ODDS_API_KEY absente")
    discord_ok=discord_test();hist=load_history();journal=v1010_load_journal();state=load_state();settled=settle_history(hist);journal_settled=v1010_settle_journal(journal,hist)
    run_state=run_model_state(hist);disp_state=dispersion_state(hist);engine="learned-runs" if run_state["active"] else "base-runs";cal_state=calibration_state(hist,engine);skill=skill_state(hist,engine);states=(run_state,disp_state,cal_state,skill)
    logging.info("Historique V10 | %d matchs | réglés=%d",len(hist),settled);logging.info("Run ML n=%d actif=%s RMSE %.3f/%.3f gainProb=%.2f folds=%d",run_state["n"],run_state["active"],num(run_state["rmse_model"]),num(run_state["rmse_base"]),run_state["gain_prob"],run_state["folds"]);logging.info("NB alpha H/A %.2f/%.2f learned=%s n=%d | calibration n=%d active=%s gainProb=%.2f | skill n=%d poids modèle=%.2f",disp_state["alpha_home"],disp_state["alpha_away"],disp_state["learned"],disp_state["n"],cal_state["n"],cal_state["active"],cal_state["gain_prob"],skill["n"],skill["model_weight"])
    savant_league();games=mlb_schedule(TARGET_DATE);events=odds_api();matches=match_odds_events(games,events);logging.info("MLB=%d odds=%d appariés=%d",len(games),len(events),len(matches));results=[]
    for g in games:
        if parse_dt(g["gameDate"])<=NOW:continue
        pair=matches.get(str(g["gamePk"]))
        if not pair:logging.warning("Odds non appariées: %s @ %s",g["teams"]["away"]["team"]["name"],g["teams"]["home"]["team"]["name"]);continue
        try:r=analyze_base(g,pair[0],pair[1],states,hist);r["disp_state"]=disp_state;attach_model_recommendations(r);results.append(r)
        except Exception as e:logging.exception("Analyse %s: %s",g.get("gamePk"),e)
    portfolio=allocate_portfolio(results);journal_added=v1010_append_run(journal,results);published=0
    for r in results:
        rec=ensure_record(hist,r["game"]);snap=build_snapshot(r,rec);publish=should_publish(rec,snap);added=should_add_snapshot(rec,snap)
        if added:rec["snapshots"].append(snap)
        sync_recommendations(rec,r["evals"],snap);sent=False
        if discord_ok and publish:sent=send_game(r,snap,portfolio)
        if sent:mark_published(rec,[e for e in r["evals"] if e["selected"]],snap);published+=1
        logging.info("%s @ %s | %s %s | lineups=%d/%d statcast=%s/%s | %s %s %.1f/10 | qualified=%d bets=%d%s",r["ctx"]["away"],r["ctx"]["home"],r["phase"],snap["role"],r["ctx"]["home_lineup"]["count"],r["ctx"]["away_lineup"]["count"],r["ctx"]["home_statcast"]["available"],r["ctx"]["away_statcast"]["available"],r["verdict"]["type"],r["verdict"]["side"],r["verdict"]["confidence"],sum(e["qualified"] for e in r["evals"]),sum(e["selected"] for e in r["evals"])," | Discord update" if sent else "")
    write_history(hist);v1010_write_journal(journal)
    if discord_ok and results:
        send_top_messages(results,state);send_daily_plan(results)
    perf=performance(hist);v1010_log_journal(journal,journal_added,journal_settled)
    logging.info("V%s terminé | analyses=%d | messages=%d | exposition=%.2f/%.2f€ | snapshots=%d",VERSION,len(results),published,portfolio["allocated"],portfolio["daily_cap"],sum(len(r.get("snapshots",[])) for r in hist.values()));logging.info("Performance | games=%d direction=%s Brier modèle=%s marché=%s | bets=%d profit=%.2f€ ROI=%s | CLV=%s pts n=%d",perf["games"],pct(perf["direction"]) if perf["direction"] is not None else "-",f"{perf['brier_model']:.4f}" if perf["brier_model"] is not None else "-",f"{perf['brier_market']:.4f}" if perf["brier_market"] is not None else "-",perf["bets"],perf["profit"],pct(perf["roi"]) if perf["roi"] is not None else "-",f"{perf['clv_pts']:+.2f}" if perf["clv_pts"] is not None else "-",perf["clv_n"])


def v10_self_test():
    global VERSION
    current=VERSION;VERSION="10.0.9"
    try:_V1009_SELF_TEST_010()
    finally:VERSION=current
    assert VERSION=="10.0.10"
    rec={"market":"ML","name":"H","point":None,"p_model":.68,"p_effective":.61,"p_push":0,"confidence":7.8,"refs":3,"p_market":.57,"market_gap":.11,"fair":1.47,"fair_effective":1.64,"min_price":1.52,"min_price_effective":1.72,"winamax_eval":{"price":1.80,"edge":.054,"ev":.098,"official_selected":True,"official_units":1,"official_reason":"retenu dans le plan officiel"}}
    fake={"game_pk":1,"game":{"gameDate":"2026-08-12T18:00:00Z"},"phase":"FINAL","seconds":3600,"quality":.85,"stability_alert":"OK","stability_delta":.01,"p_structural_raw":.66,"slate_score":82,"slate_grade":"FORT","ctx":{"home":"H","away":"A","home_sp":"Starter H","away_sp":"Starter A","home_lineup":{"count":9,"confirmed":True},"away_lineup":{"count":9,"confirmed":True}},"model_recs":{"ML":rec}}
    rows=v1010_make_run_rows([fake],"testrun","2026-08-12T12:00:00+00:00");assert len(rows)==1 and rows[0]["model_proposed"] and rows[0]["official_selected"] and rows[0]["selection_status"]=="OFFICIAL"
    j=list(rows);hist={"1":{"game_pk":1,"status":"FINAL","home":"H","away":"A","home_score":5,"away_score":3}};assert v1010_settle_journal(j,hist)==1 and j[0]["result"]=="W" and abs(j[0]["hypothetical_profit_1u_eur"]-UNIT*.80)<1e-9 and abs(j[0]["official_profit_eur"]-UNIT*.80)<1e-9
    before=len(j);known={x["journal_id"] for x in j};added=0
    for row in rows:
        if row["journal_id"] not in known:j.append(row);known.add(row["journal_id"]);added+=1
    assert added==0 and len(j)==before
    print("SELF-TEST MLB BETTING BOT V10.0.10 OK")
'''

head,tail=text.rsplit(marker,1)
p.write_text(head+'\n\n'+block+'\n'+marker+tail,encoding='utf-8')
