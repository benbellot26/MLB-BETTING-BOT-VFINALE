#!/usr/bin/env python3
import os, sys, json, math, time, logging, urllib.request, urllib.parse, urllib.error, re, hashlib, random
from datetime import datetime, timezone, timedelta
from statistics import median, mean, pstdev
from pathlib import Path
from zoneinfo import ZoneInfo
from html.parser import HTMLParser

VERSION="9.0"
SCHEMA_VERSION=9
FEATURE_VERSION="9.0"
MODEL_VERSION="runs-residual-walkforward-v3"
VERDICT_VERSION="direction-calibrated-v3"
DIST_VERSION="nb-mle-split-v2"
PARIS=ZoneInfo("Europe/Paris")
NOW=datetime.now(timezone.utc)
LOCAL_NOW=datetime.now(PARIS)
DEFAULT_DATE=(LOCAL_NOW.date()-timedelta(days=1)).isoformat() if LOCAL_NOW.hour<6 else LOCAL_NOW.date().isoformat()
TARGET_DATE=os.getenv("MLB_DATE",DEFAULT_DATE)
SEASON=int(os.getenv("MLB_SEASON",TARGET_DATE[:4]))
ODDS_KEY=os.getenv("ODDS_API_KEY","").strip()
DISCORD_URL=os.getenv("DISCORD_WEBHOOK_URL","").strip()
HISTORY_FILE=Path(os.getenv("HISTORY_FILE","data/mlb_history_v9.jsonl"))
ARCHIVE_DIR=HISTORY_FILE.parent/"archive_v9"
STATE_FILE=HISTORY_FILE.parent/"v9_state.json"
BANKROLL=float(os.getenv("BANKROLL","10") or 10)
UNIT=float(os.getenv("UNIT","0.5") or .5)
MAX_STAKE_UNITS=float(os.getenv("MAX_STAKE_UNITS","3") or 3)
MIN_EV=float(os.getenv("MIN_EV","0.03") or .03)
MIN_EDGE=float(os.getenv("MIN_EDGE","0.025") or .025)
MIN_QUALITY=float(os.getenv("MIN_QUALITY","0.62") or .62)
MAX_DAILY_EXPOSURE_PCT=float(os.getenv("MAX_DAILY_EXPOSURE_PCT","0.30") or .30)
MAX_GAME_EXPOSURE_PCT=float(os.getenv("MAX_GAME_EXPOSURE_PCT","0.15") or .15)
MAX_BETS_PER_GAME=int(os.getenv("MAX_BETS_PER_GAME","2") or 2)
MATCH_MAX_DELTA_HOURS=float(os.getenv("MATCH_MAX_DELTA_HOURS","2.0") or 2.0)
RUN_MODEL_MIN_GAMES=int(os.getenv("RUN_MODEL_MIN_GAMES","140") or 140)
CAL_MIN_GAMES=int(os.getenv("CAL_MIN_GAMES","180") or 180)
SNAPSHOT_MIN_MINUTES=int(os.getenv("SNAPSHOT_MIN_MINUTES","15") or 15)
ARCHIVE_AFTER_DAYS=int(os.getenv("ARCHIVE_AFTER_DAYS","45") or 45)
BOOKMAKERS=os.getenv("ODDS_BOOKMAKERS","winamax_fr,pinnacle,betfair_ex_eu,betclic_fr,unibet_fr,pmu_fr,netbet_fr")
REF_BOOKS={x for x in BOOKMAKERS.split(",") if x and x!="winamax_fr"}
TIMEOUT=25
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper(),format="%(asctime)s | %(levelname)s | %(message)s")

PARK={"Arizona Diamondbacks":1.04,"Athletics":1.05,"Oakland Athletics":1.05,"Atlanta Braves":1.01,"Baltimore Orioles":1.01,"Boston Red Sox":1.03,"Chicago White Sox":1.00,"Chicago Cubs":1.02,"Cincinnati Reds":1.05,"Cleveland Guardians":0.98,"Colorado Rockies":1.14,"Detroit Tigers":0.98,"Houston Astros":1.00,"Kansas City Royals":0.99,"Los Angeles Angels":1.01,"Los Angeles Dodgers":0.98,"Miami Marlins":0.96,"Milwaukee Brewers":1.00,"Minnesota Twins":0.99,"New York Mets":0.98,"New York Yankees":1.03,"Philadelphia Phillies":1.02,"Pittsburgh Pirates":0.97,"San Diego Padres":0.97,"San Francisco Giants":0.94,"Seattle Mariners":0.96,"St. Louis Cardinals":1.00,"Tampa Bay Rays":0.98,"Texas Rangers":1.02,"Toronto Blue Jays":1.01,"Washington Nationals":1.00}
COORD={"Arizona Diamondbacks":(33.4453,-112.0667),"Athletics":(38.5806,-121.5130),"Oakland Athletics":(38.5806,-121.5130),"Atlanta Braves":(33.8907,-84.4677),"Baltimore Orioles":(39.2839,-76.6217),"Boston Red Sox":(42.3467,-71.0972),"Chicago White Sox":(41.8301,-87.6338),"Chicago Cubs":(41.9484,-87.6553),"Cincinnati Reds":(39.0975,-84.5069),"Cleveland Guardians":(41.4962,-81.6852),"Colorado Rockies":(39.7559,-104.9942),"Detroit Tigers":(42.3390,-83.0485),"Houston Astros":(29.7573,-95.3555),"Kansas City Royals":(39.0517,-94.4803),"Los Angeles Angels":(33.8003,-117.8827),"Los Angeles Dodgers":(34.0739,-118.2400),"Miami Marlins":(25.7781,-80.2197),"Milwaukee Brewers":(43.0280,-87.9712),"Minnesota Twins":(44.9817,-93.2776),"New York Mets":(40.7571,-73.8458),"New York Yankees":(40.8296,-73.9262),"Philadelphia Phillies":(39.9061,-75.1665),"Pittsburgh Pirates":(40.4469,-80.0057),"San Diego Padres":(32.7076,-117.1570),"San Francisco Giants":(37.7786,-122.3893),"Seattle Mariners":(47.5914,-122.3325),"St. Louis Cardinals":(38.6226,-90.1928),"Tampa Bay Rays":(27.7683,-82.6534),"Texas Rangers":(32.7473,-97.0832),"Toronto Blue Jays":(43.6414,-79.3894),"Washington Nationals":(38.8730,-77.0074)}
TEAM_KEYS={"Arizona Diamondbacks":["AZ","ARI"],"Athletics":["ATH","OAK"],"Oakland Athletics":["OAK"],"Atlanta Braves":["ATL"],"Baltimore Orioles":["BAL"],"Boston Red Sox":["BOS"],"Chicago White Sox":["CWS","CHW"],"Chicago Cubs":["CHC"],"Cincinnati Reds":["CIN"],"Cleveland Guardians":["CLE"],"Colorado Rockies":["COL"],"Detroit Tigers":["DET"],"Houston Astros":["HOU"],"Kansas City Royals":["KC","KCR"],"Los Angeles Angels":["LAA"],"Los Angeles Dodgers":["LAD"],"Miami Marlins":["MIA"],"Milwaukee Brewers":["MIL"],"Minnesota Twins":["MIN"],"New York Mets":["NYM"],"New York Yankees":["NYY"],"Philadelphia Phillies":["PHI"],"Pittsburgh Pirates":["PIT"],"San Diego Padres":["SD","SDP"],"San Francisco Giants":["SF","SFG"],"Seattle Mariners":["SEA"],"St. Louis Cardinals":["STL"],"Tampa Bay Rays":["TB","TBR"],"Texas Rangers":["TEX"],"Toronto Blue Jays":["TOR"],"Washington Nationals":["WSH","WAS"]}
ROOF={"Arizona Diamondbacks","Houston Astros","Miami Marlins","Milwaukee Brewers","Seattle Mariners","Texas Rangers","Toronto Blue Jays"}
DOME={"Tampa Bay Rays"}
ALIASES={"oaklandathletics":"athletics","athletics":"athletics"}
_CACHE={}

def norm_name(s):
    x="".join(c.lower() for c in str(s) if c.isalnum())
    return ALIASES.get(x,x)
def clamp(x,a=.001,b=.999):return max(a,min(b,x))
def num(x,d=0.0):
    try:
        y=float(x);return y if math.isfinite(y) else d
    except Exception:return d
def pct(x):return "N/A" if x is None else f"{100*x:.1f}%"
def parse_dt(s):return datetime.fromisoformat(str(s).replace("Z","+00:00"))
def local_time(iso):
    try:return parse_dt(iso).astimezone(PARIS).strftime("%d/%m/%Y %H:%M")
    except Exception:return str(iso)
def logit(p):
    p=clamp(p,.001,.999);return math.log(p/(1-p))
def sigmoid(x):return 1/(1+math.exp(-max(-30,min(30,x))))
def round_down_units(eur):
    if UNIT<=0:return 0.0,0.0
    u=math.floor((eur/UNIT)*4+1e-9)/4
    return (u,round(u*UNIT,2)) if u>=.25 else (0.0,0.0)

def http_raw(url,params=None,timeout=TIMEOUT,retries=2,headers=None):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,safe=",")
    h={"User-Agent":"Mozilla/5.0 MLB-Betting-Bot-V9","Accept":"text/html,application/xhtml+xml,*/*"}
    if headers:h.update(headers)
    last=None
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,headers=h)
            with urllib.request.urlopen(req,timeout=timeout) as r:return r.read(),{k.lower():v for k,v in r.headers.items()}
        except Exception as e:
            last=e
            if attempt>=retries:raise
            time.sleep(1+attempt)
    raise last
def http_json(url,params=None,method="GET",payload=None,timeout=TIMEOUT,return_headers=False,retries=2):
    if params:url+=("&" if "?" in url else "?")+urllib.parse.urlencode(params,safe=",")
    data=None;headers={"User-Agent":"MLB-Betting-Bot-V9","Accept":"application/json"}
    if payload is not None:data=json.dumps(payload,ensure_ascii=False).encode();headers["Content-Type"]="application/json"
    last=None
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,data=data,headers=headers,method=method)
            with urllib.request.urlopen(req,timeout=timeout) as r:
                body=r.read().decode("utf-8","replace");obj=json.loads(body) if body else None;hdr={k.lower():v for k,v in r.headers.items()}
                return (obj,hdr) if return_headers else obj
        except urllib.error.HTTPError as e:
            last=e
            if e.code not in (429,500,502,503,504) or attempt>=retries:raise
            wait=1.2*(attempt+1)
            try:
                if e.code==429:wait=max(wait,num(json.loads(e.read().decode("utf-8","replace")).get("retry_after"),wait))
            except Exception:pass
            time.sleep(wait)
        except Exception as e:
            last=e
            if attempt>=retries:raise
            time.sleep(1+attempt)
    raise last

def mlb(path,params=None):return http_json("https://statsapi.mlb.com/api/"+path.lstrip("/"),params)
def mlb_schedule(day,team_id=None,hydrate="probablePitcher"):
    p={"sportId":1,"date":day,"hydrate":hydrate}
    if team_id:p["teamId"]=team_id
    d=mlb("v1/schedule",p);return [g for block in d.get("dates",[]) for g in block.get("games",[])]
def stat_split(d):
    try:
        s=(d.get("stats") or [{}])[0].get("splits") or [];return s[0].get("stat",{}) if s else {}
    except Exception:return {}
def season_stats(team_id,group):
    key=("teamstats",team_id,group,SEASON)
    if key in _CACHE:return _CACHE[key]
    try:out=stat_split(mlb(f"v1/teams/{team_id}/stats",{"stats":"season","group":group,"season":SEASON}))
    except Exception as e:logging.warning("Stats %s/%s: %s",team_id,group,e);out={}
    _CACHE[key]=out;return out
def player_stats(pid,group="pitching"):
    if not pid:return {}
    key=("playerstats",pid,group,SEASON)
    if key in _CACHE:return _CACHE[key]
    try:out=stat_split(mlb(f"v1/people/{pid}/stats",{"stats":"season","group":group,"season":SEASON}))
    except Exception as e:logging.debug("Player stats %s: %s",pid,e);out={}
    _CACHE[key]=out;return out
def person_info(pid):
    if not pid:return {}
    key=("person",pid)
    if key in _CACHE:return _CACHE[key]
    try:out=(mlb(f"v1/people/{pid}").get("people") or [{}])[0]
    except Exception as e:logging.debug("Person %s: %s",pid,e);out={}
    _CACHE[key]=out;return out
def league_baselines():
    key=("league",SEASON)
    if key in _CACHE:return _CACHE[key]
    vals={"rpg":4.45,"era":4.35,"ops":.710,"obp":.320,"slg":.390,"whip":1.32}
    try:
        dh=mlb("v1/teams/stats",{"stats":"season","group":"hitting","season":SEASON,"sportIds":1});dp=mlb("v1/teams/stats",{"stats":"season","group":"pitching","season":SEASON,"sportIds":1});hs=(dh.get("stats") or [{}])[0].get("splits") or [];ps=(dp.get("stats") or [{}])[0].get("splits") or []
        if hs:
            vals["rpg"]=mean(num(x.get("stat",{}).get("runsPerGame"),4.45) for x in hs);vals["ops"]=mean(num(x.get("stat",{}).get("ops"),.710) for x in hs);vals["obp"]=mean(num(x.get("stat",{}).get("obp",x.get("stat",{}).get("onBasePercentage")),.320) for x in hs);vals["slg"]=mean(num(x.get("stat",{}).get("slg",x.get("stat",{}).get("sluggingPercentage")),.390) for x in hs)
        if ps:vals["era"]=mean(num(x.get("stat",{}).get("era"),4.35) for x in ps);vals["whip"]=mean(num(x.get("stat",{}).get("whip"),1.32) for x in ps)
    except Exception as e:logging.warning("Baselines MLB: %s",e)
    _CACHE[key]=vals;return vals

class TableParser(HTMLParser):
    def __init__(self):super().__init__();self.tables=[];self.table=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=="table":self.table=[]
        elif tag=="tr" and self.table is not None:self.row=[]
        elif tag in ("td","th") and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:self.row.append(" ".join("".join(self.cell).split()));self.cell=None
        elif tag=="tr" and self.row is not None:
            if any(self.row):self.table.append(self.row)
            self.row=None
        elif tag=="table" and self.table is not None:
            if self.table:self.tables.append(self.table)
            self.table=None

def _header_key(x):return re.sub(r"[^a-z0-9]","",str(x).lower())
def _fnum(x):
    try:return float(str(x).replace(",","").replace("%",""))
    except Exception:return None
def savant_league():
    key=("savant_league",SEASON)
    if key in _CACHE:return _CACHE[key]
    result={name:{"xwoba":None,"xslg":None,"xba":None,"pa":0,"available":False,"source":"Baseball Savant"} for name in TEAM_KEYS}
    try:
        raw,_=http_raw("https://baseballsavant.mlb.com/expected_statistics",{"type":"batter-team","year":SEASON,"min":0,"filterType":"pa"});p=TableParser();p.feed(raw.decode("utf-8","replace"));rows_found=0
        for table in p.tables:
            header_idx=None;headers=None
            for i,row in enumerate(table):
                h=[_header_key(x) for x in row]
                if "team" in h and "xwoba" in h and "xslg" in h and "xba" in h:header_idx=i;headers=h;break
            if header_idx is None:continue
            for row in table[header_idx+1:]:
                if len(row)<len(headers):continue
                d=dict(zip(headers,row));cell=str(d.get("team","")).upper();tokens=set(re.findall(r"[A-Z]{2,3}",cell));team_name=None
                for name,keys in TEAM_KEYS.items():
                    if any(k in tokens for k in keys):team_name=name;break
                if not team_name:continue
                result[team_name]={"xwoba":_fnum(d.get("xwoba")),"xslg":_fnum(d.get("xslg")),"xba":_fnum(d.get("xba")),"pa":int(_fnum(d.get("pa")) or 0),"available":True,"source":"Baseball Savant"};rows_found+=1
        logging.info("Baseball Savant | équipes Statcast récupérées=%d",rows_found)
    except Exception as e:logging.warning("Baseball Savant indisponible: %s",e)
    _CACHE[key]=result;return result
def savant_team(team_name):return savant_league().get(team_name,{"xwoba":None,"xslg":None,"xba":None,"pa":0,"available":False,"source":"Baseball Savant"})

def split_hitting(team_id,pitcher_hand):
    if pitcher_hand not in ("L","R"):return {}
    sit="vl" if pitcher_hand=="L" else "vr";key=("split",team_id,sit,SEASON)
    if key in _CACHE:return _CACHE[key]
    out={}
    for stat_type in ("statSplits","season"):
        try:
            out=stat_split(mlb(f"v1/teams/{team_id}/stats",{"stats":stat_type,"group":"hitting","season":SEASON,"sitCodes":sit}))
            if out:break
        except Exception:pass
    if out:
        overall=season_stats(team_id,"hitting");pa=num(out.get("plateAppearances"),0);prior_pa=180.0;w=pa/(pa+prior_pa);base=num(overall.get("ops"),league_baselines()["ops"]);out["_raw_ops"]=num(out.get("ops"),base);out["_shrunk_ops"]=base+w*(out["_raw_ops"]-base);out["_pa"]=pa;out["_weight"]=w
    _CACHE[key]=out;return out

def anchor_date_from_game(g):return parse_dt(g["gameDate"]).astimezone(PARIS).date()
def recent_games(team_id,anchor_date,days=14):
    key=("recent",team_id,anchor_date.isoformat(),days)
    if key in _CACHE:return _CACHE[key]
    end=anchor_date-timedelta(days=1);start=end-timedelta(days=days-1)
    try:
        d=mlb("v1/schedule",{"sportId":1,"teamId":team_id,"startDate":start.isoformat(),"endDate":end.isoformat()});gs=[g for block in d.get("dates",[]) for g in block.get("games",[]) if g.get("status",{}).get("abstractGameState")=="Final"]
    except Exception as e:logging.debug("Recent games: %s",e);gs=[]
    _CACHE[key]=gs;return gs
def recent_context(team_id,anchor_date):
    gs=recent_games(team_id,anchor_date,14)[-10:];wins=rf=ra=0.0
    for g in gs:
        h=g.get("teams",{}).get("home",{});a=g.get("teams",{}).get("away",{});is_h=h.get("team",{}).get("id")==team_id;own=h if is_h else a;opp=a if is_h else h;x=num(own.get("score"));y=num(opp.get("score"));rf+=x;ra+=y;wins+=int(x>y)
    n=len(gs);return {"games":n,"win_pct":wins/n if n else .5,"run_diff_pg":(rf-ra)/n if n else 0.0,"runs_pg":rf/n if n else league_baselines()["rpg"]}
def boxscore(game_pk,fresh=False):
    key=("box",game_pk)
    if key in _CACHE and not fresh:return _CACHE[key]
    try:out=mlb(f"v1/game/{game_pk}/boxscore")
    except Exception as e:logging.debug("Boxscore %s: %s",game_pk,e);out={}
    _CACHE[key]=out;return out
def feed_live(game_pk,fresh=False):
    key=("feed",game_pk)
    if key in _CACHE and not fresh:return _CACHE[key]
    try:out=mlb(f"v1.1/game/{game_pk}/feed/live")
    except Exception as e:logging.debug("Feed %s: %s",game_pk,e);out={}
    _CACHE[key]=out;return out

def lineup_context(game_pk,side):
    b=feed_live(game_pk,True).get("liveData",{}).get("boxscore",{}).get("teams",{}).get(side,{})
    if not b:b=boxscore(game_pk,True).get("teams",{}).get(side,{})
    ids=b.get("battingOrder") or [];players=b.get("players",{})
    if not ids:
        ordered=[]
        for p in players.values():
            bo=p.get("battingOrder")
            if bo:
                try:ordered.append((int(bo),p.get("person",{}).get("id")))
                except Exception:pass
        ids=[pid for _,pid in sorted(ordered)]
    rows=[];weights=[1.10,1.07,1.12,1.10,1.04,.99,.94,.89,.84]
    for order,pid in enumerate(ids[:9]):
        p=players.get(f"ID{pid}",{});st=p.get("seasonStats",{}).get("hitting",{});ops=num(st.get("ops"),0) if st else 0;rows.append({"id":pid,"name":p.get("person",{}).get("fullName",str(pid)),"ops":ops if ops>.2 else None,"order":order+1,"weight":weights[order]})
    vals=[(r["ops"],r["weight"]) for r in rows if r["ops"] is not None];weighted_ops=sum(v*w for v,w in vals)/sum(w for _,w in vals) if len(vals)>=5 else None
    return {"confirmed":len(rows)>=8,"count":len(rows),"weighted_ops":weighted_ops,"players":rows}

def bullpen_profile(team_id,anchor_date):
    gs=recent_games(team_id,anchor_date,7)[-5:];team_pitch=season_stats(team_id,"pitching");prior_era=num(team_pitch.get("era"),league_baselines()["era"])
    if not gs:return {"load":.5,"era":prior_era,"whip":league_baselines()["whip"],"ip":0.0,"games":0,"quality":.45}
    weighted=outs=er=hits=walks=0.0;seen=0
    for g in gs:
        try:
            gd=parse_dt(g["gameDate"]).astimezone(PARIS).date();age=max(1,(anchor_date-gd).days)
            if age>5:continue
            side="home" if g["teams"]["home"]["team"]["id"]==team_id else "away";team=boxscore(g["gamePk"]).get("teams",{}).get(side,{});gp=0
            for p in team.get("players",{}).values():
                st=p.get("stats",{}).get("pitching",{})
                if not st or num(st.get("gamesStarted"),0)>=1:continue
                po=num(st.get("outs"),0)
                if po<=0:
                    ip=str(st.get("inningsPitched","0"));po=int(num(ip.split(".")[0]))*3+(int(ip.split(".")[1][:1]) if "." in ip else 0)
                outs+=po;er+=num(st.get("earnedRuns"));hits+=num(st.get("hits"));walks+=num(st.get("baseOnBalls"));gp+=num(st.get("pitchesThrown"))
            weighted+=gp*{1:1.0,2:.65,3:.40,4:.25,5:.15}.get(age,.1);seen+=1
        except Exception:pass
    ip=outs/3;recent_era=9*er/ip if ip else prior_era;recent_whip=(hits+walks)/ip if ip else league_baselines()["whip"];w=ip/(ip+18)
    return {"load":clamp(weighted/180,0,1.5),"era":clamp(prior_era+w*(recent_era-prior_era),2.2,7.0),"whip":clamp(league_baselines()["whip"]+w*(recent_whip-league_baselines()["whip"]),.85,1.9),"ip":ip,"games":seen,"quality":min(1,.45+ip/30)}

def weather(team,iso):
    if team not in COORD:return {"text":"N/A","run_adj":0,"quality":0}
    try:
        gd=parse_dt(iso).astimezone(timezone.utc);delta=(gd.date()-datetime.now(timezone.utc).date()).days
        if delta<0 or delta>3:return {"text":"hors fenêtre prévisionnelle","run_adj":0,"quality":0}
        lat,lon=COORD[team];d=http_json("https://api.open-meteo.com/v1/forecast",{"latitude":lat,"longitude":lon,"hourly":"temperature_2m,wind_speed_10m,wind_direction_10m,relative_humidity_2m,precipitation_probability","forecast_days":4,"timezone":"UTC"});target=gd.replace(minute=0,second=0,microsecond=0,tzinfo=None);ts=[datetime.fromisoformat(x) for x in d["hourly"]["time"]];i=min(range(len(ts)),key=lambda j:abs(ts[j]-target))
        if abs((ts[i]-target).total_seconds())>5400:return {"text":"prévision horaire indisponible","run_adj":0,"quality":0}
        t=num(d["hourly"]["temperature_2m"][i]);w=num(d["hourly"]["wind_speed_10m"][i]);wd=num(d["hourly"]["wind_direction_10m"][i]);h=num(d["hourly"]["relative_humidity_2m"][i]);pr=num(d["hourly"]["precipitation_probability"][i]);raw=(t-20)*.010+max(0,w-15)*.003
        if team in DOME:factor=0;note="dôme"
        elif team in ROOF:factor=.2;note="toit rétractable: impact réduit"
        else:factor=1;note="extérieur"
        return {"text":f"{t:.0f}°C • vent {w:.0f} km/h ({wd:.0f}°) • HR {h:.0f}% • pluie {pr:.0f}% • {note}","run_adj":raw*factor,"quality":1}
    except Exception as e:logging.debug("Weather %s: %s",team,e);return {"text":"N/A","run_adj":0,"quality":0}

def ip_float(v):
    try:
        t=str(v or "0")
        if "." not in t:return float(t)
        a,b=t.split(".",1);return float(a)+int(b[:1] or 0)/3
    except Exception:return 0
def shrunk_pitcher(p):
    lg=league_baselines();ip=ip_float(p.get("inningsPitched")) if p else 0;wr=ip/(ip+35);wk=ip/(ip+25);re=num(p.get("era"),lg["era"]) if p else lg["era"];rw=num(p.get("whip"),lg["whip"]) if p else lg["whip"];rk=num(p.get("strikeOutsPer9"),8.3) if p else 8.3;rb=num(p.get("walksPer9"),3.2) if p else 3.2
    return {"ip":ip,"era":clamp(lg["era"]+wr*(re-lg["era"]),2.1,6.8),"whip":clamp(lg["whip"]+wr*(rw-lg["whip"]),.9,1.8),"k9":clamp(8.3+wk*(rk-8.3),4.5,13),"bb9":clamp(3.2+wk*(rb-3.2),1,6),"raw_era":re,"raw_whip":rw}
def pitcher_line(p,hand="?"):
    if not p:return f"main {hand} • données indisponibles"
    q=shrunk_pitcher(p)
    return (f"main {hand} • ERA {q['raw_era']:.2f}→{q['era']:.2f} adj • WHIP {q['raw_whip']:.2f}→{q['whip']:.2f} • K/9 {q['k9']:.1f} • BB/9 {q['bb9']:.1f} • IP {q['ip']:.1f}") if q["ip"]<35 else f"main {hand} • ERA {q['era']:.2f} • WHIP {q['whip']:.2f} • K/9 {q['k9']:.1f} • BB/9 {q['bb9']:.1f} • IP {q['ip']:.1f}"

def team_bundle(team_id,team_name,anchor):return season_stats(team_id,"hitting"),season_stats(team_id,"pitching"),recent_context(team_id,anchor),bullpen_profile(team_id,anchor),savant_team(team_name)
def base_runs(own_h,opp_p,recent,park,wx,home):
    lg=league_baselines();rpg=num(own_h.get("runsPerGame"),lg["rpg"]);gp=max(1,num(opp_p.get("gamesPlayed"),0));opp_ra=num(opp_p.get("runs"),0)/gp if num(opp_p.get("runs"),0)>0 else lg["rpg"]*num(opp_p.get("era"),lg["era"])/lg["era"];recent_r=recent["runs_pg"] if recent["games"]>=5 else rpg;base=mean([rpg,opp_ra,recent_r])*park*(1+wx["run_adj"]*.025)+(0.08 if home else 0);return clamp(base,2.2,7.2)
def run_features(own_h,opp_p,own_recent,opp_recent,opp_sp,opp_bp,lineup,split,statcast,park,wx,home):
    lg=league_baselines();own_ops=num(own_h.get("ops"),lg["ops"]);split_ops=num(split.get("_shrunk_ops"),own_ops) if split else own_ops;lineup_ops=lineup.get("weighted_ops");xwoba=statcast.get("xwoba") if statcast else None
    return [(num(own_h.get("runsPerGame"),lg["rpg"])-lg["rpg"])/1.4,(own_ops-lg["ops"])/.09,(num(own_h.get("obp",own_h.get("onBasePercentage")),lg["obp"])-lg["obp"])/.045,(num(own_h.get("slg",own_h.get("sluggingPercentage")),lg["slg"])-lg["slg"])/.075,(num(opp_p.get("era"),lg["era"])-lg["era"])/1.3,(opp_sp["era"]-lg["era"])/1.6,(opp_sp["whip"]-lg["whip"])/.30,(opp_sp["bb9"]-3.2)/1.8-(opp_sp["k9"]-8.3)/2.8,(opp_bp["era"]-lg["era"])/1.6,(opp_bp["load"]-.5)/.6,(own_recent["run_diff_pg"]-opp_recent["run_diff_pg"])/2.5,((lineup_ops-own_ops)/.08) if lineup_ops is not None else 0,(split_ops-own_ops)/.08,((xwoba-.317)/.045) if xwoba is not None else 0,(park-1)/.08,wx["run_adj"]/.20,1 if home else 0]
def phase_quality(ctx,phase):
    core=sum(ctx["core_flags"])/len(ctx["core_flags"]);adv=sum(ctx["adv_flags"])/len(ctx["adv_flags"]);line=(ctx["home_lineup"]["count"]+ctx["away_lineup"]["count"])/18
    if phase=="EARLY":q=.72*core+.28*adv
    elif phase=="LATE":q=.60*core+.25*adv+.15*line
    else:q=.50*core+.25*adv+.25*line
    return clamp(q,0,1)
def game_context(g):
    home=g["teams"]["home"]["team"];away=g["teams"]["away"]["team"];anchor=anchor_date_from_game(g);hh,hp,hr,hbp,hsc=team_bundle(home["id"],home["name"],anchor);ah,ap,ar,abp,asc=team_bundle(away["id"],away["name"],anchor);hsp=g["teams"]["home"].get("probablePitcher") or {};asp=g["teams"]["away"].get("probablePitcher") or {};hraw=player_stats(hsp.get("id"));araw=player_stats(asp.get("id"));hs=shrunk_pitcher(hraw);ass=shrunk_pitcher(araw);hhand=person_info(hsp.get("id")).get("pitchHand",{}).get("code","?");ahand=person_info(asp.get("id")).get("pitchHand",{}).get("code","?");hsplit=split_hitting(home["id"],ahand);asplit=split_hitting(away["id"],hhand);hline=lineup_context(g["gamePk"],"home");aline=lineup_context(g["gamePk"],"away");wx=weather(home["name"],g["gameDate"]);park=PARK.get(home["name"],1);bh=base_runs(hh,ap,hr,park,wx,True);ba=base_runs(ah,hp,ar,park,wx,False);fh=run_features(hh,ap,hr,ar,ass,abp,hline,hsplit,hsc,park,wx,True);fa=run_features(ah,hp,ar,hr,hs,hbp,aline,asplit,asc,park,wx,False);core=[bool(hh),bool(ah),bool(hp),bool(ap),bool(hraw),bool(araw),hbp["games"]>0,abp["games"]>0,wx["quality"]>0];adv=[hhand in ("L","R"),ahand in ("L","R"),num(hsplit.get("_pa"),0)>=80,num(asplit.get("_pa"),0)>=80,hsc["available"],asc["available"]]
    return {"home":home["name"],"away":away["name"],"home_id":home["id"],"away_id":away["id"],"home_sp":hsp.get("fullName","Non annoncé"),"away_sp":asp.get("fullName","Non annoncé"),"home_sp_stats":hraw,"away_sp_stats":araw,"home_hand":hhand,"away_hand":ahand,"home_recent":hr,"away_recent":ar,"home_bp":hbp,"away_bp":abp,"home_lineup":hline,"away_lineup":aline,"home_split":hsplit,"away_split":asplit,"home_statcast":hsc,"away_statcast":asc,"park":park,"weather":wx,"core_flags":core,"adv_flags":adv,"base_home":bh,"base_away":ba,"run_features_home":fh,"run_features_away":fa}

def fit_linear(rows,epochs=420,lr=.012,l2=.006):
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
def linear_predict(m,x):
    z=[(x[j]-m["mean"][j])/m["std"][j] for j in range(len(x))];return m["b"]+sum(a*c for a,c in zip(m["w"],z))
def rmse_loss(pred,y):return (pred-y)**2
def bootstrap_gain_prob(base_losses,new_losses,reps=400):
    if not base_losses or len(base_losses)!=len(new_losses):return 0.0
    rng=random.Random(90210);n=len(base_losses);wins=0
    for _ in range(reps):
        gain=0.0
        for _ in range(n):
            i=rng.randrange(n);gain+=base_losses[i]-new_losses[i]
        if gain/n>0:wins+=1
    return wins/reps

def latest_pregame_snapshot(r,feature=FEATURE_VERSION):
    s=[x for x in r.get("snapshots",[]) if num(x.get("seconds_to_game"),-1)>=0 and x.get("feature_version")==feature and x.get("model_version")==MODEL_VERSION and x.get("distribution_version")==DIST_VERSION];return max(s,key=lambda x:x.get("analyzed_at","")) if s else None
def training_games(hist):
    out=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s:continue
        try:out.append((r.get("game_date",""),s,float(r["home_score"]),float(r["away_score"])))
        except Exception:pass
    out.sort(key=lambda z:z[0]);return out
def walk_folds(n,min_train=90):
    folds=[]
    for frac in (.58,.68,.78):
        cut=int(n*frac);end=min(n,cut+max(20,int(n*.10)))
        if cut>=min_train and end-cut>=15:folds.append((cut,end))
    return folds
def run_model_state(hist):
    games=training_games(hist);out={"active":False,"model":None,"n":len(games),"rmse_model":None,"rmse_base":None,"gain_prob":0.0,"folds":0}
    if len(games)<RUN_MODEL_MIN_GAMES:return out
    base_losses=[];new_losses=[];folds=walk_folds(len(games),90)
    for cut,end in folds:
        train=[]
        for _,s,hs,as_ in games[:cut]:train += [(s["run_features_home"],hs-num(s["base_home"])),(s["run_features_away"],as_-num(s["base_away"]))]
        m=fit_linear(train)
        for _,s,hs,as_ in games[cut:end]:
            ph=num(s["base_home"])+clamp(linear_predict(m,s["run_features_home"]),-2,2);pa=num(s["base_away"])+clamp(linear_predict(m,s["run_features_away"]),-2,2);base_losses += [rmse_loss(num(s["base_home"]),hs),rmse_loss(num(s["base_away"]),as_)];new_losses += [rmse_loss(ph,hs),rmse_loss(pa,as_)]
    if not base_losses:return out
    rb=math.sqrt(mean(base_losses));rn=math.sqrt(mean(new_losses));gp=bootstrap_gain_prob(base_losses,new_losses);out.update({"rmse_base":rb,"rmse_model":rn,"gain_prob":gp,"folds":len(folds)})
    if rn+.035<rb and gp>=.90:
        rows=[]
        for _,s,hs,as_ in games:rows += [(s["run_features_home"],hs-num(s["base_home"])),(s["run_features_away"],as_-num(s["base_away"]))]
        out.update({"active":True,"model":fit_linear(rows)})
    return out
def project_runs(ctx,state):
    h,a=ctx["base_home"],ctx["base_away"]
    if state["active"]:h+=clamp(linear_predict(state["model"],ctx["run_features_home"]),-2,2);a+=clamp(linear_predict(state["model"],ctx["run_features_away"]),-2,2)
    return clamp(h,2,8),clamp(a,2,8)

def nb_logpmf(y,mu,alpha):
    if alpha<=1e-6:return -mu+y*math.log(mu)-math.lgamma(y+1)
    r=1/alpha;return math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(r/(r+mu))+y*math.log(mu/(r+mu))
def fit_alpha_mle(rows):
    grid=[.02+i*.01 for i in range(44)];best=(1e99,.12)
    for a in grid:
        nll=-sum(nb_logpmf(int(y),max(.05,mu),a) for mu,y in rows)
        if nll<best[0]:best=(nll,a)
    return best[1]
def dispersion_state(hist):
    games=training_games(hist);home=[(num(s.get("home_mu"),0),hs) for _,s,hs,_ in games if num(s.get("home_mu"),0)>0];away=[(num(s.get("away_mu"),0),as_) for _,s,_,as_ in games if num(s.get("away_mu"),0)>0];out={"alpha_home":.12,"alpha_away":.12,"n":min(len(home),len(away)),"learned":False,"gain_prob":0.0}
    if len(home)<100 or len(away)<100:return out
    cut=int(min(len(home),len(away))*.75);ah=fit_alpha_mle(home[:cut]);aa=fit_alpha_mle(away[:cut]);base=[];new=[]
    for (mu,y),a in [(x,ah) for x in home[cut:]]+[(x,aa) for x in away[cut:]]:
        base.append(-nb_logpmf(int(y),mu,.12));new.append(-nb_logpmf(int(y),mu,a))
    gp=bootstrap_gain_prob(base,new);out.update({"gain_prob":gp})
    if mean(new)<mean(base) and gp>=.85:out.update({"alpha_home":ah,"alpha_away":aa,"learned":True})
    return out
def nb_pmf(mu,alpha,max_runs=30):
    r=1/alpha;p=[(r/(r+mu))**r]
    for k in range(max_runs):p.append(p[-1]*((k+r)/(k+1))*(mu/(r+mu)))
    s=sum(p);return [x/s for x in p]
def extra_innings_home_prob(ctx):
    x=.53+.035*(ctx["away_bp"]["load"]-ctx["home_bp"]["load"])+.025*((ctx["away_bp"]["era"]-ctx["home_bp"]["era"])/2);return clamp(x,.43,.63)
def ml_prob(hmu,amu,ah,aa,extra_home):
    h=nb_pmf(hmu,ah);a=nb_pmf(amu,aa);w=t=0
    for i,pi in enumerate(h):
        for j,pj in enumerate(a):
            z=pi*pj
            if i>j:w+=z
            elif i==j:t+=z
    return clamp(w+extra_home*t)
def line_probs(hmu,amu,ah,aa,kind,name,point,home,away):
    h=nb_pmf(hmu,ah);a=nb_pmf(amu,aa);w=p=l=0
    for i,pi in enumerate(h):
        for j,pj in enumerate(a):
            z=pi*pj;v=(i+point-j) if kind=="RUNLINE" and norm_name(name)==norm_name(home) else (j+point-i) if kind=="RUNLINE" else (i+j-point) if str(name).lower()=="over" else (point-i-j)
            if v>1e-9:w+=z
            elif v<-1e-9:l+=z
            else:p+=z
    s=w+p+l;return w/s,p/s,l/s

def odds_api():
    d,h=http_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",{"apiKey":ODDS_KEY,"bookmakers":BOOKMAKERS,"markets":"h2h,spreads,totals","oddsFormat":"decimal","dateFormat":"iso"},return_headers=True);logging.info("The Odds API | coût=%s | restant=%s | utilisé=%s",h.get("x-requests-last","?"),h.get("x-requests-remaining","?"),h.get("x-requests-used","?"));return d or []
def match_odds_events(games,events):
    groups={}
    for e in events:groups.setdefault((norm_name(e.get("away_team")),norm_name(e.get("home_team"))),[]).append(e)
    out={};used=set()
    for g in sorted(games,key=lambda x:x.get("gameDate","")):
        away=g["teams"]["away"]["team"]["name"];home=g["teams"]["home"]["team"]["name"];cand=[e for e in groups.get((norm_name(away),norm_name(home)),[]) if e.get("id") not in used]
        if not cand:continue
        gt=parse_dt(g["gameDate"]);rank=[]
        for e in cand:
            try:d=abs((parse_dt(e["commence_time"])-gt).total_seconds())
            except Exception:d=1e12
            rank.append((d,e))
        delta,e=min(rank,key=lambda z:z[0])
        if delta<=MATCH_MAX_DELTA_HOURS*3600:out[str(g["gamePk"])]=(e,delta/60);used.add(e.get("id"))
        else:logging.warning("Odds rejetées (écart %.1fh): %s @ %s",delta/3600,away,home)
    return out
def market_rows(event,market):return [(b,m) for b in event.get("bookmakers",[]) for m in b.get("markets",[]) if m.get("key")==market]
def winamax_outcomes(event,market):return next(((b,m) for b,m in market_rows(event,market) if b.get("key")=="winamax_fr"),(None,None))
def fair_book_probability(outcomes,name,point=None,market="h2h"):
    if market=="h2h":
        probs={norm_name(o.get("name")):1/num(o.get("price"),999) for o in outcomes if num(o.get("price"))>1};s=sum(probs.values());k=norm_name(name);return probs.get(k)/s if len(probs)>=2 and k in probs and s else None
    if market=="totals":
        xs=[o for o in outcomes if abs(num(o.get("point"))-num(point))<1e-6];probs={str(o.get("name")):1/num(o.get("price"),999) for o in xs if num(o.get("price"))>1};s=sum(probs.values());return probs.get(str(name))/s if len(probs)>=2 and str(name) in probs and s else None
    target=next((o for o in outcomes if norm_name(o.get("name"))==norm_name(name) and abs(num(o.get("point"))-num(point))<1e-6),None);other=next((o for o in outcomes if norm_name(o.get("name"))!=norm_name(name) and abs(num(o.get("point"))+num(point))<1e-6),None)
    if not target or not other:return None
    a=1/num(target.get("price"),999);b=1/num(other.get("price"),999);return a/(a+b) if a+b else None
def consensus(event,market,name,point=None):
    vals=[];ages=[]
    for b,m in market_rows(event,market):
        if b.get("key") not in REF_BOOKS:continue
        p=fair_book_probability(m.get("outcomes",[]),name,point,market)
        if p is None:continue
        try:age=max(0,(NOW-parse_dt(m.get("last_update",b.get("last_update")))).total_seconds()/60)
        except Exception:age=10
        if age>90:continue
        weight=max(.25,1-age/120);vals += [p]*max(1,int(round(weight*4)));ages.append(age)
    if not vals:return {"p":None,"n":0,"disp":None,"age_min":None}
    return {"p":median(vals),"n":len(ages),"disp":pstdev(vals) if len(vals)>1 else 0,"age_min":median(ages) if ages else None}
def serialize_market(event):
    out=[]
    for b in event.get("bookmakers",[]):
        item={"book":b.get("key"),"last_update":b.get("last_update"),"markets":[]}
        for m in b.get("markets",[]):
            if m.get("key") in ("h2h","spreads","totals"):item["markets"].append({"key":m.get("key"),"last_update":m.get("last_update"),"outcomes":[{"name":o.get("name"),"price":o.get("price"),"point":o.get("point")} for o in m.get("outcomes",[])]})
        if item["markets"]:out.append(item)
    return out
def snapshot_price(snapshot,market,name,point=None,book="winamax_fr"):
    mk={"ML":"h2h","RUNLINE":"spreads","TOTAL":"totals"}.get(market,market)
    for b in snapshot.get("market_snapshot",[]):
        if b.get("book")!=book:continue
        for m in b.get("markets",[]):
            if m.get("key")!=mk:continue
            for o in m.get("outcomes",[]):
                same=norm_name(o.get("name"))==norm_name(name) if mk!="totals" else str(o.get("name")).lower()==str(name).lower();line_ok=True if point is None else abs(num(o.get("point"))-num(point))<1e-6
                if same and line_ok:return num(o.get("price"),0)
    return None

def fit_platt(rows,epochs=500,lr=.025):
    a=0;b=1
    for ep in range(epochs):
        eta=lr*(1-ep/(epochs*1.4))
        for p,y in rows:
            p=clamp(p,.01,.99);x=logit(p);q=sigmoid(a+b*x);e=q-y;a-=eta*e;b-=eta*(e*x+.002*(b-1))
    return a,b
def platt_predict(m,p):return p if not m else clamp(sigmoid(m[0]+m[1]*logit(p)))
def brier(ps,ys):return mean((p-y)**2 for p,y in zip(ps,ys)) if ps else None
def calibration_state(hist,engine_mode):
    rows=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if s and s.get("engine_mode")==engine_mode and s.get("p_model_raw") is not None:rows.append((r.get("game_date",""),num(s["p_model_raw"],.5),int(r.get("home_win",0))))
    rows.sort();out={"active":False,"model":None,"n":len(rows),"brier_raw":None,"brier_cal":None,"gain_prob":0.0,"folds":0}
    if len(rows)<CAL_MIN_GAMES:return out
    base_losses=[];new_losses=[];folds=walk_folds(len(rows),110)
    for cut,end in folds:
        m=fit_platt([(p,y) for _,p,y in rows[:cut]])
        for _,p,y in rows[cut:end]:base_losses.append((p-y)**2);new_losses.append((platt_predict(m,p)-y)**2)
    if not base_losses:return out
    br=mean(base_losses);bc=mean(new_losses);gp=bootstrap_gain_prob(base_losses,new_losses);out.update({"brier_raw":br,"brier_cal":bc,"gain_prob":gp,"folds":len(folds)})
    if bc+.001<br and gp>=.90:out.update({"active":True,"model":fit_platt([(p,y) for _,p,y in rows])})
    return out
def skill_state(hist,engine_mode):
    pm=[];pk=[];ys=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s or s.get("engine_mode")!=engine_mode or s.get("p_model") is None or s.get("market_home") is None:continue
        pm.append(num(s["p_model"],.5));pk.append(num(s["market_home"],.5));ys.append(int(r.get("home_win",0)))
    if len(ys)<60:return {"n":len(ys),"brier_model":None,"brier_market":None,"model_weight":.42}
    bm=brier(pm,ys);bk=brier(pk,ys);gap=bk-bm;w=clamp(.42+gap*8,.25,.68);return {"n":len(ys),"brier_model":bm,"brier_market":bk,"model_weight":w}

def confidence_empirical(hist,typ,base,engine_mode):
    lo=max(0,math.floor(base/2)*2);hi=min(10,lo+2);wins=n=0
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s or s.get("engine_mode")!=engine_mode or s.get("verdict_version")!=VERDICT_VERSION or s.get("verdict_type")!=typ:continue
        sc=num(s.get("confidence_base"),-1)
        if lo<=sc<hi and s.get("directional_pick"):
            correct=(norm_name(s["directional_pick"])==norm_name(r["home"]) and r.get("home_win")==1) or (norm_name(s["directional_pick"])==norm_name(r["away"]) and r.get("home_win")==0);wins+=int(correct);n+=1
    if n<20:return None,n
    posterior=(wins+10)/(n+20);score=clamp(5+(posterior-.5)*20,2,9.8);return score,n
def market_verdict(ctx,p_model,p_market,meta,skill,hist,engine_mode,quality):
    home,away=ctx["home"],ctx["away"];mside=home if p_model>=.5 else away;mstr=max(p_model,1-p_model);mq=clamp((min(meta["n"],4)/4)*(.95-min(.45,(meta["disp"] or 0)*8)),0,1)
    if p_market is None:typ="MODEL_ONLY";side=mside;base=clamp(3+3*quality+2.5*min(1,(mstr-.5)/.18),0,9);text=f"🧠 **MODÈLE SEUL** — consensus insuffisant. Préférence **{side}**."
    else:
        kside=home if p_market>=.5 else away;kstr=max(p_market,1-p_market);gap=abs(p_model-p_market)
        if mside==kside:typ="CONFIRMED";side=mside;base=3.1+1.8*quality+1.2*mq+1.7*min(1,(mstr-.5)/.18)+1.0*min(1,(kstr-.5)/.15);text=f"✅ **MARCHÉ CONFIRMÉ** — marché et modèle indépendant préfèrent **{side}**."
        elif quality>=.70 and mstr>=.55 and gap>=.06:typ="CONTRARIAN";side=mside;base=2.9+2*quality+1.0*mq+2.0*min(1,(mstr-.5)/.18)+1.0*min(1,gap/.15);text=f"🔄 **MARCHÉ CONTESTÉ** — marché: **{kside}**, modèle: **{mside}**. Pick contrarian **{side}**."
        else:typ="UNCERTAIN";side=home if (.55*p_model+.45*p_market)>=.5 else away;base=3+1.5*quality+.8*mq+.7*min(1,abs((.55*p_model+.45*p_market)-.5)/.10);text=f"⚠️ **DÉSACCORD NON RÉSOLU** — léger avantage **{side}**, signal faible."
    base=clamp(base,0,9.7);emp,n=confidence_empirical(hist,typ,base,engine_mode);score=.55*base+.45*emp if emp is not None else base
    return {"side":side,"type":typ,"confidence":clamp(score,0,9.8),"confidence_base":base,"emp_n":n,"text":text}
def confidence_band(score):
    if score>=8:return "🟢","TRÈS FORT",5763719
    if score>=6:return "🟡","INTÉRESSANT",16766720
    if score>=4.5:return "🟠","PRUDENCE",15105570
    return "🔴","FAIBLE",15548997

def stake_candidate(pw,pp,pl,price):
    np=pw+pl
    if np<=0 or price<=1:return 0,0
    p=pw/np;b=price-1;k=max(0,(p*price-1)/b);eur=min(BANKROLL*k*.25,UNIT*MAX_STAKE_UNITS);return round_down_units(eur)
def evaluate(ctx,quality,kind,name,price,point,model_tuple,cons):
    pw,pp,pl=model_tuple;cm=pw/(pw+pl) if pw+pl else .5
    if cons["p"] is not None and kind!="ML":
        mq=clamp(min(cons["n"],4)/4,0,1);wm=.45+.20*mq;c=(1-wm)*cm+wm*cons["p"];c=clamp(c,cons["p"]-.10,cons["p"]+.10);pw=(1-pp)*c;pl=(1-pp)*(1-c)
    cond=pw/(pw+pl) if pw+pl else 0;edge=cond-1/price;ev=pw*price+pp-1;fair=(1-pp)/pw if pw>0 else 99;mq=min(1,cons["n"]/4)*(1-min(.5,(cons["disp"] or 0)*8)) if cons["p"] is not None else 0;q=.72*quality+.28*mq;reasons=[]
    if cons["n"]<2:reasons.append(f"consensus insuffisant ({cons['n']} book)")
    if q<MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10")
    if edge<MIN_EDGE:reasons.append(f"edge {edge*100:+.1f} pts < {MIN_EDGE*100:.1f}")
    if ev<MIN_EV:reasons.append(f"EV {ev*100:+.1f}% < {MIN_EV*100:.1f}%")
    cu,cs=stake_candidate(pw,pp,pl,price)
    if not reasons and cu<=0:reasons.append("Kelly prudent < 0.25u")
    return {"market":kind,"name":name,"point":point,"price":price,"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":cond,"fair":fair,"edge":edge,"ev":ev,"quality":q,"refs":cons["n"],"qualified":not reasons,"reason":"OK" if not reasons else " ; ".join(reasons),"candidate_units":cu,"candidate_stake_eur":cs,"selected":False,"units":0.0,"stake_eur":0.0,"portfolio_reason":""}

def snapshot_phase(seconds):
    h=seconds/3600;return "FINAL" if h<=2.5 else "LATE" if h<=6 else "EARLY"
def snapshot_role(rec,phase):
    if not rec.get("snapshots"):return "OPENING"
    return "CLOSING_CANDIDATE" if phase=="FINAL" else "CURRENT"
def correlation_factor(existing,p):
    if not existing:return 1.0
    factor=.65
    for q in existing:
        if {q["market"],p["market"]}=={"ML","RUNLINE"} and norm_name(q["name"])==norm_name(p["name"]):factor=min(factor,.35)
        elif q["market"]==p["market"]:factor=min(factor,.30)
    return factor
def allocate_portfolio(results):
    daily_cap=BANKROLL*MAX_DAILY_EXPOSURE_PCT;game_cap=BANKROLL*MAX_GAME_EXPOSURE_PCT;remaining=daily_cap;chosen={};candidates=[]
    for r in results:
        if r["phase"]=="EARLY":
            for e in r["evals"]:
                if e["qualified"]:e["portfolio_reason"]="WATCHLIST EARLY — aucune mise autorisée"
            continue
        for e in r["evals"]:
            if e["qualified"]:candidates.append((e["ev"]*e["quality"]+max(0,e["edge"])*.5,r,e))
    for _,r,e in sorted(candidates,key=lambda x:x[0],reverse=True):
        gid=str(r["game_pk"]);existing=chosen.setdefault(gid,[])
        if len(existing)>=MAX_BETS_PER_GAME:e["portfolio_reason"]="limite de paris par match";continue
        used=sum(x["stake_eur"] for x in existing);room_game=max(0,game_cap-used)
        if remaining<=0:e["portfolio_reason"]="exposition quotidienne maximale atteinte";continue
        f=correlation_factor(existing,e);target=min(e["candidate_stake_eur"]*f,remaining,room_game);u,stake=round_down_units(target)
        if u<.25:e["portfolio_reason"]="mise réduite sous 0.25u par contrôle portefeuille";continue
        e.update({"selected":True,"units":u,"stake_eur":stake,"portfolio_reason":"OK"});existing.append(e);remaining-=stake
    return {"daily_cap":round(daily_cap,2),"allocated":round(daily_cap-remaining,2),"remaining":round(remaining,2),"game_cap":round(game_cap,2)}

def analyze_base(g,event,delta,states,hist):
    run_state,disp_state,cal_state,skill=states;seconds=(parse_dt(g["gameDate"])-NOW).total_seconds();phase=snapshot_phase(seconds);ctx=game_context(g);quality=phase_quality(ctx,phase);hmu,amu=project_runs(ctx,run_state);engine="learned-runs" if run_state["active"] else "base-runs";extra=extra_innings_home_prob(ctx);raw=ml_prob(hmu,amu,disp_state["alpha_home"],disp_state["alpha_away"],extra);p_model=platt_predict(cal_state["model"],raw) if cal_state["active"] else raw;con=consensus(event,"h2h",ctx["home"]);p_market=con["p"];p_ensemble=p_model if p_market is None else clamp(skill["model_weight"]*p_model+(1-skill["model_weight"])*p_market);verdict=market_verdict(ctx,p_model,p_market,con,skill,hist,engine,quality);evals=[]
    _,wm=winamax_outcomes(event,"h2h")
    if wm:
        for o in wm.get("outcomes",[]):
            price=num(o.get("price"));name=o.get("name")
            if price>1:
                p=p_ensemble if norm_name(name)==norm_name(ctx["home"]) else 1-p_ensemble;evals.append(evaluate(ctx,quality,"ML",name,price,None,(p,0,1-p),consensus(event,"h2h",name)))
    _,wm=winamax_outcomes(event,"spreads")
    if wm:
        for o in wm.get("outcomes",[]):
            price=num(o.get("price"));name=o.get("name");point=num(o.get("point"))
            if price>1:evals.append(evaluate(ctx,quality,"RUNLINE",name,price,point,line_probs(hmu,amu,disp_state["alpha_home"],disp_state["alpha_away"],"RUNLINE",name,point,ctx["home"],ctx["away"]),consensus(event,"spreads",name,point)))
    _,wm=winamax_outcomes(event,"totals")
    if wm:
        for o in wm.get("outcomes",[]):
            price=num(o.get("price"));name=o.get("name");point=num(o.get("point"))
            if price>1:evals.append(evaluate(ctx,quality,"TOTAL",name,price,point,line_probs(hmu,amu,disp_state["alpha_home"],disp_state["alpha_away"],"TOTAL",name,point,ctx["home"],ctx["away"]),consensus(event,"totals",name,point)))
    return {"game":g,"game_pk":g["gamePk"],"event":event,"delta":delta,"ctx":ctx,"quality":quality,"hmu":hmu,"amu":amu,"engine":engine,"extra_home":extra,"p_model_raw":raw,"p_model":p_model,"con":con,"p_ensemble":p_ensemble,"verdict":verdict,"evals":evals,"phase":phase,"seconds":seconds}

def history_paths():return sorted(ARCHIVE_DIR.glob("*.jsonl"))+([HISTORY_FILE] if HISTORY_FILE.exists() else [])
def load_history():
    out={};bad=[]
    for path in history_paths():
        for i,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
            if not line.strip():continue
            try:r=json.loads(line);out[str(r["game_pk"])]=r
            except Exception:bad.append((path,i,line))
    if bad:
        q=HISTORY_FILE.parent/"v9_corrupt_quarantine.txt";q.write_text("\n".join(f"{p}:{i}:{line}" for p,i,line in bad),encoding="utf-8");raise RuntimeError(f"Historique V9 corrompu: {len(bad)} ligne(s); écriture bloquée")
    return out
def load_state():
    try:return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except Exception:return {}
def save_state(state):
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True);STATE_FILE.write_text(json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True);text="\n".join(json.dumps(r,ensure_ascii=False,separators=(",",":")) for r in rows)+("\n" if rows else "")
    for line in text.splitlines():json.loads(line)
    tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(text,encoding="utf-8");tmp.replace(path)
def write_history(hist):
    cutoff=NOW.astimezone(PARIS).date()-timedelta(days=ARCHIVE_AFTER_DAYS);active=[];archives={}
    for r in sorted(hist.values(),key=lambda x:(x.get("game_date",""),int(x.get("game_pk",0)))):
        try:d=parse_dt(r.get("game_date")).astimezone(PARIS).date()
        except Exception:d=NOW.astimezone(PARIS).date()
        if r.get("status")=="FINAL" and d<cutoff:
            key=d.strftime("%Y-%m");archives.setdefault(key,[]).append(r)
        else:active.append(r)
    write_jsonl(HISTORY_FILE,active);ARCHIVE_DIR.mkdir(parents=True,exist_ok=True);existing={p.stem for p in ARCHIVE_DIR.glob("*.jsonl")}
    for key,rows in archives.items():write_jsonl(ARCHIVE_DIR/f"{key}.jsonl",rows)
    for stale in existing-set(archives):
        p=ARCHIVE_DIR/f"{stale}.jsonl"
        if p.exists():p.unlink()
def ensure_record(hist,g):
    k=str(g["gamePk"])
    if k not in hist:hist[k]={"schema_version":SCHEMA_VERSION,"game_pk":g["gamePk"],"game_date":g["gameDate"],"home":g["teams"]["home"]["team"]["name"],"away":g["teams"]["away"]["team"]["name"],"status":"PENDING","snapshots":[],"recommendations":[]}
    hist[k].setdefault("snapshots",[]);hist[k].setdefault("recommendations",[]);hist[k]["game_date"]=g.get("gameDate",hist[k].get("game_date"));return hist[k]
def should_add_snapshot(rec,s):
    snaps=rec["snapshots"]
    if not snaps:return True
    last=snaps[-1]
    try:mins=(parse_dt(s["analyzed_at"])-parse_dt(last["analyzed_at"])).total_seconds()/60
    except Exception:mins=999
    if mins>=SNAPSHOT_MIN_MINUTES:return True
    keys=("market_home","p_model","p_ensemble","home_mu","away_mu","directional_pick","verdict_type","home_lineup_count","away_lineup_count","phase");return any(str(last.get(k))!=str(s.get(k)) for k in keys)
def recommendation_key(p):return f"{p['market']}|{norm_name(p['name'])}|{p.get('point')}"
def get_rec_item(rec,key):return next((x for x in rec.get("recommendations",[]) if x.get("key")==key),None)
def sync_recommendations(rec,evals,snap):
    qualified={recommendation_key(e):e for e in evals if e["qualified"]};now=snap["analyzed_at"]
    for key,e in qualified.items():
        item=get_rec_item(rec,key)
        if not item:
            item={"key":key,"market":e["market"],"name":e["name"],"point":e.get("point"),"state":"WATCH" if snap["phase"]=="EARLY" else "QUALIFIED","active":True,"first_seen":now,"price_history":[]};rec["recommendations"].append(item)
        item.update({"active":True,"last_seen":now,"latest_price":e["price"],"latest_ev":e["ev"],"latest_edge":e["edge"],"latest_phase":snap["phase"]});item.setdefault("price_history",[]).append({"at":now,"phase":snap["phase"],"price":e["price"],"ev":e["ev"],"edge":e["edge"]})
        if not item.get("published_at"):item["state"]="WATCH" if snap["phase"]=="EARLY" else "QUALIFIED"
    for item in rec.get("recommendations",[]):
        if item.get("key") in qualified:continue
        if item.get("state") in ("WATCH","QUALIFIED"):item.update({"state":"WITHDRAWN","active":False,"withdrawn_at":now})
        elif item.get("state")=="PUBLISHED" and item.get("active",True):item.update({"active":False,"withdrawn_at":now})
def mark_published(rec,selected,snap):
    for e in selected:
        key=recommendation_key(e);item=get_rec_item(rec,key)
        if not item:continue
        if not item.get("published_at"):item.update({"state":"PUBLISHED","active":True,"published_at":snap["analyzed_at"],"published_snapshot_id":snap["snapshot_id"],"published_price":e["price"],"published_units":e["units"],"published_stake_eur":e["stake_eur"],"published_ev":e["ev"],"published_edge":e["edge"]})
        else:item["state"]="PUBLISHED"
def closing_price_for(rec,item):
    snaps=[s for s in rec.get("snapshots",[]) if num(s.get("seconds_to_game"),-1)>=0];snaps.sort(key=lambda s:s.get("analyzed_at",""),reverse=True)
    for s in snaps:
        price=snapshot_price(s,item["market"],item["name"],item.get("point"))
        if price:return price,s.get("snapshot_id")
    return None,None
def settle_recommendation(item,rec,hs,as_):
    if not item.get("published_at"):
        if item.get("state")!="SETTLED":item["state"]="EXPIRED"
        return
    if item["market"]=="ML":v=(hs-as_) if norm_name(item["name"])==norm_name(rec["home"]) else (as_-hs)
    elif item["market"]=="RUNLINE":v=(hs+num(item["point"])-as_) if norm_name(item["name"])==norm_name(rec["home"]) else (as_+num(item["point"])-hs)
    else:v=(hs+as_-num(item["point"])) if str(item["name"]).lower()=="over" else (num(item["point"])-hs-as_)
    res="W" if v>1e-9 else "L" if v<-1e-9 else "P";stake=num(item.get("published_stake_eur"));price=num(item.get("published_price"));profit=round(stake*(price-1),4) if res=="W" else -round(stake,4) if res=="L" else 0.0;close,cid=closing_price_for(rec,item);item.update({"state":"SETTLED","active":False,"result":res,"profit_eur":profit,"closing_price":close,"closing_snapshot_id":cid})
    if close and price:item["clv_odds_pct"]=price/close-1;item["clv_implied_pts"]=(1/close-1/price)*100
def settle_history(hist):
    settled=0;changed=False
    for rec in hist.values():
        if rec.get("status") not in ("PENDING","POSTPONED"):continue
        feed=feed_live(rec["game_pk"],True)
        try:
            status=feed.get("gameData",{}).get("status",{});state=status.get("abstractGameState");detail=status.get("detailedState","");new_dt=feed.get("gameData",{}).get("datetime",{}).get("dateTime")
            if new_dt:rec["game_date"]=new_dt
            if state!="Final":
                if any(x in detail.lower() for x in ("postpon","cancel")):rec["status"]="POSTPONED";changed=True
                continue
            lines=feed.get("liveData",{}).get("linescore",{}).get("teams",{});hs=num(lines.get("home",{}).get("runs"),-1);as_=num(lines.get("away",{}).get("runs"),-1)
            if hs<0 or as_<0:continue
            rec.update({"status":"FINAL","home_score":int(hs),"away_score":int(as_),"home_win":1 if hs>as_ else 0,"settled_at":NOW.isoformat()});pre=[s for s in rec.get("snapshots",[]) if num(s.get("seconds_to_game"),-1)>=0]
            if pre:rec["closing_snapshot_id"]=max(pre,key=lambda s:s.get("analyzed_at",""))["snapshot_id"]
            for item in rec.get("recommendations",[]):settle_recommendation(item,rec,hs,as_)
            settled+=1;changed=True
        except Exception as e:logging.debug("Settlement %s: %s",rec.get("game_pk"),e)
    if changed:write_history(hist)
    return settled

def build_snapshot(result,rec):
    sid=f"{result['game_pk']}-{NOW.strftime('%Y%m%dT%H%M%S')}";sel=[e for e in result["evals"] if e["selected"]];qualified=[e for e in result["evals"] if e["qualified"]]
    return {"snapshot_id":sid,"feature_version":FEATURE_VERSION,"model_version":MODEL_VERSION,"verdict_version":VERDICT_VERSION,"distribution_version":DIST_VERSION,"engine_mode":result["engine"],"phase":result["phase"],"role":snapshot_role(rec,result["phase"]),"analyzed_at":NOW.isoformat(),"seconds_to_game":round(result["seconds"]),"odds_event_id":result["event"].get("id"),"odds_commence":result["event"].get("commence_time"),"match_delta_min":round(result["delta"],1),"base_home":round(result["ctx"]["base_home"],4),"base_away":round(result["ctx"]["base_away"],4),"home_mu":round(result["hmu"],4),"away_mu":round(result["amu"],4),"run_features_home":[round(x,6) for x in result["ctx"]["run_features_home"]],"run_features_away":[round(x,6) for x in result["ctx"]["run_features_away"]],"p_model_raw":round(result["p_model_raw"],6),"p_model":round(result["p_model"],6),"market_home":round(result["con"]["p"],6) if result["con"]["p"] is not None else None,"p_ensemble":round(result["p_ensemble"],6),"market_refs":result["con"]["n"],"market_disp":result["con"]["disp"],"market_age_min":result["con"]["age_min"],"quality":round(result["quality"],4),"verdict_type":result["verdict"]["type"],"directional_pick":result["verdict"]["side"],"confidence_base":round(result["verdict"]["confidence_base"],3),"direction_confidence":round(result["verdict"]["confidence"],3),"home_lineup_count":result["ctx"]["home_lineup"]["count"],"away_lineup_count":result["ctx"]["away_lineup"]["count"],"home_statcast":result["ctx"]["home_statcast"],"away_statcast":result["ctx"]["away_statcast"],"market_snapshot":serialize_market(result["event"]),"qualified_candidates":[{k:v for k,v in e.items() if k!="portfolio_reason"} for e in qualified],"selected_picks":[{k:v for k,v in e.items() if k!="portfolio_reason"} for e in sel]}
def should_publish(rec,s):
    snaps=rec.get("snapshots",[])
    if not snaps:return True
    last=snaps[-1]
    if last.get("phase")!=s.get("phase"):return True
    if last.get("directional_pick")!=s.get("directional_pick"):return True
    if abs(num(last.get("direction_confidence"))-num(s.get("direction_confidence")))>=.7:return True
    if last.get("home_lineup_count",0)<8<=s.get("home_lineup_count",0) or last.get("away_lineup_count",0)<8<=s.get("away_lineup_count",0):return True
    a={(p["market"],p["name"],p.get("point")) for p in last.get("selected_picks",[])};b={(p["market"],p["name"],p.get("point")) for p in s.get("selected_picks",[])};return a!=b

def discord_request(method="GET",payload=None):
    if not DISCORD_URL:return None,None
    data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None;req=urllib.request.Request(DISCORD_URL,data=data,headers={"User-Agent":"MLB-Betting-Bot-V9","Accept":"application/json","Content-Type":"application/json"},method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as r:return r.status,r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace");logging.error("Discord HTTP %s | %s",e.code,body[:400]);return e.code,body
    except Exception as e:logging.error("Discord: %s",e);return None,str(e)
def discord_test():
    if not DISCORD_URL:return False
    s,_=discord_request("GET");logging.info("Discord webhook %s","OK" if s==200 else f"ERREUR {s}");return s==200
def send_embed(title,fields,color):
    fs=[{"name":n[:256],"value":v[:1024],"inline":False} for n,v in fields if v];payload={"username":"MLB Betting Bot","allowed_mentions":{"parse":[]},"embeds":[{"title":title[:256],"color":color,"fields":fs,"footer":{"text":f"MLB V{VERSION} • modèle + marché • aucune garantie de gain"}}]}
    for _ in range(3):
        s,b=discord_request("POST",payload)
        if s in (200,204):time.sleep(.3);return True
        if s==429:
            try:time.sleep(max(.5,num(json.loads(b).get("retry_after"),1.5)))
            except Exception:time.sleep(1.5)
        elif s in (401,403,404):return False
    return False
def eval_text(e,phase):
    if not e:return "Cote non fournie par **Winamax via The Odds API**."
    pt=f" {e['point']:+g}" if e["point"] is not None and e["market"]=="RUNLINE" else f" {e['point']:g}" if e["point"] is not None else "";base=f"**{e['market']} — {e['name']}{pt} @ {e['price']:.2f}**\nProb {pct(e['p_cond'])} • Fair {e['fair']:.2f} • Edge {e['edge']*100:+.1f} pts • EV {e['ev']*100:+.1f}% • refs {e['refs']}"
    if e["selected"]:return base+f"\n✅ **PARI RETENU** • {e['units']:.2f}u = {e['stake_eur']:.2f} €"
    if e["qualified"] and phase=="EARLY":return base+"\n👀 **WATCHLIST EARLY** • critères passés, mais aucune mise autorisée avant LATE/FINAL"
    if e["qualified"]:return base+"\n🟠 Qualifié mais non retenu par le portefeuille • "+(e["portfolio_reason"] or "limite de risque")
    return base+"\n⚪ Non retenu • "+e["reason"]
def fmt_statcast(x):
    if not x.get("available"):return "N/A"
    return " • ".join(z for z in [f"xwOBA {x['xwoba']:.3f}" if x.get("xwoba") is not None else "",f"xSLG {x['xslg']:.3f}" if x.get("xslg") is not None else "",f"xBA {x['xba']:.3f}" if x.get("xba") is not None else ""] if z)
def representative(evals,market):
    xs=[x for x in evals if x["market"]==market];return max(xs,key=lambda z:(z["selected"],z["qualified"],z["ev"])) if xs else None
def send_game(result,snap,portfolio):
    ctx=result["ctx"];v=result["verdict"];emoji,label,color=confidence_band(v["confidence"]);disp=result["disp_state"];probs=f"Modèle indépendant **{ctx['home']} {pct(result['p_model'])}** • {ctx['away']} {pct(1-result['p_model'])}\nMarché **{pct(result['con']['p'])} {ctx['home']}** ({result['con']['n']} books) • ensemble {pct(result['p_ensemble'])}\nProjection: **{ctx['home']} {result['hmu']:.2f} – {result['amu']:.2f} {ctx['away']}** • total {result['hmu']+result['amu']:.2f}\nNB α H/A={disp['alpha_home']:.2f}/{disp['alpha_away']:.2f} • extras domicile {pct(result['extra_home'])} • phase **{result['phase']}** / {snap['role']}";direction=v["text"]+f"\n{emoji} Confiance: **{v['confidence']:.1f}/10 — {label}**"+(f" • historique comparable n={v['emp_n']}" if v["emp_n"] else "");starters=f"{ctx['away']}: **{ctx['away_sp']}** • {pitcher_line(ctx['away_sp_stats'],ctx['away_hand'])}\n{ctx['home']}: **{ctx['home_sp']}** • {pitcher_line(ctx['home_sp_stats'],ctx['home_hand'])}";advanced=f"Lineups H/A: **{ctx['home_lineup']['count']}/9 – {ctx['away_lineup']['count']}/9** • OPS pondéré {ctx['home_lineup']['weighted_ops'] if ctx['home_lineup']['weighted_ops'] else 'N/A'} / {ctx['away_lineup']['weighted_ops'] if ctx['away_lineup']['weighted_ops'] else 'N/A'}\nSplits vs main opposée PA: {int(num(ctx['home_split'].get('_pa')))} / {int(num(ctx['away_split'].get('_pa')))}\nStatcast {ctx['home']}: {fmt_statcast(ctx['home_statcast'])}\nStatcast {ctx['away']}: {fmt_statcast(ctx['away_statcast'])}\nBullpen ERA H/A: {ctx['home_bp']['era']:.2f}/{ctx['away_bp']['era']:.2f} • fatigue {ctx['home_bp']['load']:.2f}/{ctx['away_bp']['load']:.2f}";context=f"Park {ctx['park']:.3f} • météo: {ctx['weather']['text']}\nForme 10: {ctx['home']} {ctx['home_recent']['win_pct']*100:.0f}% (RD {ctx['home_recent']['run_diff_pg']:+.2f}/g) • {ctx['away']} {ctx['away_recent']['win_pct']*100:.0f}% (RD {ctx['away_recent']['run_diff_pg']:+.2f}/g)\nQualité adaptée à la phase: **{result['quality']*10:.1f}/10**";markets="\n\n".join(eval_text(representative(result["evals"],m),result["phase"]) for m in ("ML","RUNLINE","TOTAL"));selected=[e for e in result["evals"] if e["selected"]];final="\n".join(f"• **{e['market']} {e['name']} {e['point'] if e['point'] is not None else ''} @ {e['price']:.2f}** • {e['units']:.2f}u" for e in selected[:3]) if selected else (f"👀 Watchlist seulement — **aucune mise en phase EARLY**. Pick directionnel: **{v['side']}**." if result["phase"]=="EARLY" else f"Pick directionnel: **{v['side']}**. Aucun prix ne passe le portefeuille de risque.");risk=f"Exposition journée: **{portfolio['allocated']:.2f} € / {portfolio['daily_cap']:.2f} €** • plafond/match {portfolio['game_cap']:.2f} €"
    return send_embed(f"⚾ MLB V{VERSION} • {ctx['away']} @ {ctx['home']}",[("🕒 Match",local_time(result["game"]["gameDate"])+" (Paris)"),("🎯 Probabilités",probs),("🧭 Lecture du marché",direction),("🧑 Starters",starters),("🧪 Lineup / splits / Statcast / bullpen",advanced),("🔬 Contexte",context),("💰 Winamax — prix",markets),("🛡️ Risque portefeuille",risk),("✅ Verdict",final)],color)

def top_signature(results):
    payload=[]
    for r in sorted(results,key=lambda x:str(x["game_pk"])):payload.append([r["game_pk"],r["verdict"]["side"],round(r["verdict"]["confidence"],1),[(e["market"],e["name"],e.get("point"),round(e["price"],2),e["selected"],e["qualified"]) for e in r["evals"]]])
    return hashlib.sha1(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def send_top_messages(results,state):
    sig=top_signature(results)
    if state.get("top_signature")==sig:logging.info("Top 3 inchangé — Discord non renvoyé");return False
    dirs=sorted([r for r in results if r["verdict"]["type"]!="UNCERTAIN"],key=lambda r:r["verdict"]["confidence"],reverse=True)[:3];body="\n\n".join(f"**#{i+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{confidence_band(r['verdict']['confidence'])[0]} **{r['verdict']['side']}** • {r['verdict']['confidence']:.1f}/10 • {confidence_band(r['verdict']['confidence'])[1]} • phase {r['phase']}" for i,r in enumerate(dirs)) or "Aucune lecture claire.";ok=send_embed("🏆 TOP 3 LECTURES MONEYLINE",[("Direction",body)],16766720)
    for market,title in (("RUNLINE","⚾ TOP 3 RUN LINE"),("TOTAL","📈 TOP 3 TOTAUX")):
        xs=[]
        for r in results:
            for e in r["evals"]:
                if e["market"]==market and e["qualified"]:xs.append((r,e))
        xs=sorted(xs,key=lambda x:(x[1]["selected"],x[1]["ev"]),reverse=True)[:3];txt="\n\n".join(f"**#{i+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{e['name']} {e['point']} @ **{e['price']:.2f}** • EV {e['ev']*100:+.1f}% • {'✅ '+str(e['units'])+'u' if e['selected'] else '👀 watch/qualifié'}" for i,(r,e) in enumerate(xs)) if xs else "Aucun prix qualifié.";ok=send_embed(title,[("Sélection V9",txt)],16766720) and ok
    if ok:state["top_signature"]=sig;save_state(state)
    return ok

def performance(hist):
    rows=[];bets=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if s:
            y=int(r.get("home_win",0));pick=s.get("directional_pick");correct=(norm_name(pick)==norm_name(r["home"]) and y==1) or (norm_name(pick)==norm_name(r["away"]) and y==0) if pick else None;rows.append((s,y,correct))
        bets += [p for p in r.get("recommendations",[]) if p.get("state")=="SETTLED" and p.get("published_at")]
    ys=[y for _,y,_ in rows];market_rows_=[(s,y) for s,y,_ in rows if s.get("market_home") is not None];out={"games":len(rows),"direction":mean([c for _,_,c in rows if c is not None]) if rows else None,"brier_model":brier([num(s.get("p_model"),.5) for s,_,_ in rows],ys) if rows else None,"brier_market":brier([num(s.get("market_home"),.5) for s,y in market_rows_],[y for s,y in market_rows_]) if market_rows_ else None,"bets":len(bets)};profit=sum(num(p.get("profit_eur")) for p in bets);stake=sum(num(p.get("published_stake_eur")) for p in bets if p.get("result")!="P");clv=[num(p.get("clv_implied_pts")) for p in bets if p.get("clv_implied_pts") is not None];out.update({"profit":profit,"roi":profit/stake if stake else None,"clv_pts":mean(clv) if clv else None,"clv_n":len(clv)});return out

def self_test():
    assert abs(sum(nb_pmf(4.5,.12))-1)<1e-8
    w,p,l=line_probs(4.5,4.0,.12,.12,"TOTAL","Over",8,"H","A");assert p>0 and abs(w+p+l-1)<1e-8
    a={"market":"ML","name":"A","point":None,"price":2.0};b=dict(a);b["price"]=1.9;assert recommendation_key(a)==recommendation_key(b)
    assert snapshot_phase(8*3600)=="EARLY" and snapshot_phase(4*3600)=="LATE" and snapshot_phase(2*3600)=="FINAL"
    games=[{"gamePk":1,"gameDate":"2026-08-11T17:00:00Z","teams":{"away":{"team":{"name":"A"}},"home":{"team":{"name":"B"}}}},{"gamePk":2,"gameDate":"2026-08-11T22:00:00Z","teams":{"away":{"team":{"name":"A"}},"home":{"team":{"name":"B"}}}}];ev=[{"id":"x","away_team":"A","home_team":"B","commence_time":"2026-08-11T17:05:00Z"},{"id":"y","away_team":"A","home_team":"B","commence_time":"2026-08-11T22:02:00Z"}];m=match_odds_events(games,ev);assert m["1"][0]["id"]=="x" and m["2"][0]["id"]=="y"
    snap={"market_snapshot":[{"book":"winamax_fr","markets":[{"key":"h2h","outcomes":[{"name":"A","price":2.05,"point":None},{"name":"B","price":1.80,"point":None}]}]}]};assert snapshot_price(snap,"ML","A")==2.05
    early={"game_pk":1,"phase":"EARLY","evals":[{"qualified":True,"ev":.1,"quality":.9,"edge":.05,"candidate_stake_eur":1.0,"candidate_units":2,"selected":False,"units":0,"stake_eur":0,"portfolio_reason":"","market":"ML","name":"A"}]};allocate_portfolio([early]);assert not early["evals"][0]["selected"]
    late={"game_pk":2,"phase":"FINAL","evals":[{"qualified":True,"ev":.1,"quality":.9,"edge":.05,"candidate_stake_eur":1.5,"candidate_units":3,"selected":False,"units":0,"stake_eur":0,"portfolio_reason":"","market":"ML","name":"A"}]};port=allocate_portfolio([late]);assert late["evals"][0]["selected"] and port["allocated"]<=BANKROLL*MAX_DAILY_EXPOSURE_PCT+.001
    print("SELF-TEST V9 OK")

def main():
    logging.info("="*68);logging.info("MLB BETTING BOT V%s | date MLB=%s",VERSION,TARGET_DATE);logging.info("="*68)
    if not ODDS_KEY:raise SystemExit("ODDS_API_KEY absente")
    discord_ok=discord_test();hist=load_history();state=load_state();settled=settle_history(hist);run_state=run_model_state(hist);disp_state=dispersion_state(hist);engine="learned-runs" if run_state["active"] else "base-runs";cal_state=calibration_state(hist,engine);skill=skill_state(hist,engine);states=(run_state,disp_state,cal_state,skill);logging.info("Historique V9 | %d matchs | réglés=%d",len(hist),settled);logging.info("Run ML n=%d actif=%s RMSE %.3f/%.3f gainProb=%.2f folds=%d",run_state["n"],run_state["active"],num(run_state["rmse_model"]),num(run_state["rmse_base"]),run_state["gain_prob"],run_state["folds"]);logging.info("NB alpha H/A %.2f/%.2f learned=%s n=%d | calibration n=%d active=%s gainProb=%.2f | skill n=%d poids modèle=%.2f",disp_state["alpha_home"],disp_state["alpha_away"],disp_state["learned"],disp_state["n"],cal_state["n"],cal_state["active"],cal_state["gain_prob"],skill["n"],skill["model_weight"])
    savant_league();games=mlb_schedule(TARGET_DATE);events=odds_api();matches=match_odds_events(games,events);logging.info("MLB=%d odds=%d appariés=%d",len(games),len(events),len(matches));results=[]
    for g in games:
        if parse_dt(g["gameDate"])<=NOW:continue
        pair=matches.get(str(g["gamePk"]))
        if not pair:logging.warning("Odds non appariées: %s @ %s",g["teams"]["away"]["team"]["name"],g["teams"]["home"]["team"]["name"]);continue
        try:r=analyze_base(g,pair[0],pair[1],states,hist);r["disp_state"]=disp_state;results.append(r)
        except Exception as e:logging.exception("Analyse %s: %s",g.get("gamePk"),e)
    portfolio=allocate_portfolio(results);published=0
    for r in results:
        rec=ensure_record(hist,r["game"]);snap=build_snapshot(r,rec);publish=should_publish(rec,snap);added=should_add_snapshot(rec,snap)
        if added:rec["snapshots"].append(snap)
        sync_recommendations(rec,r["evals"],snap);sent=False
        if discord_ok and publish:sent=send_game(r,snap,portfolio)
        if sent:mark_published(rec,[e for e in r["evals"] if e["selected"]],snap);published+=1
        logging.info("%s @ %s | %s %s | lineups=%d/%d statcast=%s/%s | %s %s %.1f/10 | qualified=%d bets=%d%s",r["ctx"]["away"],r["ctx"]["home"],r["phase"],snap["role"],r["ctx"]["home_lineup"]["count"],r["ctx"]["away_lineup"]["count"],r["ctx"]["home_statcast"]["available"],r["ctx"]["away_statcast"]["available"],r["verdict"]["type"],r["verdict"]["side"],r["verdict"]["confidence"],sum(e["qualified"] for e in r["evals"]),sum(e["selected"] for e in r["evals"])," | Discord update" if sent else "")
    write_history(hist)
    if discord_ok and results:send_top_messages(results,state)
    perf=performance(hist);logging.info("V%s terminé | analyses=%d | messages=%d | exposition=%.2f/%.2f€ | snapshots=%d",VERSION,len(results),published,portfolio["allocated"],portfolio["daily_cap"],sum(len(r.get("snapshots",[])) for r in hist.values()));logging.info("Performance | games=%d direction=%s Brier modèle=%s marché=%s | bets=%d profit=%.2f€ ROI=%s | CLV=%s pts n=%d",perf["games"],pct(perf["direction"]) if perf["direction"] is not None else "-",f"{perf['brier_model']:.4f}" if perf["brier_model"] is not None else "-",f"{perf['brier_market']:.4f}" if perf["brier_market"] is not None else "-",perf["bets"],perf["profit"],pct(perf["roi"]) if perf["roi"] is not None else "-",f"{perf['clv_pts']:+.2f}" if perf["clv_pts"] is not None else "-",perf["clv_n"])

if __name__=="__main__":
    try:
        if "--self-test" in sys.argv:self_test()
        else:main()
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception:logging.exception("ERREUR FATALE");raise
