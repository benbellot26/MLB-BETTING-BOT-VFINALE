#!/usr/bin/env python3
import os, json, math, time, logging, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta, date as Date
from statistics import median, mean, pstdev
from pathlib import Path
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

VERSION="7.0"
PARIS=ZoneInfo("Europe/Paris")
NOW=datetime.now(timezone.utc)
TARGET_DATE=os.getenv("MLB_DATE",datetime.now(PARIS).date().isoformat())
SEASON=int(os.getenv("MLB_SEASON",TARGET_DATE[:4]))
ODDS_KEY=os.getenv("ODDS_API_KEY","").strip()
DISCORD_URL=os.getenv("DISCORD_WEBHOOK_URL","").strip()
HISTORY_FILE=Path(os.getenv("HISTORY_FILE","data/mlb_history.jsonl"))
BANKROLL=float(os.getenv("BANKROLL","10") or 10)
UNIT=float(os.getenv("UNIT","0.5") or .5)
MAX_STAKE_UNITS=float(os.getenv("MAX_STAKE_UNITS","3") or 3)
MIN_EV=float(os.getenv("MIN_EV","0.03") or .03)
MIN_EDGE=float(os.getenv("MIN_EDGE","0.025") or .025)
MIN_QUALITY=float(os.getenv("MIN_QUALITY","0.62") or .62)
MAX_MODEL_MARKET_GAP=float(os.getenv("MAX_MODEL_MARKET_GAP","0.16") or .16)
ML_MIN_GAMES=int(os.getenv("ML_MIN_GAMES","150") or 150)
BOOKMAKERS=os.getenv("ODDS_BOOKMAKERS","winamax_fr,pinnacle,betfair_ex_eu,betclic_fr,unibet_fr,pmu_fr,netbet_fr")
REF_BOOKS={x for x in BOOKMAKERS.split(",") if x and x!="winamax_fr"}
TIMEOUT=25
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper(),format="%(asctime)s | %(levelname)s | %(message)s")

PARK={
"Arizona Diamondbacks":1.04,"Athletics":1.05,"Oakland Athletics":1.05,"Atlanta Braves":1.01,"Baltimore Orioles":1.01,
"Boston Red Sox":1.03,"Chicago White Sox":1.00,"Chicago Cubs":1.02,"Cincinnati Reds":1.05,"Cleveland Guardians":0.98,
"Colorado Rockies":1.14,"Detroit Tigers":0.98,"Houston Astros":1.00,"Kansas City Royals":0.99,"Los Angeles Angels":1.01,
"Los Angeles Dodgers":0.98,"Miami Marlins":0.96,"Milwaukee Brewers":1.00,"Minnesota Twins":0.99,"New York Mets":0.98,
"New York Yankees":1.03,"Philadelphia Phillies":1.02,"Pittsburgh Pirates":0.97,"San Diego Padres":0.97,
"San Francisco Giants":0.94,"Seattle Mariners":0.96,"St. Louis Cardinals":1.00,"Tampa Bay Rays":0.98,
"Texas Rangers":1.02,"Toronto Blue Jays":1.01,"Washington Nationals":1.00
}
COORD={
"Arizona Diamondbacks":(33.4453,-112.0667),"Athletics":(38.5806,-121.5130),"Oakland Athletics":(38.5806,-121.5130),
"Atlanta Braves":(33.8907,-84.4677),"Baltimore Orioles":(39.2839,-76.6217),"Boston Red Sox":(42.3467,-71.0972),
"Chicago White Sox":(41.8301,-87.6338),"Chicago Cubs":(41.9484,-87.6553),"Cincinnati Reds":(39.0975,-84.5069),
"Cleveland Guardians":(41.4962,-81.6852),"Colorado Rockies":(39.7559,-104.9942),"Detroit Tigers":(42.3390,-83.0485),
"Houston Astros":(29.7573,-95.3555),"Kansas City Royals":(39.0517,-94.4803),"Los Angeles Angels":(33.8003,-117.8827),
"Los Angeles Dodgers":(34.0739,-118.2400),"Miami Marlins":(25.7781,-80.2197),"Milwaukee Brewers":(43.0280,-87.9712),
"Minnesota Twins":(44.9817,-93.2776),"New York Mets":(40.7571,-73.8458),"New York Yankees":(40.8296,-73.9262),
"Philadelphia Phillies":(39.9061,-75.1665),"Pittsburgh Pirates":(40.4469,-80.0057),"San Diego Padres":(32.7076,-117.1570),
"San Francisco Giants":(37.7786,-122.3893),"Seattle Mariners":(47.5914,-122.3325),"St. Louis Cardinals":(38.6226,-90.1928),
"Tampa Bay Rays":(27.7683,-82.6534),"Texas Rangers":(32.7473,-97.0832),"Toronto Blue Jays":(43.6414,-79.3894),
"Washington Nationals":(38.8730,-77.0074)
}
ROOF={"Arizona Diamondbacks","Houston Astros","Miami Marlins","Milwaukee Brewers","Seattle Mariners","Texas Rangers","Toronto Blue Jays"}
DOME={"Tampa Bay Rays"}
ALIASES={"oaklandathletics":"athletics","athletics":"athletics"}
_CACHE={}

def norm_name(s):
    x="".join(c.lower() for c in str(s) if c.isalnum())
    return ALIASES.get(x,x)

def clamp(x,a=0.001,b=0.999): return max(a,min(b,x))
def num(x,d=0.0):
    try:
        y=float(x)
        return y if math.isfinite(y) else d
    except: return d

def pct(x): return "N/A" if x is None else f"{100*x:.1f}%"
def odds_fmt(x): return "N/A" if not x else f"{x:.2f}"
def local_time(iso):
    try:return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(PARIS).strftime("%d/%m/%Y %H:%M")
    except:return iso

def http_json(url,params=None,method="GET",payload=None,timeout=TIMEOUT,return_headers=False):
    if params:
        qs=urllib.parse.urlencode(params,safe=",")
        url += ("&" if "?" in url else "?")+qs
    data=None
    headers={"User-Agent":"MLB-Betting-Bot-V7/1.0","Accept":"application/json"}
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        body=r.read().decode("utf-8","replace")
        obj=json.loads(body) if body else None
        hdr={k.lower():v for k,v in r.headers.items()}
        return (obj,hdr) if return_headers else obj

def mlb(path,params=None): return http_json("https://statsapi.mlb.com/api/"+path.lstrip("/"),params)

def mlb_schedule(day,team_id=None,hydrate="probablePitcher"):
    p={"sportId":1,"date":day,"hydrate":hydrate}
    if team_id:p["teamId"]=team_id
    d=mlb("v1/schedule",p)
    return [g for block in d.get("dates",[]) for g in block.get("games",[])]

def season_stats(team_id,group):
    key=("teamstats",team_id,group,SEASON)
    if key in _CACHE:return _CACHE[key]
    try:
        d=mlb(f"v1/teams/{team_id}/stats",{"stats":"season","group":group,"season":SEASON})
        s=(d.get("stats") or [{}])[0].get("splits") or []
        out=s[0].get("stat",{}) if s else {}
    except Exception as e:
        logging.warning("Stats %s/%s: %s",team_id,group,e);out={}
    _CACHE[key]=out;return out

def pitcher_stats(pid):
    if not pid:return {}
    key=("pitcher",pid,SEASON)
    if key in _CACHE:return _CACHE[key]
    try:
        d=mlb(f"v1/people/{pid}/stats",{"stats":"season","group":"pitching","season":SEASON})
        s=(d.get("stats") or [{}])[0].get("splits") or []
        out=s[0].get("stat",{}) if s else {}
    except Exception as e:
        logging.warning("Pitcher %s: %s",pid,e);out={}
    _CACHE[key]=out;return out

def recent_games(team_id,days=14):
    key=("recent",team_id,days)
    if key in _CACHE:return _CACHE[key]
    end=datetime.now(PARIS).date()-timedelta(days=1);start=end-timedelta(days=days-1)
    try:
        d=mlb("v1/schedule",{"sportId":1,"teamId":team_id,"startDate":start.isoformat(),"endDate":end.isoformat()})
        gs=[g for block in d.get("dates",[]) for g in block.get("games",[]) if g.get("status",{}).get("abstractGameState")=="Final"]
    except Exception:gs=[]
    _CACHE[key]=gs;return gs

def recent_context(team_id):
    gs=recent_games(team_id,14)[-10:]
    wins=rf=ra=0
    for g in gs:
        home=g.get("teams",{}).get("home",{});away=g.get("teams",{}).get("away",{})
        is_home=home.get("team",{}).get("id")==team_id
        own=home if is_home else away;opp=away if is_home else home
        a=num(own.get("score"));b=num(opp.get("score"));rf+=a;ra+=b;wins+=int(a>b)
    n=len(gs)
    return {"games":n,"win_pct":wins/n if n else .5,"run_diff_pg":(rf-ra)/n if n else 0.0,"runs_pg":rf/n if n else 4.4}

def boxscore(game_pk):
    key=("box",game_pk)
    if key in _CACHE:return _CACHE[key]
    try:out=mlb(f"v1/game/{game_pk}/boxscore")
    except:out={}
    _CACHE[key]=out;return out

def bullpen_load(team_id):
    gs=recent_games(team_id,5)
    if not gs:return .5,0
    today=datetime.now(PARIS).date();weighted=0.0;seen=0
    for g in gs[-3:]:
        try:
            gd=datetime.fromisoformat(g["gameDate"].replace("Z","+00:00")).astimezone(PARIS).date()
            age=max(1,(today-gd).days)
            if age>3:continue
            b=boxscore(g["gamePk"]);side="home" if g["teams"]["home"]["team"]["id"]==team_id else "away"
            team=b.get("teams",{}).get(side,{})
            pitches=0
            for p in team.get("players",{}).values():
                st=p.get("stats",{}).get("pitching",{})
                if not st:continue
                if num(st.get("gamesStarted"),0)>=1:continue
                pitches+=num(st.get("pitchesThrown"),0)
            weight={1:1.0,2:.6,3:.3}.get(age,.2)
            weighted += pitches*weight;seen+=1
        except:pass
    if not seen:return .5,0
    return clamp(weighted/180,0,1.5),seen

def weather(team,iso):
    if team not in COORD:return {"text":"N/A","run_adj":0.0,"quality":0.0}
    try:
        lat,lon=COORD[team]
        d=http_json("https://api.open-meteo.com/v1/forecast",{
            "latitude":lat,"longitude":lon,"hourly":"temperature_2m,wind_speed_10m,relative_humidity_2m,precipitation_probability",
            "forecast_days":4,"timezone":"UTC"})
        target=datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0,tzinfo=None)
        ts=[datetime.fromisoformat(x) for x in d["hourly"]["time"]]
        i=min(range(len(ts)),key=lambda j:abs(ts[j]-target))
        t=num(d["hourly"]["temperature_2m"][i]);w=num(d["hourly"]["wind_speed_10m"][i]);h=num(d["hourly"]["relative_humidity_2m"][i]);pr=num(d["hourly"]["precipitation_probability"][i])
        raw=(t-20)*.012 + max(0,w-15)*.006
        if team in DOME:factor=0.0;note="dôme"
        elif team in ROOF:factor=.20;note="toit rétractable: impact météo réduit"
        else:factor=1.0;note="extérieur"
        return {"text":f"{t:.0f}°C • vent {w:.0f} km/h • HR {h:.0f}% • pluie {pr:.0f}% • {note}","run_adj":raw*factor,"quality":1.0}
    except Exception:return {"text":"N/A","run_adj":0.0,"quality":0.0}

def team_bundle(team_id):
    return season_stats(team_id,"hitting"),season_stats(team_id,"pitching"),recent_context(team_id),bullpen_load(team_id)

def pitcher_line(p):
    if not p:return "données indisponibles"
    return f"ERA {num(p.get('era'),4.50):.2f} • WHIP {num(p.get('whip'),1.35):.2f} • K/9 {num(p.get('strikeOutsPer9'),8.2):.1f} • BB/9 {num(p.get('walksPer9'),3.2):.1f}"

def feature_and_projection(g):
    home=g["teams"]["home"]["team"];away=g["teams"]["away"]["team"]
    hh,hp,hr,(hb,hbn)=team_bundle(home["id"]);ah,ap,ar,(ab,abn)=team_bundle(away["id"])
    hsp=g["teams"]["home"].get("probablePitcher") or {};asp=g["teams"]["away"].get("probablePitcher") or {}
    hs=pitcher_stats(hsp.get("id"));aps=pitcher_stats(asp.get("id"));wx=weather(home["name"],g["gameDate"])
    def rate(d,k,default):return num(d.get(k),default)
    def per_game(d,k,gk="gamesPlayed",default=0):
        gp=max(1,num(d.get(gk),0));return num(d.get(k),default)/gp if gp else default
    h_rpg=rate(hh,"runsPerGame",per_game(hh,"runs",default=4.4));a_rpg=rate(ah,"runsPerGame",per_game(ah,"runs",default=4.4))
    h_era=rate(hp,"era",4.40);a_era=rate(ap,"era",4.40)
    h_ops=rate(hh,"ops",.710);a_ops=rate(ah,"ops",.710)
    h_obp=rate(hh,"obp",rate(hh,"onBasePercentage",.320));a_obp=rate(ah,"obp",rate(ah,"onBasePercentage",.320))
    h_slg=rate(hh,"slg",rate(hh,"sluggingPercentage",.390));a_slg=rate(ah,"slg",rate(ah,"sluggingPercentage",.390))
    hs_era=rate(hs,"era",4.35);as_era=rate(aps,"era",4.35);hs_whip=rate(hs,"whip",1.32);as_whip=rate(aps,"whip",1.32)
    hs_k=rate(hs,"strikeOutsPer9",8.3);as_k=rate(aps,"strikeOutsPer9",8.3);hs_bb=rate(hs,"walksPer9",3.2);as_bb=rate(aps,"walksPer9",3.2)
    park=PARK.get(home["name"],1.0)
    league=4.45
    home_mu=(.52*h_rpg+.18*(a_era/9*9)+.30*league)
    away_mu=(.52*a_rpg+.18*(h_era/9*9)+.30*league)
    home_mu += .22 + (h_ops-.710)*2.0 + (h_obp-.320)*1.2 + (h_slg-.390)*.9
    away_mu += (a_ops-.710)*2.0 + (a_obp-.320)*1.2 + (a_slg-.390)*.9
    home_mu += (as_era-4.35)*.16 + (as_whip-1.32)*.45 - (as_k-8.3)*.035 + (as_bb-3.2)*.045
    away_mu += (hs_era-4.35)*.16 + (hs_whip-1.32)*.45 - (hs_k-8.3)*.035 + (hs_bb-3.2)*.045
    home_mu += ar["run_diff_pg"]*(-.035) + hr["run_diff_pg"]*.055 + (ab-.5)*.18 - (hb-.5)*.05
    away_mu += hr["run_diff_pg"]*(-.035) + ar["run_diff_pg"]*.055 + (hb-.5)*.18 - (ab-.5)*.05
    scale=park*(1+wx["run_adj"]*.035)
    home_mu=clamp(home_mu*scale,2.1,7.8);away_mu=clamp(away_mu*scale,2.1,7.8)
    features=[
        (h_rpg-a_rpg)/1.5,(h_ops-a_ops)/.10,(h_obp-a_obp)/.05,(h_slg-a_slg)/.08,(a_era-h_era)/1.5,
        (as_era-hs_era)/2.0,(as_whip-hs_whip)/.35,(hs_k-as_k)/3.0,(as_bb-hs_bb)/2.0,
        (hr["run_diff_pg"]-ar["run_diff_pg"])/2.5,(ab-hb),park-1.0,wx["run_adj"]/0.25
    ]
    completeness=[bool(hh),bool(ah),bool(hp),bool(ap),bool(hs),bool(aps),wx["quality"]>0,hbn>0,abn>0]
    quality=sum(completeness)/len(completeness)
    return {
        "home":home["name"],"away":away["name"],"home_id":home["id"],"away_id":away["id"],
        "home_sp":hsp.get("fullName","Non annoncé"),"away_sp":asp.get("fullName","Non annoncé"),
        "home_sp_stats":hs,"away_sp_stats":aps,"home_mu":home_mu,"away_mu":away_mu,"total_mu":home_mu+away_mu,
        "features":features,"quality":quality,"park":park,"weather":wx,"home_recent":hr,"away_recent":ar,
        "home_bullpen":hb,"away_bullpen":ab,"home_bullpen_n":hbn,"away_bullpen_n":abn
    }

def poisson(mu,max_runs=25):
    p=[math.exp(-mu)]
    for k in range(1,max_runs+1):p.append(p[-1]*mu/k)
    s=sum(p)
    return [x/s for x in p]

def ml_probs(hmu,amu):
    h=poisson(hmu);a=poisson(amu);win=tie=0.0
    for i,pi in enumerate(h):
        for j,pj in enumerate(a):
            z=pi*pj
            if i>j:win+=z
            elif i==j:tie+=z
    return clamp(win+.5*tie)

def line_probs(hmu,amu,kind,name,point,home,away):
    h=poisson(hmu);a=poisson(amu);w=p=l=0.0
    for i,pi in enumerate(h):
        for j,pj in enumerate(a):
            z=pi*pj
            if kind=="RUNLINE":v=(i+point-j) if norm_name(name)==norm_name(home) else (j+point-i)
            else:v=(i+j-point) if name.lower()=="over" else (point-i-j)
            if v>1e-9:w+=z
            elif v<-1e-9:l+=z
            else:p+=z
    s=w+p+l
    return w/s,p/s,l/s

def odds_api():
    data,h=http_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",{
        "apiKey":ODDS_KEY,"bookmakers":BOOKMAKERS,"markets":"h2h,spreads,totals","oddsFormat":"decimal","dateFormat":"iso"
    },return_headers=True)
    logging.info("The Odds API | coût=%s | restant=%s | utilisé=%s",h.get("x-requests-last","?"),h.get("x-requests-remaining","?"),h.get("x-requests-used","?"))
    return data or []

def market_rows(event,market):
    rows=[]
    for b in event.get("bookmakers",[]):
        for m in b.get("markets",[]):
            if m.get("key")==market:rows.append((b,m))
    return rows

def winamax_outcomes(event,market):
    for b,m in market_rows(event,market):
        if b.get("key")=="winamax_fr":return b,m
    return None,None

def fair_book_probability(outcomes,target_name,target_point=None,market="h2h"):
    if market=="h2h":
        if len(outcomes)<2:return None
        probs={norm_name(o.get("name")):1/num(o.get("price"),999) for o in outcomes if num(o.get("price"))>1}
        s=sum(probs.values());key=norm_name(target_name)
        return probs.get(key)/s if key in probs and s else None
    if market=="totals":
        xs=[o for o in outcomes if abs(num(o.get("point"))-num(target_point))<1e-6]
        if len(xs)<2:return None
        probs={o.get("name"):1/num(o.get("price"),999) for o in xs if num(o.get("price"))>1};s=sum(probs.values())
        return probs.get(target_name)/s if target_name in probs and s else None
    target=next((o for o in outcomes if norm_name(o.get("name"))==norm_name(target_name) and abs(num(o.get("point"))-num(target_point))<1e-6),None)
    other=next((o for o in outcomes if norm_name(o.get("name"))!=norm_name(target_name) and abs(num(o.get("point"))+num(target_point))<1e-6),None)
    if not target or not other:return None
    a=1/num(target.get("price"),999);b=1/num(other.get("price"),999)
    return a/(a+b) if a+b else None

def consensus(event,market,name,point=None):
    vals=[];books=[]
    for b,m in market_rows(event,market):
        if b.get("key") not in REF_BOOKS:continue
        p=fair_book_probability(m.get("outcomes",[]),name,point,market)
        if p is not None:vals.append(p);books.append(b.get("key"))
    if not vals:return {"p":None,"n":0,"disp":None,"books":[]}
    return {"p":median(vals),"n":len(vals),"disp":pstdev(vals) if len(vals)>1 else 0.0,"books":books}

def load_history():
    if not HISTORY_FILE.exists():return {}
    out={}
    try:
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():continue
            r=json.loads(line);out[str(r["game_pk"])]=r
    except Exception as e:logging.warning("Historique illisible: %s",e)
    return out

def write_history(hist):
    HISTORY_FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=HISTORY_FILE.with_suffix(HISTORY_FILE.suffix+".tmp")
    rows=sorted(hist.values(),key=lambda r:(r.get("game_date",""),int(r.get("game_pk",0))))
    tmp.write_text("\n".join(json.dumps(r,ensure_ascii=False,separators=(",",":")) for r in rows)+("\n" if rows else ""),encoding="utf-8")
    tmp.replace(HISTORY_FILE)

def settle_history(hist):
    pending=[r for r in hist.values() if r.get("status","PENDING")=="PENDING"]
    dates=sorted({r.get("game_date","")[:10] for r in pending if r.get("game_date")})
    settled=0
    for day in dates:
        try:games={str(g["gamePk"]):g for g in mlb_schedule(day,hydrate="")}
        except:continue
        for r in [x for x in pending if x.get("game_date","")[:10]==day]:
            g=games.get(str(r["game_pk"]));
            if not g or g.get("status",{}).get("abstractGameState")!="Final":continue
            hs=num(g.get("teams",{}).get("home",{}).get("score"));as_=num(g.get("teams",{}).get("away",{}).get("score"))
            r.update({"status":"FINAL","home_score":int(hs),"away_score":int(as_),"home_win":1 if hs>as_ else 0,"settled_at":NOW.isoformat()})
            for p in r.get("picks",[]):
                if p["market"]=="ML":v=(hs-as_) if norm_name(p["name"])==norm_name(r["home"]) else (as_-hs)
                elif p["market"]=="RUNLINE":v=(hs+num(p["point"])-as_) if norm_name(p["name"])==norm_name(r["home"]) else (as_+num(p["point"])-hs)
                else:v=(hs+as_-num(p["point"])) if p["name"].lower()=="over" else (num(p["point"])-hs-as_)
                res="W" if v>1e-9 else "L" if v<-1e-9 else "P"
                p["result"]=res
                stake=num(p.get("stake_eur"));price=num(p.get("price"))
                p["profit_eur"]=round(stake*(price-1),4) if res=="W" else -round(stake,4) if res=="L" else 0.0
            settled+=1
    if settled:write_history(hist)
    return settled

def sigmoid(z):return 1/(1+math.exp(-max(-30,min(30,z))))
def brier(ps,ys):return mean((p-y)**2 for p,y in zip(ps,ys)) if ps else 1.0

def fit_logistic(rows):
    n=len(rows);d=len(rows[0][0]);means=[mean(r[0][j] for r in rows) for j in range(d)];std=[]
    for j in range(d):
        s=math.sqrt(mean((r[0][j]-means[j])**2 for r in rows));std.append(s if s>.05 else 1.0)
    w=[0.0]*d;b=0.0;lr=.018
    for epoch in range(260):
        decay=lr*(1-epoch/400)
        for x,y,_ in rows:
            z=[(x[j]-means[j])/std[j] for j in range(d)];p=sigmoid(b+sum(wi*zi for wi,zi in zip(w,z)));e=p-y
            b-=decay*e
            for j in range(d):w[j]-=decay*(e*z[j]+.001*w[j])
    return {"w":w,"b":b,"mean":means,"std":std}

def logistic_predict(model,x):
    z=[(x[j]-model["mean"][j])/model["std"][j] for j in range(len(x))]
    return clamp(sigmoid(model["b"]+sum(wi*zi for wi,zi in zip(model["w"],z))) )

def ml_state(hist):
    data=[]
    for r in hist.values():
        if r.get("status")!="FINAL" or "home_win" not in r:continue
        x=r.get("ml_features");base=r.get("p_pre_ml")
        if isinstance(x,list) and base is not None:data.append((x,int(r["home_win"]),num(base,.5),r.get("game_date","")))
    data.sort(key=lambda z:z[3]);n=len(data)
    state={"n":n,"active":False,"model":None,"brier_ml":None,"brier_base":None}
    if n<ML_MIN_GAMES:return state
    cut=max(100,int(n*.80));train=[(x,y,b) for x,y,b,_ in data[:cut]];val=[(x,y,b) for x,y,b,_ in data[cut:]]
    if len(val)<20:return state
    m=fit_logistic(train);pm=[logistic_predict(m,x) for x,_,_ in val];yb=[y for _,y,_ in val];pb=[b for _,_,b in val]
    bm=brier(pm,yb);bb=brier(pb,yb);state.update({"brier_ml":bm,"brier_base":bb})
    if bm+0.002<bb:
        state["active"]=True;state["model"]=fit_logistic([(x,y,b) for x,y,b,_ in data])
    return state

def blend_probability(model_p,market,quality,mlp=None):
    if market["p"] is None:return clamp(model_p),False
    w_model=.22+.18*quality
    if market["n"]>=4:w_model-=.04
    if market["disp"] is not None and market["disp"]>.035:w_model+=.05
    w_model=clamp(w_model,.18,.42)
    base=clamp(w_model*model_p+(1-w_model)*market["p"])
    if mlp is not None:base=.85*base+.15*mlp
    cap=.10 if quality>=.75 else .07
    base=clamp(base,market["p"]-cap,market["p"]+cap)
    anomaly=abs(model_p-market["p"])>MAX_MODEL_MARKET_GAP
    return base,anomaly

def stake_for(pw,pp,pl,price):
    nonpush=pw+pl
    if nonpush<=0 or price<=1:return 0.0,0.0
    p=pw/nonpush;b=price-1;k=max(0,(p*price-1)/b)
    eur=min(BANKROLL*k*.25,UNIT*MAX_STAKE_UNITS)
    units=eur/UNIT if UNIT>0 else 0
    units=math.floor(units*4+1e-9)/4
    if units<.25:return 0.0,0.0
    return units,round(units*UNIT,2)

def evaluate(event,ctx,kind,name,price,point,model_tuple,cons,anomaly=False):
    pw,pp,pl=model_tuple
    cond_model=pw/(pw+pl) if pw+pl else .5
    if cons["p"] is not None and kind!="ML":
        cond_final=(.38*cond_model+.62*cons["p"]) if cons["n"]>=2 else (.48*cond_model+.52*cons["p"])
        cond_final=clamp(cond_final,cons["p"]-.09,cons["p"]+.09)
        pw=(1-pp)*cond_final;pl=(1-pp)*(1-cond_final)
    be=1/price;cond=pw/(pw+pl) if pw+pl else 0
    edge=cond-be;ev=pw*price+pp-1;fair=(1-pp)/pw if pw>0 else 99
    market_quality=min(1,cons["n"]/4)*(1-min(.5,(cons["disp"] or 0)*8)) if cons["p"] is not None else 0
    q=.72*ctx["quality"]+.28*market_quality
    reasons=[]
    if cons["n"]<2:reasons.append(f"consensus insuffisant ({cons['n']} book)")
    if q<MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10 < {MIN_QUALITY*10:.1f}")
    if anomaly and kind in ("ML","RUNLINE"):reasons.append("divergence modèle/marché anormale")
    if edge<MIN_EDGE:reasons.append(f"edge {edge*100:+.1f} pts < {MIN_EDGE*100:.1f}")
    if ev<MIN_EV:reasons.append(f"EV {ev*100:+.1f}% < {MIN_EV*100:.1f}%")
    units,stake=stake_for(pw,pp,pl,price)
    if units<=0 and not reasons:reasons.append("Kelly prudent < 0.25u")
    ok=not reasons
    return {"market":kind,"name":name,"point":point,"price":price,"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":cond,
            "fair":fair,"edge":edge,"ev":ev,"quality":q,"refs":cons["n"],"disp":cons["disp"],"units":units,"stake_eur":stake,
            "selected":ok,"reason":"OK" if ok else " ; ".join(reasons)}

def representative(evals,market):
    xs=[x for x in evals if x["market"]==market]
    if not xs:return None
    return max(xs,key=lambda z:(z["selected"],z["ev"]))

def analyze(g,event,mls,hist):
    ctx=feature_and_projection(g);home=ctx["home"];away=ctx["away"]
    raw_ml=ml_probs(ctx["home_mu"],ctx["away_mu"]);con_ml=consensus(event,"h2h",home)
    ml_features=ctx["features"]+[raw_ml,con_ml["p"] if con_ml["p"] is not None else .5]
    mlp=logistic_predict(mls["model"],ml_features) if mls["active"] and mls["model"] else None
    p_home,anomaly=blend_probability(raw_ml,con_ml,ctx["quality"],mlp)
    evals=[]
    wb,wm=winamax_outcomes(event,"h2h")
    if wm:
        for o in wm.get("outcomes",[]):
            name=o.get("name");price=num(o.get("price"))
            if price<=1:continue
            p=p_home if norm_name(name)==norm_name(home) else 1-p_home
            c=consensus(event,"h2h",name)
            ev=evaluate(event,ctx,"ML",name,price,None,(p,0,1-p),c,anomaly)
            evals.append(ev)
    wb,wm=winamax_outcomes(event,"spreads")
    if wm:
        for o in wm.get("outcomes",[]):
            name=o.get("name");point=num(o.get("point"));price=num(o.get("price"))
            if price<=1:continue
            model=line_probs(ctx["home_mu"],ctx["away_mu"],"RUNLINE",name,point,home,away)
            c=consensus(event,"spreads",name,point);ev=evaluate(event,ctx,"RUNLINE",name,price,point,model,c,anomaly);evals.append(ev)
    wb,wm=winamax_outcomes(event,"totals")
    if wm:
        for o in wm.get("outcomes",[]):
            name=o.get("name");point=num(o.get("point"));price=num(o.get("price"))
            if price<=1:continue
            model=line_probs(ctx["home_mu"],ctx["away_mu"],"TOTAL",name,point,home,away)
            c=consensus(event,"totals",name,point);ev=evaluate(event,ctx,"TOTAL",name,price,point,model,c,False);evals.append(ev)
    picks=sorted([x for x in evals if x["selected"]],key=lambda z:z["ev"],reverse=True)
    record={
        "game_pk":g["gamePk"],"game_date":g["gameDate"],"home":home,"away":away,"status":"PENDING",
        "analyzed_at":NOW.isoformat(),"first_analyzed_at":hist.get(str(g["gamePk"]),{}).get("first_analyzed_at",NOW.isoformat()),
        "analysis_count":hist.get(str(g["gamePk"]),{}).get("analysis_count",0)+1,
        "home_mu":round(ctx["home_mu"],4),"away_mu":round(ctx["away_mu"],4),"raw_model_home":round(raw_ml,6),
        "market_home":round(con_ml["p"],6) if con_ml["p"] is not None else None,"p_pre_ml":round(blend_probability(raw_ml,con_ml,ctx["quality"],None)[0],6),
        "p_home":round(p_home,6),"quality":round(ctx["quality"],4),"model_market_anomaly":anomaly,"ml_features":[round(x,6) for x in ml_features],
        "ml_active":mls["active"],"picks":[{k:v for k,v in x.items() if k not in ("selected","reason","disp")} for x in picks]
    }
    hist[str(g["gamePk"])]=record
    return ctx,p_home,raw_ml,con_ml,mlp,anomaly,evals,picks

def discord_request(method="GET",payload=None):
    if not DISCORD_URL:return None,None
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8") if payload is not None else None
    req=urllib.request.Request(DISCORD_URL,data=data,headers={"User-Agent":"MLB-Betting-Bot-V7","Accept":"application/json","Content-Type":"application/json"},method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as r:return r.status,r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace");logging.error("Discord HTTP %s | %s",e.code,body[:500]);return e.code,body
    except Exception as e:logging.error("Discord réseau: %s",e);return None,str(e)

def discord_test():
    if not DISCORD_URL:logging.warning("Discord désactivé: secret absent");return False
    s,_=discord_request("GET")
    logging.info("Discord webhook %s", "OK" if s==200 else f"ERREUR {s}")
    return s==200

def send_embed(title,fields,color=3447003):
    if not DISCORD_URL:return False
    fs=[]
    for name,value in fields:
        if value:fs.append({"name":name[:256],"value":value[:1024],"inline":False})
    payload={"username":"MLB Betting Bot","allowed_mentions":{"parse":[]},"embeds":[{"title":title[:256],"color":color,"fields":fs,
             "footer":{"text":f"MLB V{VERSION} • value betting • aucune garantie de gain"}}]}
    for attempt in range(3):
        s,b=discord_request("POST",payload)
        if s in (200,204):time.sleep(.35);return True
        if s==429:
            try:w=max(.5,num(json.loads(b).get("retry_after"),1.5))
            except:w=1.5
            time.sleep(w);continue
        if s in (401,403,404):return False
        time.sleep(1+attempt)
    return False

def eval_text(x):
    if not x:return "Marché indisponible sur Winamax."
    point=f" {x['point']:+g}" if x["point"] is not None and x["market"]=="RUNLINE" else f" {x['point']:g}" if x["point"] is not None else ""
    head=f"**{x['market']} — {x['name']}{point} @ {x['price']:.2f}**"
    stats=f"Prob {pct(x['p_cond'])} • Fair {x['fair']:.2f} • Edge {x['edge']*100:+.1f} pts • EV {x['ev']*100:+.1f}% • refs {x['refs']} • qualité {x['quality']*10:.1f}/10"
    if x["selected"]:return head+"\n"+stats+f"\n✅ VALUE • **{x['units']:.2f}u = {x['stake_eur']:.2f} €**"
    return head+"\n"+stats+"\n❌ REJETÉ • "+x["reason"]

def send_game(g,ctx,p_home,raw,con,mlp,anomaly,evals,picks,mls):
    probs=(f"Finale **{ctx['home']} {pct(p_home)}** • {ctx['away']} {pct(1-p_home)}\n"
           f"Poisson/statistique: {pct(raw)} • consensus: {pct(con['p'])} ({con['n']} books)\n"
           f"Projection score: **{ctx['home']} {ctx['home_mu']:.2f} – {ctx['away_mu']:.2f} {ctx['away']}** • total {ctx['total_mu']:.2f}\n"
           f"ML historique: {'ACTIF '+pct(mlp) if mlp is not None else 'inactif'} • n={mls['n']}"
           +(f"\n⚠️ **Divergence brute modèle/marché: paris ML/RL bloqués**" if anomaly else "\n✅ Cohérence modèle/marché acceptable"))
    starters=(f"{ctx['away']}: **{ctx['away_sp']}** • {pitcher_line(ctx['away_sp_stats'])}\n"
              f"{ctx['home']}: **{ctx['home_sp']}** • {pitcher_line(ctx['home_sp_stats'])}")
    context=(f"Park factor {ctx['park']:.3f} • météo: {ctx['weather']['text']}\n"
             f"Bullpen fatigue H/A: {ctx['home_bullpen']:.2f}/{ctx['away_bullpen']:.2f}\n"
             f"Forme 10: {ctx['home']} {ctx['home_recent']['win_pct']*100:.0f}% (RD {ctx['home_recent']['run_diff_pg']:+.2f}/g) • "
             f"{ctx['away']} {ctx['away_recent']['win_pct']*100:.0f}% (RD {ctx['away_recent']['run_diff_pg']:+.2f}/g)\n"
             f"Qualité données brute: **{ctx['quality']*10:.1f}/10**")
    reps=[representative(evals,m) for m in ("ML","RUNLINE","TOTAL")]
    markets="\n\n".join(eval_text(x) for x in reps)
    best=("\n".join(f"• **{x['market']} {x['name']} {x['point'] if x['point'] is not None else ''} @ {x['price']:.2f}** • EV {x['ev']*100:+.1f}% • {x['units']:.2f}u" for x in picks[:3]) if picks else "❌ **NO BET** — aucun marché ne franchit tous les filtres.")
    return send_embed(f"⚾ MLB V{VERSION} • {ctx['away']} @ {ctx['home']}",[
        ("🕒 Match",local_time(g["gameDate"])+" (Paris)"),("🎯 Probabilités",probs),("🧑 Starters",starters),("🔬 Contexte",context),
        ("💰 Winamax — meilleurs prix par catégorie",markets),("✅ Décision",best)
    ],5763719 if picks else 9807270)

def top_messages(all_picks):
    for market,title in (("ML","🏆 TOP 3 MONEYLINE"),("RUNLINE","⚾ TOP 3 RUN LINE"),("TOTAL","📈 TOP 3 TOTAUX")):
        xs=sorted([x for x in all_picks if x["market"]==market],key=lambda z:(z["ev"],z["quality"]),reverse=True)[:3]
        if xs:
            body="\n\n".join(f"**#{i+1} {x['away']} @ {x['home']}**\n{x['name']} {x['point'] if x['point'] is not None else ''} @ **{x['price']:.2f}** • Prob {pct(x['p_cond'])} • Edge {x['edge']*100:+.1f} pts • EV {x['ev']*100:+.1f}% • **{x['units']:.2f}u / {x['stake_eur']:.2f} €**" for i,x in enumerate(xs))
        else:body="Aucun pari qualifié aujourd'hui."
        send_embed(title,[("Sélection V7",body)],16766720)

def performance(hist):
    settled=[r for r in hist.values() if r.get("status")=="FINAL" and r.get("p_home") is not None]
    br=brier([num(r["p_home"],.5) for r in settled],[int(r.get("home_win",0)) for r in settled]) if settled else None
    picks=[p for r in settled for p in r.get("picks",[]) if p.get("result") in ("W","L","P")]
    profit=sum(num(p.get("profit_eur")) for p in picks);stake=sum(num(p.get("stake_eur")) for p in picks if p.get("result")!="P")
    return {"games":len(settled),"brier":br,"picks":len(picks),"profit":profit,"roi":profit/stake if stake else None}

def main():
    logging.info("="*56);logging.info("MLB BETTING BOT V%s | %s",VERSION,TARGET_DATE);logging.info("="*56)
    if not ODDS_KEY:raise SystemExit("ODDS_API_KEY absente")
    discord_test()
    hist=load_history();settled=settle_history(hist);logging.info("Historique | %d matchs | %d réglés maintenant",len(hist),settled)
    mls=ml_state(hist);logging.info("ML historique | n=%d | actif=%s | Brier ML=%s | base=%s",mls["n"],mls["active"],f"{mls['brier_ml']:.4f}" if mls["brier_ml"] is not None else "-",f"{mls['brier_base']:.4f}" if mls["brier_base"] is not None else "-")
    games=mlb_schedule(TARGET_DATE);odds=odds_api()
    odds_map={(norm_name(x.get("away_team")),norm_name(x.get("home_team"))):x for x in odds}
    logging.info("Matchs MLB=%d | événements odds=%d",len(games),len(odds))
    all_picks=[];analyzed=0
    for g in games:
        away=g["teams"]["away"]["team"]["name"];home=g["teams"]["home"]["team"]["name"]
        event=odds_map.get((norm_name(away),norm_name(home)))
        if not event:
            logging.warning("Odds absentes: %s @ %s",away,home);continue
        try:
            ctx,p_home,raw,con,mlp,anom,evals,picks=analyze(g,event,mls,hist);analyzed+=1
            for x in picks:x.update({"home":home,"away":away,"game_pk":g["gamePk"]});all_picks.append(x)
            send_game(g,ctx,p_home,raw,con,mlp,anom,evals,picks,mls)
            logging.info("%s @ %s | pHome=%s | market=%s | picks=%d",away,home,pct(p_home),pct(con["p"]),len(picks))
        except Exception as e:logging.exception("Analyse %s @ %s: %s",away,home,e)
    write_history(hist);top_messages(all_picks)
    perf=performance(hist)
    logging.info("V%s terminé | %d/%d matchs analysés | %d bets",VERSION,analyzed,len(games),len(all_picks))
    logging.info("Performance | matchs réglés=%d | Brier=%s | picks=%d | profit=%.2f€ | ROI=%s",perf["games"],f"{perf['brier']:.4f}" if perf["brier"] is not None else "-",perf["picks"],perf["profit"],pct(perf["roi"]) if perf["roi"] is not None else "-")

if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception:logging.exception("ERREUR FATALE");raise
