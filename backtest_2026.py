#!/usr/bin/env python3
"""Leakage-safe MLB 2026 walk-forward backtest for V9 vs V10.0.5.

This is intentionally a pure-baseball backtest: no historical bookmaker odds are
invented. It reconstructs pregame team/player/starter/bullpen state exclusively
from games completed earlier in the season, then scores the prediction after the
actual game. Historical Winamax ROI/EV is therefore NOT reported.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import math
import os
import random
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

YEAR = 2026
START = os.getenv("BACKTEST_START", "2026-03-01")
END = os.getenv("BACKTEST_END", "2026-08-11")
OUT = Path(os.getenv("BACKTEST_OUT", "data/mlb_backtest_2026.jsonl"))
REPORT_JSON = Path(os.getenv("BACKTEST_REPORT_JSON", "data/mlb_backtest_2026_report.json"))
REPORT_MD = Path(os.getenv("BACKTEST_REPORT_MD", "data/mlb_backtest_2026_report.md"))
WORKERS = max(2, min(20, int(os.getenv("BACKTEST_WORKERS", "12"))))
TIMEOUT = 25
STRUCTURAL_CAP = 0.75
ALPHA = 0.12
RESIDUAL_MIN_GAMES = 450
CAL_MIN_GAMES = 500
RETRAIN_EVERY = 50

PARK={"Arizona Diamondbacks":1.04,"Athletics":1.05,"Oakland Athletics":1.05,"Atlanta Braves":1.01,"Baltimore Orioles":1.01,"Boston Red Sox":1.03,"Chicago White Sox":1.00,"Chicago Cubs":1.02,"Cincinnati Reds":1.05,"Cleveland Guardians":0.98,"Colorado Rockies":1.14,"Detroit Tigers":0.98,"Houston Astros":1.00,"Kansas City Royals":0.99,"Los Angeles Angels":1.01,"Los Angeles Dodgers":0.98,"Miami Marlins":0.96,"Milwaukee Brewers":1.00,"Minnesota Twins":0.99,"New York Mets":0.98,"New York Yankees":1.03,"Philadelphia Phillies":1.02,"Pittsburgh Pirates":0.97,"San Diego Padres":0.97,"San Francisco Giants":0.94,"Seattle Mariners":0.96,"St. Louis Cardinals":1.00,"Tampa Bay Rays":0.98,"Texas Rangers":1.02,"Toronto Blue Jays":1.01,"Washington Nationals":1.00}


def num(x, d=0.0):
    try:
        y=float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def clamp(x,a=.001,b=.999): return max(a,min(b,x))
def logit(p):
    p=clamp(p,.001,.999); return math.log(p/(1-p))
def sigmoid(x): return 1/(1+math.exp(-max(-30,min(30,x))))


def get_json(url, params=None, retries=4):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",")
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"MLB-Betting-Bot-Backtest/2026","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8","replace"))
        except Exception as e:
            last=e
            if i>=retries: raise
            time.sleep(.6*(i+1))
    raise last


def mlb(path,params=None): return get_json("https://statsapi.mlb.com/api/"+path.lstrip("/"),params)


def schedule():
    d=mlb("v1/schedule",{"sportId":1,"startDate":START,"endDate":END,"hydrate":"linescore"})
    out=[]
    for block in d.get("dates",[]):
        for g in block.get("games",[]):
            if g.get("gameType")!="R": continue
            if g.get("status",{}).get("abstractGameState")!="Final": continue
            try:
                hs=int(g["teams"]["home"]["score"]); a=int(g["teams"]["away"]["score"])
            except Exception:
                continue
            out.append({
                "game_pk":g["gamePk"],"game_date":g["gameDate"],
                "home_id":g["teams"]["home"]["team"]["id"],"home":g["teams"]["home"]["team"]["name"],
                "away_id":g["teams"]["away"]["team"]["id"],"away":g["teams"]["away"]["team"]["name"],
                "home_score":hs,"away_score":a,
            })
    out.sort(key=lambda x:(x["game_date"],x["game_pk"]))
    return out


def fetch_box(pk):
    return pk, mlb(f"v1/game/{pk}/boxscore")


def fetch_boxes(games):
    boxes={}; total=len(games)
    print(f"Fetching {total} boxscores with {WORKERS} workers ...",flush=True)
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs={ex.submit(fetch_box,g["game_pk"]):g["game_pk"] for g in games}
        done=0
        for fut in cf.as_completed(futs):
            pk=futs[fut]
            try:
                k,b=fut.result(); boxes[k]=b
            except Exception as e:
                print(f"WARN boxscore {pk}: {e}",flush=True)
            done+=1
            if done%100==0 or done==total: print(f"  boxscores {done}/{total}",flush=True)
    return boxes


def outs_from_stat(st):
    if st is None:return 0
    o=num(st.get("outs"),-1)
    if o>=0:return int(round(o))
    s=str(st.get("inningsPitched","0"))
    try:
        if "." not in s:return int(float(s))*3
        a,b=s.split(".",1); return int(a)*3+int((b or "0")[0])
    except Exception:return 0


def blank_batting():
    return {"pa":0.0,"ab":0.0,"h":0.0,"d2":0.0,"d3":0.0,"hr":0.0,"bb":0.0,"hbp":0.0,"sf":0.0}


def add_batting(dst,st):
    if not st:return
    dst["ab"]+=num(st.get("atBats")); dst["h"]+=num(st.get("hits")); dst["d2"]+=num(st.get("doubles")); dst["d3"]+=num(st.get("triples")); dst["hr"]+=num(st.get("homeRuns")); dst["bb"]+=num(st.get("baseOnBalls")); dst["hbp"]+=num(st.get("hitByPitch")); dst["sf"]+=num(st.get("sacFlies")); dst["pa"]+=num(st.get("plateAppearances"),num(st.get("atBats"))+num(st.get("baseOnBalls"))+num(st.get("hitByPitch"))+num(st.get("sacFlies")))


def batting_rates(st,lg):
    ab=st["ab"]; h=st["h"]; singles=max(0,h-st["d2"]-st["d3"]-st["hr"]); tb=singles+2*st["d2"]+3*st["d3"]+4*st["hr"]
    obp_den=ab+st["bb"]+st["hbp"]+st["sf"]
    obp=(h+st["bb"]+st["hbp"])/obp_den if obp_den>0 else lg["obp"]
    slg=tb/ab if ab>0 else lg["slg"]
    return {"obp":obp,"slg":slg,"ops":obp+slg}


def blank_team():
    return {"games":0,"rf":0.0,"ra":0.0,"bat":blank_batting(),"pitch_outs":0.0,"er":0.0,"h_allowed":0.0,"bb_allowed":0.0,"recent":deque(maxlen=10),"bullpen":deque(maxlen=12)}


def blank_pitcher(): return {"outs":0.0,"er":0.0,"h":0.0,"bb":0.0,"so":0.0,"starts":0.0}


def league_baseline(team_state):
    teams=[s for s in team_state.values() if s["games"]>0]
    if not teams:return {"rpg":4.45,"era":4.35,"ops":.710,"obp":.320,"slg":.390,"whip":1.32}
    games=sum(s["games"] for s in teams)
    rf=sum(s["rf"] for s in teams)
    outs=sum(s["pitch_outs"] for s in teams); er=sum(s["er"] for s in teams); ha=sum(s["h_allowed"] for s in teams); bb=sum(s["bb_allowed"] for s in teams)
    agg=blank_batting()
    for s in teams:
        for k in agg: agg[k]+=s["bat"][k]
    prior={"obp":.320,"slg":.390}; br=batting_rates(agg,prior)
    return {"rpg":rf/games if games else 4.45,"era":27*er/outs if outs else 4.35,"ops":br["ops"],"obp":br["obp"],"slg":br["slg"],"whip":3*(ha+bb)/outs if outs else 1.32}


def team_hitting(s,lg):
    br=batting_rates(s["bat"],lg); return {"runsPerGame":s["rf"]/s["games"] if s["games"] else lg["rpg"],**br}


def team_pitching(s,lg):
    return {"gamesPlayed":s["games"],"runs":s["ra"],"era":27*s["er"]/s["pitch_outs"] if s["pitch_outs"] else lg["era"],"whip":3*(s["h_allowed"]+s["bb_allowed"])/s["pitch_outs"] if s["pitch_outs"] else lg["whip"]}


def recent_context(s,lg):
    xs=list(s["recent"])
    if not xs:return {"games":0,"win_pct":.5,"run_diff_pg":0.0,"runs_pg":lg["rpg"]}
    n=len(xs); rf=sum(x[0] for x in xs); ra=sum(x[1] for x in xs)
    return {"games":n,"win_pct":sum(x[0]>x[1] for x in xs)/n,"run_diff_pg":(rf-ra)/n,"runs_pg":rf/n}


def pitcher_profile(ps,lg):
    outs=ps["outs"]; ip=outs/3; wr=ip/(ip+35); wk=ip/(ip+25)
    re=27*ps["er"]/outs if outs else lg["era"]; rw=3*(ps["h"]+ps["bb"])/outs if outs else lg["whip"]; rk=27*ps["so"]/outs if outs else 8.3; rb=27*ps["bb"]/outs if outs else 3.2
    return {"ip":ip,"gs":ps["starts"],"era":clamp(lg["era"]+wr*(re-lg["era"]),2.1,6.8),"whip":clamp(lg["whip"]+wr*(rw-lg["whip"]),.9,1.8),"k9":clamp(8.3+wk*(rk-8.3),4.5,13),"bb9":clamp(3.2+wk*(rb-3.2),1,6)}


def bullpen_profile(s,game_day,lg):
    prior_era=27*s["er"]/s["pitch_outs"] if s["pitch_outs"] else lg["era"]
    weighted=outs=er=h=bb=0.0; seen=0
    for z in s["bullpen"]:
        age=(game_day-z["date"]).days
        if age<1 or age>5:continue
        weighted+=z["pitches"]*{1:1.0,2:.65,3:.40,4:.25,5:.15}.get(age,.1);outs+=z["outs"];er+=z["er"];h+=z["h"];bb+=z["bb"];seen+=1
    ip=outs/3; recent_era=27*er/outs if outs else prior_era; recent_whip=3*(h+bb)/outs if outs else lg["whip"];w=ip/(ip+18)
    return {"load":clamp(weighted/180,0,1.5),"era":clamp(prior_era+w*(recent_era-prior_era),2.2,7.0),"whip":clamp(lg["whip"]+w*(recent_whip-lg["whip"]),.85,1.9),"ip":ip,"games":seen}


def lineup_ops(box_side,batter_state,lg):
    ids=(box_side or {}).get("battingOrder") or []; players=(box_side or {}).get("players") or {}; weights=[1.10,1.07,1.12,1.10,1.04,.99,.94,.89,.84]; vals=[]
    for i,pid in enumerate(ids[:9]):
        bs=batter_state.get(int(pid))
        if not bs or bs["pa"]<20:continue
        vals.append((batting_rates(bs,lg)["ops"],weights[i]))
    return {"count":len(ids[:9]),"weighted_ops":sum(v*w for v,w in vals)/sum(w for _,w in vals) if len(vals)>=5 else None,"known":len(vals)}


def expected_starter_ip(sp):
    gs=max(0.0,num(sp.get("gs")));ip=max(0.0,num(sp.get("ip")));raw=ip/gs if gs>=3 and ip>0 else 5.3;w=gs/(gs+8.0);return clamp(5.3+w*(raw-5.3),4.0,6.5)


def safe_ratio(v,base,lo=.65,hi=1.55):return 1.0 if base<=0 else clamp(num(v,base)/base,lo,hi)


def base_v9(own_h,opp_p,recent,park,home,lg):
    rpg=num(own_h.get("runsPerGame"),lg["rpg"]);gp=max(1,num(opp_p.get("gamesPlayed"),0));opp_ra=num(opp_p.get("runs"),0)/gp if num(opp_p.get("runs"),0)>0 else lg["rpg"]*num(opp_p.get("era"),lg["era"])/lg["era"];rr=recent["runs_pg"] if recent["games"]>=5 else rpg
    return clamp(mean([rpg,opp_ra,rr])*park+(0.08 if home else 0),2.2,7.2)


def base_v10_raw(own_h,opp_p,recent,opp_sp,opp_bp,lineup,park,home,lg):
    rpg=num(own_h.get("runsPerGame"),lg["rpg"]);ops=num(own_h.get("ops"),lg["ops"]);gp=max(1.0,num(opp_p.get("gamesPlayed"),0));runs_allowed=num(opp_p.get("runs"),0);opp_ra=runs_allowed/gp if runs_allowed>0 else lg["rpg"]*safe_ratio(num(opp_p.get("era"),lg["era"]),lg["era"],.72,1.35)
    log_mu=math.log(lg["rpg"]);log_mu+=.34*math.log(safe_ratio(rpg,lg["rpg"],.70,1.35));log_mu+=.20*math.log(safe_ratio(ops,lg["ops"],.82,1.18));log_mu+=.14*math.log(safe_ratio(opp_ra,lg["rpg"],.72,1.38))
    if recent["games"]>=5:log_mu+=.08*math.log(safe_ratio(recent["runs_pg"],lg["rpg"],.72,1.38))
    sip=expected_starter_ip(opp_sp); ss=sip/9; bs=1-ss; spq=(opp_sp["era"]-lg["era"])/1.45+.45*(opp_sp["whip"]-lg["whip"])/.28+.18*((opp_sp["bb9"]-3.2)/1.4-(opp_sp["k9"]-8.3)/2.4);log_mu+=ss*clamp(spq,-1.10,1.10)*.23
    bpq=(opp_bp["era"]-lg["era"])/1.55+.35*(opp_bp["whip"]-lg["whip"])/.30+.35*(opp_bp["load"]-.5)/.60;log_mu+=bs*clamp(bpq,-1.0,1.2)*.22
    if lineup.get("weighted_ops") is not None and lineup.get("count",0)>=7:log_mu+=clamp(lineup["count"]/9,0,1)*.18*clamp((lineup["weighted_ops"]-ops)/.080,-1,1)
    log_mu+=.55*math.log(clamp(park,.88,1.16))
    return clamp(math.exp(log_mu)+(0.08 if home else 0),2.0,8.2)


def run_features(own_h,opp_p,own_recent,opp_recent,opp_sp,opp_bp,lineup,park,home,lg):
    own_ops=num(own_h.get("ops"),lg["ops"]); lineup_ops=lineup.get("weighted_ops")
    return [(num(own_h.get("runsPerGame"),lg["rpg"])-lg["rpg"])/1.4,(own_ops-lg["ops"])/.09,(num(own_h.get("obp"),lg["obp"])-lg["obp"])/.045,(num(own_h.get("slg"),lg["slg"])-lg["slg"])/.075,(num(opp_p.get("era"),lg["era"])-lg["era"])/1.3,(opp_sp["era"]-lg["era"])/1.6,(opp_sp["whip"]-lg["whip"])/.30,(opp_sp["bb9"]-3.2)/1.8-(opp_sp["k9"]-8.3)/2.8,(opp_bp["era"]-lg["era"])/1.6,(opp_bp["load"]-.5)/.6,(own_recent["run_diff_pg"]-opp_recent["run_diff_pg"])/2.5,((lineup_ops-own_ops)/.08) if lineup_ops is not None else 0,0.0,0.0,(park-1)/.08,0.0,1 if home else 0]


def fit_linear(rows,epochs=180,lr=.012,l2=.006):
    d=len(rows[0][0]);mu=[mean(r[0][j] for r in rows) for j in range(d)];sd=[]
    for j in range(d):
        s=math.sqrt(mean((r[0][j]-mu[j])**2 for r in rows));sd.append(s if s>.08 else 1)
    w=[0.0]*d;b=0.0
    for ep in range(epochs):
        eta=lr*(1-ep/(epochs*1.35))
        for x,y in rows:
            z=[(x[j]-mu[j])/sd[j] for j in range(d)];pred=b+sum(a*c for a,c in zip(w,z));e=pred-y;b-=eta*e
            for j in range(d):w[j]-=eta*(e*z[j]+l2*w[j])
    return {"w":w,"b":b,"mean":mu,"std":sd}


def linpred(m,x):return m["b"]+sum(a*((x[j]-m["mean"][j])/m["std"][j]) for j,a in enumerate(m["w"]))


def bootstrap_gain(base,new,reps=250):
    if not base or len(base)!=len(new):return 0.0
    rng=random.Random(90210);n=len(base);win=0
    for _ in range(reps):
        gain=sum(base[(i:=rng.randrange(n))]-new[i] for _ in range(n))/n
        if gain>0:win+=1
    return win/reps


def residual_state(game_rows):
    if len(game_rows)<RESIDUAL_MIN_GAMES:return {"active":False,"model":None,"rmse_base":None,"rmse_model":None,"gain_prob":0.0}
    cut=max(300,int(len(game_rows)*.78)); tr=game_rows[:cut]; va=game_rows[cut:]
    rows=[]
    for z in tr:rows.extend([(z["fh"],z["hs"]-z["bh"]),(z["fa"],z["as"]-z["ba"])])
    m=fit_linear(rows);bl=[];nl=[]
    for z in va:
        for feat,base,y in ((z["fh"],z["bh"],z["hs"]),(z["fa"],z["ba"],z["as"])):
            pred=base+clamp(linpred(m,feat),-2,2);bl.append((base-y)**2);nl.append((pred-y)**2)
    rb=math.sqrt(mean(bl));rn=math.sqrt(mean(nl));gp=bootstrap_gain(bl,nl)
    if rn+.035<rb and gp>=.90:
        allrows=[]
        for z in game_rows:allrows.extend([(z["fh"],z["hs"]-z["bh"]),(z["fa"],z["as"]-z["ba"])])
        return {"active":True,"model":fit_linear(allrows),"rmse_base":rb,"rmse_model":rn,"gain_prob":gp}
    return {"active":False,"model":None,"rmse_base":rb,"rmse_model":rn,"gain_prob":gp}


def fit_platt(rows,epochs=500,lr=.025):
    a=0;b=1
    for ep in range(epochs):
        eta=lr*(1-ep/(epochs*1.4))
        for p,y in rows:
            x=logit(clamp(p,.01,.99));q=sigmoid(a+b*x);e=q-y;a-=eta*e;b-=eta*(e*x+.002*(b-1))
    return a,b


def platt(m,p):return clamp(sigmoid(m[0]+m[1]*logit(p))) if m else p


def cal_state(rows):
    if len(rows)<CAL_MIN_GAMES:return {"active":False,"model":None,"brier_raw":None,"brier_cal":None,"gain_prob":0.0}
    cut=max(350,int(len(rows)*.80));tr=rows[:cut];va=rows[cut:];m=fit_platt([(z["p"],z["y"]) for z in tr]);bl=[];nl=[]
    for z in va:bl.append((z["p"]-z["y"])**2);nl.append((platt(m,z["p"])-z["y"])**2)
    br=mean(bl);bc=mean(nl);gp=bootstrap_gain(bl,nl)
    if bc+.001<br and gp>=.90:return {"active":True,"model":fit_platt([(z["p"],z["y"]) for z in rows]),"brier_raw":br,"brier_cal":bc,"gain_prob":gp}
    return {"active":False,"model":None,"brier_raw":br,"brier_cal":bc,"gain_prob":gp}


def nb_pmf(mu,alpha=ALPHA,max_runs=30):
    r=1/alpha;p=[(r/(r+mu))**r]
    for k in range(max_runs):p.append(p[-1]*((k+r)/(k+1))*(mu/(r+mu)))
    s=sum(p);return [x/s for x in p]


def ml_prob(hmu,amu,extra=.53):
    h=nb_pmf(hmu);a=nb_pmf(amu);w=t=0.0
    for i,pi in enumerate(h):
        for j,pj in enumerate(a):
            z=pi*pj
            if i>j:w+=z
            elif i==j:t+=z
    return clamp(w+extra*t)


def runline_prob(hmu,amu,name,point,home,away):
    h=nb_pmf(hmu);a=nb_pmf(amu);w=p=l=0.0
    for i,pi in enumerate(h):
        for j,pj in enumerate(a):
            z=pi*pj;v=(i+point-j) if name==home else (j+point-i)
            if v>1e-9:w+=z
            elif v<-1e-9:l+=z
            else:p+=z
    return w/(w+l) if w+l else .5


def brier(rows,key):return mean((z[key]-z["y"])**2 for z in rows) if rows else None
def logloss(rows,key):return mean(-(z["y"]*math.log(clamp(z[key],.001,.999))+(1-z["y"])*math.log(clamp(1-z[key],.001,.999))) for z in rows) if rows else None

def metrics(rows,pkey):
    if not rows:return {}
    correct=sum((z[pkey]>=.5)==bool(z["y"]) for z in rows)
    return {"n":len(rows),"accuracy":correct/len(rows),"brier":brier(rows,pkey),"logloss":logloss(rows,pkey)}


def run_metrics(rows,hkey,akey):
    if not rows:return {}
    errs=[];sq=[];terr=[];tsq=[]
    for z in rows:
        for p,y in ((z[hkey],z["home_score"]),(z[akey],z["away_score"])):errs.append(abs(p-y));sq.append((p-y)**2)
        t=z[hkey]+z[akey];y=z["home_score"]+z["away_score"];terr.append(abs(t-y));tsq.append((t-y)**2)
    return {"team_run_mae":mean(errs),"team_run_rmse":math.sqrt(mean(sq)),"total_mae":mean(terr),"total_rmse":math.sqrt(mean(tsq))}


def probability_bins(rows,key):
    bins=[]
    for lo in (.50,.55,.60,.65,.70,.75,.80):
        hi=lo+.05 if lo<.80 else 1.01;xs=[]
        for z in rows:
            p=z[key];q=max(p,1-p)
            if lo<=q<hi:xs.append((q, int((p>=.5)==bool(z["y"]))))
        if xs:bins.append({"bin":f"{int(lo*100)}-{int(min(100,hi*100))}%","n":len(xs),"avg_confidence":mean(x[0] for x in xs),"hit_rate":mean(x[1] for x in xs)})
    return bins


def person_hand(pid,cache):
    if not pid:return "?"
    if pid in cache:return cache[pid]
    try:
        p=(mlb(f"v1/people/{pid}").get("people") or [{}])[0];h=p.get("pitchHand",{}).get("code","?")
    except Exception:h="?"
    cache[pid]=h;return h


def team_box(box,side):return (box.get("teams") or {}).get(side) or {}

def starter_id(sidebox):
    xs=sidebox.get("pitchers") or []
    return int(xs[0]) if xs else None


def update_states(g,box,team_state,pitcher_state,batter_state):
    gd=datetime.fromisoformat(g["game_date"].replace("Z","+00:00")).date()
    for side,opp_side,tid,rf,ra in (("home","away",g["home_id"],g["home_score"],g["away_score"]),("away","home",g["away_id"],g["away_score"],g["home_score"])):
        sb=team_box(box,side); s=team_state[tid]; tstats=sb.get("teamStats") or {};bat=tstats.get("batting") or tstats.get("hitting") or {};pit=tstats.get("pitching") or {}
        s["games"]+=1;s["rf"]+=rf;s["ra"]+=ra;add_batting(s["bat"],bat);s["pitch_outs"]+=outs_from_stat(pit);s["er"]+=num(pit.get("earnedRuns"));s["h_allowed"]+=num(pit.get("hits"));s["bb_allowed"]+=num(pit.get("baseOnBalls"));s["recent"].append((rf,ra))
        pids=[int(x) for x in (sb.get("pitchers") or [])]; bullpen={"date":gd,"pitches":0.0,"outs":0.0,"er":0.0,"h":0.0,"bb":0.0}
        for i,pid in enumerate(pids):
            ps=((sb.get("players") or {}).get(f"ID{pid}") or {}).get("stats",{}).get("pitching") or {}; st=pitcher_state[pid];st["outs"]+=outs_from_stat(ps);st["er"]+=num(ps.get("earnedRuns"));st["h"]+=num(ps.get("hits"));st["bb"]+=num(ps.get("baseOnBalls"));st["so"]+=num(ps.get("strikeOuts"));st["starts"]+=1 if i==0 else 0
            if i>0:bullpen["pitches"]+=num(ps.get("pitchesThrown"));bullpen["outs"]+=outs_from_stat(ps);bullpen["er"]+=num(ps.get("earnedRuns"));bullpen["h"]+=num(ps.get("hits"));bullpen["bb"]+=num(ps.get("baseOnBalls"))
        if len(pids)>1:s["bullpen"].append(bullpen)
        for pid_s,p in (sb.get("players") or {}).items():
            bst=(p.get("stats") or {}).get("batting") or {}
            if not bst:continue
            pid=int((p.get("person") or {}).get("id") or pid_s.replace("ID",""));add_batting(batter_state[pid],bst)


def main():
    games=schedule();print(f"Regular-season finals {START} -> {END}: {len(games)}",flush=True)
    if not games:raise SystemExit("No final regular-season games found")
    boxes=fetch_boxes(games);missing=[g["game_pk"] for g in games if g["game_pk"] not in boxes]
    if missing:print(f"WARN missing boxscores: {len(missing)}",flush=True)
    team_state=defaultdict(blank_team);pitcher_state=defaultdict(blank_pitcher);batter_state=defaultdict(blank_batting);hand_cache={};rows=[];train_games=[];cal_rows=[];res_state={"active":False,"model":None};cstate={"active":False,"model":None}
    last_retrain=-999
    for idx,g in enumerate(games):
        box=boxes.get(g["game_pk"])
        if not box:continue
        gd=datetime.fromisoformat(g["game_date"].replace("Z","+00:00")).date();lg=league_baseline(team_state);hs=team_state[g["home_id"]];as_=team_state[g["away_id"]];hh=team_hitting(hs,lg);ah=team_hitting(as_,lg);hp=team_pitching(hs,lg);ap=team_pitching(as_,lg);hr=recent_context(hs,lg);ar=recent_context(as_,lg);hbp=bullpen_profile(hs,gd,lg);abp=bullpen_profile(as_,gd,lg);hbox=team_box(box,"home");abox=team_box(box,"away");hspid=starter_id(hbox);aspid=starter_id(abox);hsp=pitcher_profile(pitcher_state[hspid],lg) if hspid else pitcher_profile(blank_pitcher(),lg);asp=pitcher_profile(pitcher_state[aspid],lg) if aspid else pitcher_profile(blank_pitcher(),lg);hhand=person_hand(hspid,hand_cache);ahand=person_hand(aspid,hand_cache);hline=lineup_ops(hbox,batter_state,lg);aline=lineup_ops(abox,batter_state,lg);park=PARK.get(g["home"],1.0)
        bv9h=base_v9(hh,ap,hr,park,True,lg);bv9a=base_v9(ah,hp,ar,park,False,lg);rawh=base_v10_raw(hh,ap,hr,asp,abp,hline,park,True,lg);rawa=base_v10_raw(ah,hp,ar,hsp,hbp,aline,park,False,lg);bh=clamp(bv9h+clamp(rawh-bv9h,-STRUCTURAL_CAP,STRUCTURAL_CAP),2,8.2);ba=clamp(bv9a+clamp(rawa-bv9a,-STRUCTURAL_CAP,STRUCTURAL_CAP),2,8.2);fh=run_features(hh,ap,hr,ar,asp,abp,hline,park,True,lg);fa=run_features(ah,hp,ar,hr,hsp,hbp,aline,park,False,lg)
        if len(train_games)>=RESIDUAL_MIN_GAMES and len(train_games)-last_retrain>=RETRAIN_EVERY:
            res_state=residual_state(train_games);last_retrain=len(train_games);print(f"retrain @{len(train_games)} residual active={res_state['active']} rmse={res_state.get('rmse_model')} base={res_state.get('rmse_base')} gp={res_state.get('gain_prob'):.2f}",flush=True)
        hmu=bh+(clamp(linpred(res_state["model"],fh),-2,2) if res_state.get("active") else 0);amu=ba+(clamp(linpred(res_state["model"],fa),-2,2) if res_state.get("active") else 0);hmu=clamp(hmu,2,8);amu=clamp(amu,2,8)
        extra=clamp(.53+.035*(abp["load"]-hbp["load"])+.025*((abp["era"]-hbp["era"])/2),.43,.63);pv9=ml_prob(bv9h,bv9a,extra);praw=ml_prob(hmu,amu,extra)
        if len(cal_rows)>=CAL_MIN_GAMES and (len(cal_rows)%RETRAIN_EVERY==0):cstate=cal_state(cal_rows);print(f"cal @{len(cal_rows)} active={cstate['active']} brier={cstate.get('brier_cal')} raw={cstate.get('brier_raw')} gp={cstate.get('gain_prob'):.2f}",flush=True)
        pcal=platt(cstate.get("model"),praw) if cstate.get("active") else praw;y=int(g["home_score"]>g["away_score"])
        favorite=g["home"] if pcal>=.5 else g["away"];fav_point=-1.5;dog=g["away"] if favorite==g["home"] else g["home"];dog_point=1.5;pfav=runline_prob(hmu,amu,favorite,fav_point,g["home"],g["away"]);pdog=runline_prob(hmu,amu,dog,dog_point,g["home"],g["away"]);rl_name,rl_point,rl_p=(favorite,fav_point,pfav) if pfav>=pdog else (dog,dog_point,pdog);margin=(g["home_score"]-g["away_score"]) if rl_name==g["home"] else (g["away_score"]-g["home_score"]);rl_result="W" if margin+rl_point>0 else "P" if abs(margin+rl_point)<1e-9 else "L"
        warm=min(hs["games"],as_["games"])
        row={"game_pk":g["game_pk"],"game_date":g["game_date"],"home":g["home"],"away":g["away"],"home_score":g["home_score"],"away_score":g["away_score"],"pregame_games_home":hs["games"],"pregame_games_away":as_["games"],"warmup_min_games":warm,"league":{"rpg":round(lg["rpg"],4),"ops":round(lg["ops"],4),"era":round(lg["era"],4)},"starters":{"home_id":hspid,"away_id":aspid,"home_hand":hhand,"away_hand":ahand,"home_prior_ip":round(hsp["ip"],2),"away_prior_ip":round(asp["ip"],2)},"lineup_known":{"home":hline["known"],"away":aline["known"]},"v9":{"home_mu":round(bv9h,4),"away_mu":round(bv9a,4),"p_home":round(pv9,6)},"v10":{"home_v9_base":round(bv9h,4),"away_v9_base":round(bv9a,4),"home_raw":round(rawh,4),"away_raw":round(rawa,4),"home_struct":round(bh,4),"away_struct":round(ba,4),"home_mu":round(hmu,4),"away_mu":round(amu,4),"p_home_raw":round(praw,6),"p_home":round(pcal,6),"residual_active":bool(res_state.get("active")),"calibration_active":bool(cstate.get("active"))},"rl_proxy":{"name":rl_name,"point":rl_point,"p":round(rl_p,6),"result":rl_result},"y":y}
        rows.append(row);train_games.append({"fh":fh,"fa":fa,"bh":bh,"ba":ba,"hs":g["home_score"],"as":g["away_score"]});cal_rows.append({"p":praw,"y":y});update_states(g,box,team_state,pitcher_state,batter_state)
        if (idx+1)%100==0:print(f"processed {idx+1}/{len(games)}",flush=True)
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text("\n".join(json.dumps(z,separators=(",",":")) for z in rows)+"\n",encoding="utf-8")
    simple=[]
    for z in rows:simple.append({**z,"p_v9":z["v9"]["p_home"],"p_v10":z["v10"]["p_home"],"h_v9":z["v9"]["home_mu"],"a_v9":z["v9"]["away_mu"],"h_v10":z["v10"]["home_mu"],"a_v10":z["v10"]["away_mu"]})
    warm=[z for z in simple if z["warmup_min_games"]>=5]
    rl=[z for z in rows if z["rl_proxy"]["result"] in ("W","L")]
    rep={"schema":"mlb-backtest-2026-v1","generated_at":datetime.now(timezone.utc).isoformat(),"range":{"start":START,"end":END},"methodology":{"walk_forward":True,"future_game_stats_used":False,"historical_odds_used":False,"statcast_used":False,"weather_used":False,"actual_final_lineup_used_with_prior_player_stats":True,"structural_cap_runs":STRUCTURAL_CAP,"residual_min_games":RESIDUAL_MIN_GAMES,"calibration_min_games":CAL_MIN_GAMES,"notes":["Every prediction is made before current-game boxscore stats are added to state.","Actual starting pitcher and final lineup identities are treated as FINAL-phase pregame information; only their prior stats are used.","No historical sportsbook line/price is fabricated; ROI/EV/CLV are intentionally omitted.","Statcast, historical forecast weather and historical market-reference confidence are neutralized because leakage-safe point-in-time archives are not available here."]},"games":len(simple),"warm_games":len(warm),"v9_ml":metrics(simple,"p_v9"),"v10_ml":metrics(simple,"p_v10"),"v9_runs":run_metrics(simple,"h_v9","a_v9"),"v10_runs":run_metrics(simple,"h_v10","a_v10"),"warm_v9_ml":metrics(warm,"p_v9"),"warm_v10_ml":metrics(warm,"p_v10"),"warm_v9_runs":run_metrics(warm,"h_v9","a_v9"),"warm_v10_runs":run_metrics(warm,"h_v10","a_v10"),"v10_probability_bins":probability_bins(warm,"p_v10"),"runline_proxy":{"n":len(rl),"wins":sum(z["rl_proxy"]["result"]=="W" for z in rl),"hit_rate":sum(z["rl_proxy"]["result"]=="W" for z in rl)/len(rl) if rl else None,"definition":"Model-favorite standard ±1.5 pair; choose higher model cover probability. No odds/value filter."},"activation":{"residual_active_final":bool(res_state.get("active")),"residual_validation":{k:res_state.get(k) for k in ("rmse_base","rmse_model","gain_prob")},"calibration_active_final":bool(cstate.get("active")),"calibration_validation":{k:cstate.get(k) for k in ("brier_raw","brier_cal","gain_prob")}}}
    REPORT_JSON.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding="utf-8")
    def f(x,n=4):return "N/A" if x is None else f"{x:.{n}f}"
    md=["# MLB 2026 walk-forward backtest — V9 vs V10.0.5","",f"Range: **{START} → {END}**  ",f"Games replayed: **{rep['games']}** (warm sample ≥5 prior games/team: **{rep['warm_games']}**)  ","","## Leakage control","","- Prediction generated before adding the current game's stats.","- Expanding team/player/starter/bullpen statistics only.","- Actual starter/lineup identity used as FINAL-phase information, but only prior stats contribute.","- No historical bookmaker odds invented: **no ROI/EV/CLV claims**.","- Historical Statcast/weather/market confidence neutralized in this replay.","","## Moneyline — all games","",f"- V9 accuracy: **{rep['v9_ml'].get('accuracy',0)*100:.2f}%** | Brier {f(rep['v9_ml'].get('brier'))} | LogLoss {f(rep['v9_ml'].get('logloss'))}",f"- V10.0.5 accuracy: **{rep['v10_ml'].get('accuracy',0)*100:.2f}%** | Brier {f(rep['v10_ml'].get('brier'))} | LogLoss {f(rep['v10_ml'].get('logloss'))}","","## Moneyline — warm sample","",f"- V9 accuracy: **{rep['warm_v9_ml'].get('accuracy',0)*100:.2f}%** | Brier {f(rep['warm_v9_ml'].get('brier'))} | LogLoss {f(rep['warm_v9_ml'].get('logloss'))}",f"- V10.0.5 accuracy: **{rep['warm_v10_ml'].get('accuracy',0)*100:.2f}%** | Brier {f(rep['warm_v10_ml'].get('brier'))} | LogLoss {f(rep['warm_v10_ml'].get('logloss'))}","","## Run projection — warm sample","",f"- V9 team-run MAE **{f(rep['warm_v9_runs'].get('team_run_mae'),3)}** | RMSE **{f(rep['warm_v9_runs'].get('team_run_rmse'),3)}** | total MAE **{f(rep['warm_v9_runs'].get('total_mae'),3)}**",f"- V10.0.5 team-run MAE **{f(rep['warm_v10_runs'].get('team_run_mae'),3)}** | RMSE **{f(rep['warm_v10_runs'].get('team_run_rmse'),3)}** | total MAE **{f(rep['warm_v10_runs'].get('total_mae'),3)}**","",f"## Run Line proxy ±1.5\n\n- N **{rep['runline_proxy']['n']}** | hit rate **{(rep['runline_proxy']['hit_rate'] or 0)*100:.2f}%**\n- This is predictive only; no historical price/value filter.","","## Walk-forward activation","",f"- Residual run model active at end: **{rep['activation']['residual_active_final']}**",f"- ML calibration active at end: **{rep['activation']['calibration_active_final']}**","","## V10 probability bins (warm sample)",""]
    for b in rep["v10_probability_bins"]:md.append(f"- {b['bin']}: n={b['n']} | avg model {b['avg_confidence']*100:.1f}% | hit {b['hit_rate']*100:.1f}%")
    md += ["","## Important limitation","","This backtest tests the **baseball prediction engine**, not historical profitability. A true betting ROI backtest needs point-in-time bookmaker lines/prices from a licensed historical odds archive. Those prices are deliberately not reconstructed from future/current data."]
    REPORT_MD.write_text("\n".join(md)+"\n",encoding="utf-8")
    print(json.dumps(rep,indent=2),flush=True)
    print(f"Wrote {OUT}, {REPORT_JSON}, {REPORT_MD}",flush=True)


if __name__=="__main__": main()
