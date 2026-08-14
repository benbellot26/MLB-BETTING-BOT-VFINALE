from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from .config import LIVE_FILE, REPORT_FILE

def _num(x,d=0.0):
    try:
        y=float(x); return y if math.isfinite(y) else d
    except Exception:return d

def _norm(s): return "".join(c.lower() for c in str(s or "") if c.isalnum())

def load_rows(path=LIVE_FILE):
    if not Path(path).exists(): return []
    out=[]
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: out.append(json.loads(line))
        except Exception: pass
    return out

def write_rows(rows,path=LIVE_FILE):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text("\n".join(json.dumps(x,ensure_ascii=False,separators=(",",":")) for x in rows)+("\n" if rows else ""),encoding="utf-8")

def is_final(game):
    s=game.get("status") or {}
    return str(s.get("abstractGameState") or "").lower()=="final" or str(s.get("codedGameState") or "").upper()=="F" or str(s.get("detailedState") or "").lower() in {"final","game over","completed early"}

def settle_rows(core,rows):
    dates=sorted({str(r.get("target_date")) for r in rows if r.get("result_status")!="FINAL" and r.get("target_date")}); games={}
    for day in dates:
        try:
            for g in core.mlb_schedule(day): games[str(g.get("gamePk"))]=g
        except Exception: core.logging.exception("V11 settlement unavailable for %s",day)
    changed=0; now=datetime.now(timezone.utc).isoformat()
    for r in rows:
        if r.get("result_status")=="FINAL": continue
        g=games.get(str(r.get("game_pk")))
        if not g or not is_final(g): continue
        teams=g.get("teams") or {}; hs=int(_num((teams.get("home") or {}).get("score"))); aps=int(_num((teams.get("away") or {}).get("score")))
        if hs==aps: continue
        home,away=str(r.get("home")),str(r.get("away")); winner=home if hs>aps else away; y=1 if winner==home else 0
        p10=max(.001,min(.999,_num(r.get("base_v10_p_home"),.5))); p112=max(.001,min(.999,_num(r.get("v11_2_p_home"),.5))); v10=r.get("base_v10_pick") or (home if p10>=.5 else away); v11=r.get("v11_3_pick")
        r.update({"result_status":"FINAL","winner":winner,"home_score":hs,"away_score":aps,"v10_correct":v10==winner,"v11_3_correct":v11==winner,"v11_net_correction":1 if v11==winner and v10!=winner else -1 if v10==winner and v11!=winner else 0,"v10_brier":round((p10-y)**2,8),"v11_2_brier":round((p112-y)**2,8),"v10_logloss":round(-(y*math.log(p10)+(1-y)*math.log(1-p10)),8),"v11_2_logloss":round(-(y*math.log(p112)+(1-y)*math.log(1-p112)),8),"settled_at":now})
        for b in r.get("official_bets") or []: settle_bet(b,r)
        changed+=1
    return changed

def settle_bet(b,row):
    if b.get("status") in {"WIN","LOSS","PUSH"} or row.get("result_status")!="FINAL": return False
    hs,aps=_num(row.get("home_score")),_num(row.get("away_score")); home,away=str(row.get("home")),str(row.get("away")); m=str(b.get("market") or "").upper(); pick=str(b.get("pick") or ""); point=_num(b.get("point"))
    if m=="ML": winner=home if hs>aps else away if aps>hs else None; res="WIN" if winner and _norm(pick)==_norm(winner) else "LOSS" if winner else "PUSH"
    elif m=="RUNLINE":
        margin=hs-aps+point if _norm(pick)==_norm(home) else aps-hs+point if _norm(pick)==_norm(away) else None
        if margin is None:return False
        res="WIN" if margin>1e-9 else "LOSS" if margin<-1e-9 else "PUSH"
    elif m=="TOTAL":
        d=hs+aps-point
        if abs(d)<=1e-9:res="PUSH"
        elif pick.lower()=="over":res="WIN" if d>0 else "LOSS"
        elif pick.lower()=="under":res="WIN" if d<0 else "LOSS"
        else:return False
    else:return False
    u=max(0,_num(b.get("units"))); price=_num(b.get("winamax_price")); pnl=u*(price-1) if res=="WIN" and price>1 else -u if res=="LOSS" else 0.0 if res=="PUSH" else None
    b.update({"status":res,"profit_units":round(pnl,4) if pnl is not None else None,"settled_at":datetime.now(timezone.utc).isoformat()}); return True

def capture_official_bets(core,result):
    bets=[]
    for rec in core.v1011_iter_options(result):
        e=rec.get("winamax_eval") or {}
        if not e.get("official_selected"):continue
        price=_num(e.get("price")); units=_num(e.get("official_units",e.get("units")))
        bets.append({"market":str(rec.get("market") or "").upper(),"pick":rec.get("name"),"point":rec.get("point"),"units":units,"stake_eur":round(units*_num(getattr(core,"UNIT",.5),.5),2),"winamax_price":round(price,4) if price>1 else None,"p_effective":round(_num(rec.get("p_effective",rec.get("p_model")),.5),6),"confidence":round(_num(rec.get("confidence")),4),"status":"PENDING","profit_units":None,"settled_at":None,"price_gate":e.get("v11_price_gate")})
    return bets

def canonical_final(rows):
    best={}
    for r in rows:
        if r.get("result_status")!="FINAL" or not r.get("game_pk"):continue
        k=str(r["game_pk"]); rank=str(r.get("analyzed_at") or "")
        if k not in best or rank>best[k][0]:best[k]=(rank,r)
    return [v[1] for v in best.values()]

def comparison_summary(rows):
    xs=canonical_final(rows); n=len(xs)
    if not n:return {"settled_games":0}
    w10=sum(bool(x.get("v10_correct")) for x in xs); w11=sum(bool(x.get("v11_3_correct")) for x in xs); vals=lambda f:[_num(x.get(f)) for x in xs if x.get(f) is not None]; avg=lambda f: round(sum(vals(f))/len(vals(f)),8) if vals(f) else None; corr=sum(_num(x.get("v11_net_correction"))>0 for x in xs); reg=sum(_num(x.get("v11_net_correction"))<0 for x in xs); by_grade={}
    for g in ("FORT","BON","PRUDENCE","FAIBLE"):
        z=[x for x in xs if x.get("grade")==g]
        if z:
            w=sum(bool(x.get("v11_3_correct")) for x in z); by_grade[g]={"n":len(z),"wins":w,"accuracy":w/len(z)}
    return {"settled_games":n,"v10_wins":w10,"v11_3_wins":w11,"v10_accuracy":w10/n,"v11_3_accuracy":w11/n,"v11_corrections":corr,"v11_regressions":reg,"v11_net_corrections":corr-reg,"v10_brier":avg("v10_brier"),"v11_2_brier":avg("v11_2_brier"),"v10_logloss":avg("v10_logloss"),"v11_2_logloss":avg("v11_2_logloss"),"by_grade":by_grade}

def finance_summary(rows):
    best={}
    for r in rows:
        if not r.get("official_bets") or not r.get("game_pk"):continue
        k=str(r["game_pk"]); rank=str(r.get("analyzed_at") or "")
        if k not in best or rank>best[k][0]:best[k]=(rank,r)
    bets=[b for _,r in best.values() for b in (r.get("official_bets") or [])]; settled=[b for b in bets if b.get("status") in {"WIN","LOSS","PUSH"}]; stake=sum(_num(b.get("units")) for b in settled if b.get("status")!="PUSH"); known=[b for b in settled if b.get("profit_units") is not None]; pnl=sum(_num(b.get("profit_units")) for b in known); by={}
    for m in ("ML","RUNLINE","TOTAL"):
        z=[b for b in settled if b.get("market")==m]
        if z:
            st=sum(_num(b.get("units")) for b in z if b.get("status")!="PUSH"); kz=[b for b in z if b.get("profit_units") is not None]; pu=sum(_num(b.get("profit_units")) for b in kz); by[m]={"n":len(z),"wins":sum(b.get("status")=="WIN" for b in z),"losses":sum(b.get("status")=="LOSS" for b in z),"pushes":sum(b.get("status")=="PUSH" for b in z),"profit_units":pu if kz else None,"roi":pu/st if st and len(kz)==len(z) else None}
    return {"bets_recorded":len(bets),"settled":len(settled),"wins":sum(b.get("status")=="WIN" for b in settled),"losses":sum(b.get("status")=="LOSS" for b in settled),"pushes":sum(b.get("status")=="PUSH" for b in settled),"staked_units":stake,"profit_units":pnl if known else None,"roi":pnl/stake if stake and len(known)==len(settled) else None,"by_market":by}

def write_report(report,path=REPORT_FILE):
    Path(path).parent.mkdir(parents=True,exist_ok=True); Path(path).write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
