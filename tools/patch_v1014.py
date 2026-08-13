from pathlib import Path
from textwrap import dedent

p=Path('bot.py')
s=p.read_text(encoding='utf-8')
marker='# ==================== V10.0.14 ROBUST SELECTOR ====================='
if marker in s:
    print('V10.0.14 already patched')
    raise SystemExit(0)
needle='if __name__=="__main__":\n'
if needle not in s:
    raise SystemExit('main guard not found')
layer=dedent(r'''

# ==================== V10.0.14 ROBUST SELECTOR =====================
# Selection/ranking-only layer. Baseball projections and V10.0.13 market
# probabilities remain unchanged. The official plan ranks eligible options by
# robustness: data quality, confidence, reference-book depth, structural/model
# stability and observed EARLY->LATE->FINAL consistency from the live journal.
# Winamax remains informational only.
_V1013_SELF_TEST_014=v10_self_test
_V1013_CANDIDATE_014=v1011_candidate
_V1013_ALLOCATE_014=allocate_portfolio
_V1013_MAKE_RUN_ROWS_014=v1010_make_run_rows
_V1013_JOURNAL_METRICS_014=v1010_journal_metrics

VERSION="10.0.14"
SELECTION_VERSION="robust-selector-v5"
V1014_SCORE_PENALTY_FACTOR=float(os.getenv("V1014_SCORE_PENALTY_FACTOR","160") or 160)
V1014_MAX_UNCERTAINTY=clamp(float(os.getenv("V1014_MAX_UNCERTAINTY","0.030") or .030),.01,.06)
V1014_LIVE_STABILITY_ENABLED=str(os.getenv("V1014_LIVE_STABILITY_ENABLED","1")).strip().lower() not in ("0","false","no","off")
_V1014_PRIOR_INDEX=None


def v1014_point_key(point):
    return None if point is None else round(num(point),3)


def v1014_option_key(game_pk,market,pick,point):
    return (str(game_pk),str(market or ""),norm_name(pick),v1014_point_key(point))


def v1014_load_prior_index():
    global _V1014_PRIOR_INDEX
    if _V1014_PRIOR_INDEX is not None:return _V1014_PRIOR_INDEX
    idx={}
    if V1014_LIVE_STABILITY_ENABLED and JOURNAL_FILE.exists():
        try:
            for line in JOURNAL_FILE.read_text(encoding="utf-8").splitlines():
                if not line.strip():continue
                row=json.loads(line)
                if row.get("target_date")!=TARGET_DATE or row.get("market")=="COMBO":continue
                if row.get("p_effective") is None:continue
                k=v1014_option_key(row.get("game_pk"),row.get("market"),row.get("pick"),row.get("point"))
                idx.setdefault(k,[]).append(row)
            for k in idx:idx[k].sort(key=lambda x:str(x.get("analyzed_at") or ""))
        except Exception as exc:
            logging.warning("V10.0.14 stabilité journal indisponible: %s",exc);idx={}
    _V1014_PRIOR_INDEX=idx
    return idx


def v1014_live_stability(result,rec):
    k=v1014_option_key(result.get("game_pk"),rec.get("market"),rec.get("name"),rec.get("point"));xs=v1014_load_prior_index().get(k,[])
    current=clamp(num(rec.get("p_effective"),.5),.001,.999);vals=[clamp(num(x.get("p_effective"),.5),.001,.999) for x in xs]
    phases=sorted({str(x.get("phase") or "") for x in xs if x.get("phase")})
    if not vals:return {"n":0,"phases":phases,"spread":0.0,"trend":0.0,"last_delta":0.0,"penalty":0.0,"stable":False}
    allv=vals+[current];spread=max(allv)-min(allv);trend=current-vals[0];last_delta=current-vals[-1]
    penalty=min(.020,spread*.25+max(0.0,-trend)*.20+max(0.0,-last_delta)*.10)
    stable=len(xs)>=2 and len(phases)>=2 and spread<=.025 and trend>=-.015
    return {"n":len(xs),"phases":phases,"spread":spread,"trend":trend,"last_delta":last_delta,"penalty":penalty,"stable":stable}


def v1014_uncertainty(result,rec):
    conf=num(rec.get("confidence"),0);q=clamp(num(result.get("quality"),0),0,1);refs=int(num(rec.get("refs"),0));delta=abs(num(result.get("stability_delta"),0))
    quality_pen=max(0.0,1.0-q)*.025
    conf_pen=max(0.0,7.5-conf)*.003
    refs_pen=.004 if refs<=2 else .002 if refs==3 else 0.0
    structural_pen=min(.006,delta*.12)
    live=v1014_live_stability(result,rec)
    total=min(V1014_MAX_UNCERTAINTY,quality_pen+conf_pen+refs_pen+structural_pen+num(live.get("penalty"),0))
    return {"total":total,"quality":quality_pen,"confidence":conf_pen,"refs":refs_pen,"structural":structural_pen,"live":live}


def v1011_candidate(result,rec,require_phase=True):
    base=_V1013_CANDIDATE_014(result,rec,require_phase);pe=clamp(num(rec.get("p_effective"),.5),.001,.999);u=v1014_uncertainty(result,rec);pen=num(u.get("total"),0);live=u.get("live") or {}
    safe=max(.5,pe-pen);legacy=num(base.get("score"),0);bonus=1.5 if live.get("stable") else 0.0;robust=clamp(legacy-V1014_SCORE_PENALTY_FACTOR*pen+bonus,0,100)
    base.update({"legacy_score":legacy,"score":robust,"robust_score":robust,"safe_probability":safe,"uncertainty_penalty":pen,"uncertainty":u,"live_stability":live})
    rec["selection_version"]=SELECTION_VERSION;rec["selection_safe_probability"]=safe;rec["selection_uncertainty_penalty"]=pen;rec["selection_robust_score"]=robust;rec["selection_legacy_score"]=legacy;rec["selection_live_stability"]=live
    return base


def allocate_portfolio(results):
    portfolio=_V1013_ALLOCATE_014(results)
    for r in results or []:
        for rec in v1011_iter_options(r):
            c=v1011_candidate(r,rec,False);e=v1012_ensure_execution(rec)
            e["selection_version"]=SELECTION_VERSION;e["robust_score"]=round(num(c.get("score"),0),2);e["safe_probability"]=round(num(c.get("safe_probability"),.5),6);e["uncertainty_penalty"]=round(num(c.get("uncertainty_penalty"),0),6)
            if e.get("official_selected"):
                e["official_reason"]=f"retenu par le score robuste V10.0.14 ({num(c.get('score')):.1f}/100, {str(r.get('phase','EARLY')).upper()})"
                e["reason"]="OK V10.0.14";e["portfolio_reason"]="PARI OFFICIEL V10.0.14"
    if isinstance(_V1007_LAST_SLATE,dict):_V1007_LAST_SLATE["selector_version"]=SELECTION_VERSION
    portfolio["selector_version"]=SELECTION_VERSION
    logging.info("V10.0.14 ROBUST SELECTOR | selected=%d | score=%s | Winamax gates=OFF",int(num((_V1007_LAST_SLATE or {}).get("official_count"),0)),f"{num((_V1007_LAST_SLATE or {}).get('score')):.1f}")
    return portfolio


def v1014_stability_text(c):
    live=c.get("live_stability") or {};n=int(num(live.get("n"),0))
    if live.get("stable"):return f"🟢 stable sur {n+1} observations"
    if n:
        return f"variation {num(live.get('spread'))*100:.1f} pt sur {n+1} observations"
    return "1re observation de la journée"


def v1011_plan_pick_text(item,index=None):
    r=item["result"];rec=item["rec"];e=v1012_ensure_execution(rec);c=v1011_candidate(r,rec,False);u=num(e.get("official_units"),0);price=num(e.get("price"),0);prefix=f"**#{index}** " if index is not None else "• ";price_txt=f"{price:.2f}" if price>1 else "non récupérée"
    return f"{prefix}✅ **{v1011_market_label(rec)} — {u:g}u = {u*UNIT:.2f} €**\n{r['ctx']['away']} @ {r['ctx']['home']} • **{v1012_phase_badge(r.get('phase'))}**\nChance prudente **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • robustesse **{num(c.get('score')):.0f}/100**\n{v1014_stability_text(c)} • Winamax **{price_txt}** *(info)*"


def v1010_make_run_rows(results,run_id=None,analyzed_at=None):
    rows=_V1013_MAKE_RUN_ROWS_014(results,run_id,analyzed_at);lookup={}
    for r in results or []:
        for rec in v1011_iter_options(r):lookup[v1014_option_key(r.get("game_pk"),rec.get("market"),rec.get("name"),rec.get("point"))]=(r,rec)
    for row in rows:
        row["selection_version"]=SELECTION_VERSION
        if row.get("market")=="COMBO":continue
        pair=lookup.get(v1014_option_key(row.get("game_pk"),row.get("market"),row.get("pick"),row.get("point")))
        if not pair:continue
        c=v1011_candidate(pair[0],pair[1],False);live=c.get("live_stability") or {}
        row["legacy_candidate_score"]=round(num(c.get("legacy_score"),0),2);row["robust_score"]=round(num(c.get("score"),0),2);row["safe_probability"]=round(num(c.get("safe_probability"),.5),6);row["uncertainty_penalty"]=round(num(c.get("uncertainty_penalty"),0),6)
        row["stability_history_n"]=int(num(live.get("n"),0));row["stability_history_spread"]=round(num(live.get("spread"),0),6);row["stability_history_trend"]=round(num(live.get("trend"),0),6);row["stability_history_stable"]=bool(live.get("stable"))
        row["canonical_official_key"]="|".join(map(str,v1014_option_key(row.get("game_pk"),row.get("market"),row.get("pick"),row.get("point"))))
    return rows


def v1014_official_event_key(row):
    if row.get("market")=="COMBO":
        legs=row.get("combo_legs") or [];sig=tuple(sorted(v1014_option_key(x.get("game_pk"),x.get("market"),x.get("pick"),x.get("point")) for x in legs));return ("COMBO",sig)
    return ("SINGLE",)+v1014_option_key(row.get("game_pk"),row.get("market"),row.get("pick"),row.get("point"))


def v1010_journal_metrics(journal):
    base=_V1013_JOURNAL_METRICS_014(journal);events={}
    official=sorted((r for r in journal if r.get("official_selected") and r.get("result") in ("W","L","P")),key=lambda r:str(r.get("analyzed_at") or ""))
    for row in official:events.setdefault(v1014_official_event_key(row),row)
    canonical=list(events.values());priced=[r for r in canonical if r.get("official_profit_eur") is not None]
    profit=sum(num(r.get("official_profit_eur"),0) for r in priced);stake=sum(num(r.get("official_stake_eur"),0) for r in priced if r.get("result")!="P")
    base.update({"official_settled":len(canonical),"official_priced":len(priced),"official_profit":profit,"official_roi":profit/stake if stake else None,"official_canonical_events":len(canonical)})
    return base


def v1010_log_journal(journal,added=0,settled_now=0):
    m=v1010_journal_metrics(journal)
    logging.info("V%s LIVE JOURNAL | rows=%d +%d | settled=%d (+%d) | priced=%d hypROI=%s | official canonical=%d priced=%d ROI=%s",VERSION,m["rows"],added,m["settled"],settled_now,m["priced"],pct(m["hyp_roi"]) if m["hyp_roi"] is not None else "-",m["official_settled"],m.get("official_priced",0),pct(m["official_roi"]) if m["official_roi"] is not None else "-")


def v10_self_test():
    global VERSION,_V1014_PRIOR_INDEX
    current=VERSION;VERSION="10.0.13"
    try:_V1013_SELF_TEST_014()
    finally:VERSION=current
    assert VERSION=="10.0.14"
    _V1014_PRIOR_INDEX={}
    fake={"phase":"FINAL","quality":.85,"stability_alert":"OK","stability_delta":.01,"game_pk":991,"ctx":{"home":"H","away":"A","home_sp":"Starter H","away_sp":"Starter A","home_lineup":{"count":9},"away_lineup":{"count":9}}}
    rec={"market":"ML","name":"H","point":None,"p_model":.74,"p_effective":.625,"p_push":0,"confidence":7.2,"refs":3,"p_market":.60,"min_price_effective":1.70,"winamax_eval":{}}
    c=v1011_candidate(fake,rec,True);assert c["eligible"] and c["uncertainty_penalty"]>0 and c["score"]<c["legacy_score"] and c["safe_probability"]<rec["p_effective"]
    dup=[{"official_selected":True,"result":"W","market":"ML","game_pk":1,"pick":"H","point":None,"analyzed_at":"1","official_profit_eur":.4,"official_stake_eur":.5,"unit_eur":.5,"winamax_price":1.8,"hypothetical_profit_1u_eur":.4},
         {"official_selected":True,"result":"W","market":"ML","game_pk":1,"pick":"H","point":None,"analyzed_at":"2","official_profit_eur":.4,"official_stake_eur":.5,"unit_eur":.5,"winamax_price":1.8,"hypothetical_profit_1u_eur":.4}]
    m=v1010_journal_metrics(dup);assert m["official_settled"]==1 and m["official_priced"]==1
    _V1014_PRIOR_INDEX=None
    print("SELF-TEST MLB BETTING BOT V10.0.14 OK")

''')
s=s.replace(needle,layer+'\n'+needle,1)
p.write_text(s,encoding='utf-8')
print('patched bot.py with V10.0.14 robust selector')
