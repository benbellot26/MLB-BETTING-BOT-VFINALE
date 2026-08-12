#!/usr/bin/env python3
import os, sys, json, math, time, logging, urllib.request, urllib.parse, urllib.error, re, hashlib, random
from datetime import datetime, timezone, timedelta
from statistics import median, mean, pstdev
from pathlib import Path
from zoneinfo import ZoneInfo
from html.parser import HTMLParser

VERSION="9.1.1"
SCHEMA_VERSION=9
FEATURE_VERSION="9.0.3"
MODEL_VERSION="runs-residual-walkforward-v3"
VERDICT_VERSION="direction-calibrated-v3"
DIST_VERSION="nb-mle-split-v2"
RECOMMENDATION_VERSION="model-first-v1"
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
    max_u=max(0,int(math.floor(MAX_STAKE_UNITS+1e-9)))
    u=min(max_u,int(math.floor(max(0.0,eur)/UNIT+1e-9)))
    return (float(u),round(u*UNIT,2)) if u>=1 else (0.0,0.0)
def integer_stake_units(eur):
    if UNIT<=0:return 0.0,0.0
    raw=max(0.0,eur)/UNIT;max_u=max(0,int(math.floor(MAX_STAKE_UNITS+1e-9)))
    if raw<.25 or max_u<1:return 0.0,0.0
    u=1 if raw<1.5 else 2 if raw<2.5 else 3;u=min(u,max_u)
    return float(u),round(u*UNIT,2)

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
SAVANT_TEAM_NAMES={
    "angels":"Los Angeles Angels","astros":"Houston Astros","athletics":"Athletics","bluejays":"Toronto Blue Jays",
    "braves":"Atlanta Braves","brewers":"Milwaukee Brewers","cardinals":"St. Louis Cardinals","cubs":"Chicago Cubs",
    "dbacks":"Arizona Diamondbacks","diamondbacks":"Arizona Diamondbacks","dodgers":"Los Angeles Dodgers","giants":"San Francisco Giants",
    "guardians":"Cleveland Guardians","mariners":"Seattle Mariners","marlins":"Miami Marlins","mets":"New York Mets",
    "nationals":"Washington Nationals","orioles":"Baltimore Orioles","padres":"San Diego Padres","phillies":"Philadelphia Phillies",
    "pirates":"Pittsburgh Pirates","rangers":"Texas Rangers","rays":"Tampa Bay Rays","reds":"Cincinnati Reds",
    "redsox":"Boston Red Sox","rockies":"Colorado Rockies","royals":"Kansas City Royals","tigers":"Detroit Tigers",
    "twins":"Minnesota Twins","whitesox":"Chicago White Sox","yankees":"New York Yankees"
}
SAVANT_TEAM_IDS={108:"Los Angeles Angels",109:"Arizona Diamondbacks",110:"Baltimore Orioles",111:"Boston Red Sox",112:"Chicago Cubs",113:"Cincinnati Reds",114:"Cleveland Guardians",115:"Colorado Rockies",116:"Detroit Tigers",117:"Houston Astros",118:"Kansas City Royals",119:"Los Angeles Dodgers",120:"Washington Nationals",121:"New York Mets",133:"Athletics",134:"Pittsburgh Pirates",135:"San Diego Padres",136:"Seattle Mariners",137:"San Francisco Giants",138:"St. Louis Cardinals",139:"Tampa Bay Rays",140:"Texas Rangers",141:"Toronto Blue Jays",142:"Minnesota Twins",143:"Philadelphia Phillies",144:"Atlanta Braves",145:"Chicago White Sox",146:"Miami Marlins",147:"New York Yankees",158:"Milwaukee Brewers"}
def _savant_empty():
    return {name:{"xwoba":None,"xslg":None,"xba":None,"pa":0,"available":False,"source":"Baseball Savant Expected Statistics"} for name in TEAM_KEYS}
def _savant_team_name(cell):
    raw=str(cell or "").strip();n=norm_name(raw)
    if n in SAVANT_TEAM_NAMES:return SAVANT_TEAM_NAMES[n]
    try:
        tid=int(float(raw))
        if tid in SAVANT_TEAM_IDS:return SAVANT_TEAM_IDS[tid]
    except Exception:pass
    tokens=set(re.findall(r"[A-Z]{2,3}",raw.upper()))
    for name,keys in TEAM_KEYS.items():
        if n==norm_name(name) or any(k in tokens for k in keys):return name
    return None
def _savant_get(row,*aliases):
    for alias in aliases:
        k=_header_key(alias)
        if k in row and str(row[k]).strip()!="":return row[k]
    return None
def _savant_apply_row(result,row):
    team_cell=_savant_get(row,"team_name","team","team_name_alt","last_name","team_abbr","teamabbr","team_abbreviation","abbreviation")
    team=_savant_team_name(team_cell)
    if not team:
        team=_savant_team_name(_savant_get(row,"team_id","teamid"))
    if not team:return False
    xba=_fnum(_savant_get(row,"est_ba","xba","x_ba","estimated_ba","expected_batting_average"))
    xslg=_fnum(_savant_get(row,"est_slg","xslg","x_slg","estimated_slg","expected_slugging"))
    xwoba=_fnum(_savant_get(row,"est_woba","xwoba","x_woba","estimated_woba","expected_woba"))
    pa=int(_fnum(_savant_get(row,"pa","plate_appearances","plateappearances")) or 0)
    if not all(v is not None for v in (xba,xslg,xwoba)):return False
    result[team]={"xwoba":xwoba,"xslg":xslg,"xba":xba,"pa":pa,"available":True,"source":"Baseball Savant Expected Statistics"}
    return True
def _savant_parse_csv(raw,result):
    csv_mod=__import__('csv');io_mod=__import__('io');text=raw.decode('utf-8-sig','replace')
    if ',' not in text[:1000]:return 0,0,[],[]
    reader=csv_mod.DictReader(io_mod.StringIO(text));recognized=total=0;samples=[];headers=[]
    if reader.fieldnames:headers=[_header_key(x) for x in reader.fieldnames]
    for original in reader:
        total+=1;row={_header_key(k):v for k,v in original.items() if k is not None}
        if len(samples)<5:samples.append(str(_savant_get(row,"team_name","team","last_name","team_id","abbreviation")))
        recognized+=int(_savant_apply_row(result,row))
    return recognized,total,headers,samples
def savant_league():
    key=("savant_league",SEASON,"v9.0.2")
    if key in _CACHE:return _CACHE[key]
    result=_savant_empty();base="https://baseballsavant.mlb.com/leaderboard/expected_statistics";params={"type":"batter-team","year":SEASON,"position":"","team":"","csv":"true"}
    try:
        raw,hdr=http_raw(base,params,headers={"Accept":"text/csv,text/plain,*/*","Referer":"https://baseballsavant.mlb.com/"})
        recognized,total,headers,samples=_savant_parse_csv(raw,result)
        available=sum(1 for v in result.values() if v.get("available"))
        logging.info("Baseball Savant CSV | bytes=%d type=%s total=%d reconnus=%d valides=%d",len(raw),hdr.get("content-type","?"),total,recognized,available)
        logging.info("Baseball Savant CSV | headers=%s | samples=%s",",".join(headers[:12]),samples)
        if available<20:logging.warning("Statcast incomplet: %d équipes valides sur 30; données absentes neutralisées",available)
    except Exception as e:
        logging.warning("Baseball Savant CSV indisponible: %s",e)
    _CACHE[key]=result;return result
def savant_team(team_name):return savant_league().get(team_name,{"xwoba":None,"xslg":None,"xba":None,"pa":0,"available":False,"source":"Baseball Savant Expected Statistics"})

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
    p=pw/np;b=price-1;k=max(0,(p*price-1)/b);eur=min(BANKROLL*k*.25,UNIT*MAX_STAKE_UNITS);return integer_stake_units(eur)
def min_acceptable_price(pw,pp,pl):
    nonpush=pw+pl
    if pw<=0 or nonpush<=0:return None
    pcond=pw/nonpush
    ev_price=(1+MIN_EV-pp)/pw
    edge_price=1/(pcond-MIN_EDGE) if pcond>MIN_EDGE else 99.0
    return max((1-pp)/pw,ev_price,edge_price)
def evaluate(ctx,quality,kind,name,price,point,model_tuple,cons):
    pw,pp,pl=model_tuple
    nonpush=pw+pl;pcond=pw/nonpush if nonpush else .5
    edge=pcond-1/price;ev=pw*price+pp-1;fair=(1-pp)/pw if pw>0 else 99;reasons=[]
    if quality<MIN_QUALITY:reasons.append(f"qualité {quality*10:.1f}/10 < {MIN_QUALITY*10:.1f}")
    if edge<MIN_EDGE:reasons.append(f"prix: edge {edge*100:+.1f} pts < {MIN_EDGE*100:.1f}")
    if ev<MIN_EV:reasons.append(f"prix: EV {ev*100:+.1f}% < {MIN_EV*100:.1f}%")
    cu,cs=stake_candidate(pw,pp,pl,price)
    if not reasons and cu<=0:reasons.append("Kelly prudent < 0.25u")
    return {"market":kind,"name":name,"point":point,"price":price,"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":pcond,"fair":fair,"min_price":min_acceptable_price(pw,pp,pl),"edge":edge,"ev":ev,"quality":quality,"refs":cons.get("n",0),"market_prob":cons.get("p"),"qualified":not reasons,"reason":"OK" if not reasons else " ; ".join(reasons),"candidate_units":cu,"candidate_stake_eur":cs,"selected":False,"units":0.0,"stake_eur":0.0,"portfolio_reason":"","model_recommended":False}

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
def model_signal_confidence(p_model,quality,p_market=None,refs=0):
    strength=max(0,p_model-.5)
    gap=abs(p_model-p_market) if p_market is not None else 0
    return clamp(4.4+min(2.9,strength/.18*2.9)+max(0,quality-.55)*2.0+min(1.0,gap/.12)+min(.4,max(0,refs-2)*.10),4.2,9.6)
def winamax_eval_for(result,market,name,point=None):
    for e in result.get("evals",[]):
        if e.get("market")!=market:continue
        same=(str(e.get("name")).lower()==str(name).lower()) if market=="TOTAL" else (norm_name(e.get("name"))==norm_name(name))
        line=True if point is None else abs(num(e.get("point"))-num(point))<1e-6
        if same and line:return e
    return None
def model_line_views(result,market):
    mk="spreads" if market=="RUNLINE" else "totals"
    candidates={}
    for b,m in market_rows(result["event"],mk):
        if b.get("key") not in REF_BOOKS:continue
        for o in m.get("outcomes",[]):
            if o.get("point") is None:continue
            name=o.get("name");point=round(num(o.get("point")),3)
            key=(norm_name(name),point) if market=="RUNLINE" else (str(name).lower(),point)
            candidates[key]=(name,point)
    views=[]
    for name,point in candidates.values():
        con=consensus(result["event"],mk,name,point)
        probs=line_probs(result["hmu"],result["amu"],result["disp_state"]["alpha_home"],result["disp_state"]["alpha_away"],market,name,point,result["ctx"]["home"],result["ctx"]["away"])
        pw,pp,pl=probs;nonpush=pw+pl
        if nonpush<=0:continue
        pm=pw/nonpush
        if pm<.50:continue
        mp=con.get("p");market_gap=pm-mp if mp is not None else None
        conf=model_signal_confidence(pm,result["quality"],mp,con.get("n",0))
        we=winamax_eval_for(result,market,name,point)
        views.append({"market":market,"name":name,"point":point,"p_model":pm,"p_win":pw,"p_push":pp,"p_loss":pl,"p_market":mp,"market_gap":market_gap,"refs":con.get("n",0),"fair":(1-pp)/pw if pw>0 else 99,"min_price":min_acceptable_price(pw,pp,pl),"confidence":conf,"winamax_eval":we})
    return views
def best_model_line(result,market):
    xs=model_line_views(result,market)
    if not xs:return None
    return max(xs,key=lambda v:(v["confidence"]+(max(0,v["market_gap"] or 0)*8),v["p_model"],v["refs"]))
def attach_model_recommendations(result):
    home=result["ctx"]["home"];away=result["ctx"]["away"]
    side=home if result["p_model"]>=.5 else away
    pm=result["p_model"] if side==home else 1-result["p_model"]
    mp=None if result["con"].get("p") is None else (result["con"]["p"] if side==home else 1-result["con"]["p"])
    ml_eval=winamax_eval_for(result,"ML",side,None)
    ml={"market":"ML","name":side,"point":None,"p_model":pm,"p_win":pm,"p_push":0.0,"p_loss":1-pm,"p_market":mp,"market_gap":pm-mp if mp is not None else None,"refs":result["con"].get("n",0),"fair":1/pm,"min_price":min_acceptable_price(pm,0,1-pm),"confidence":model_signal_confidence(pm,result["quality"],mp,result["con"].get("n",0)),"winamax_eval":ml_eval}
    recs={"ML":ml,"RUNLINE":best_model_line(result,"RUNLINE"),"TOTAL":best_model_line(result,"TOTAL")}
    result["model_recs"]=recs
    for e in result.get("evals",[]):e["model_recommended"]=False
    for rec in recs.values():
        if rec and rec.get("winamax_eval") is not None:rec["winamax_eval"]["model_recommended"]=True
    return recs
def model_rec_payload(rec):
    if not rec:return None
    return {k:v for k,v in rec.items() if k!="winamax_eval"}
def displayed_stake_units(rec):
    c=num((rec or {}).get("confidence"),0)
    max_u=max(0,int(math.floor(MAX_STAKE_UNITS+1e-9)))
    if c<MIN_PLAN_CONF or max_u<1:return 0
    u=1 if c<7.0 else 2 if c<8.0 else 3
    return min(u,max_u)
def execution_status(rec,phase):
    if not rec:return "⚠️ Pas de recommandation modèle exploitable."
    e=rec.get("winamax_eval");minimum=rec.get("min_price");du=displayed_stake_units(rec);ds=round(du*UNIT,2)
    phase_txt=f" • phase {phase}" if phase else ""
    stake_txt=(f"💰 **Mise recommandée : {du}u = {ds:.2f} €**" if du>0 else f"💰 **Mise recommandée : 0u** • confiance sous le seuil {MIN_PLAN_CONF:.1f}/10")
    if not e:
        return f"ℹ️ **Winamax : cote absente du flux** • cote mini indicative **{minimum:.2f}**{phase_txt}\n{stake_txt} • unité basée uniquement sur la confiance modèle"
    price=num(e.get("price"),0)
    price_txt=(f"ℹ️ **Winamax {price:.2f}** • cote mini indicative **{minimum:.2f}**" if price+1e-9>=minimum else f"⚠️ **Winamax {price:.2f} sous la cote mini indicative {minimum:.2f}**")
    return f"{price_txt}{phase_txt}\n{stake_txt} • unité basée uniquement sur la confiance modèle"
def model_rec_text(rec):
    if not rec:return "Aucune recommandation modèle suffisamment définie."
    market=rec["market"];pt=""
    if rec.get("point") is not None:pt=(f" {rec['point']:+g}" if market=="RUNLINE" else f" {rec['point']:g}")
    market_txt=pct(rec.get("p_market")) if rec.get("p_market") is not None else "N/A"
    gap=f"{rec['market_gap']*100:+.1f} pts" if rec.get("market_gap") is not None else "N/A"
    emoji,band,_=confidence_band(rec["confidence"])
    return f"**{rec['name']}{pt}** • modèle **{pct(rec['p_model'])}** • marché réf. {market_txt} • écart {gap}\nFair **{rec['fair']:.2f}** • cote mini **{rec['min_price']:.2f}** • {emoji} **{rec['confidence']:.1f}/10 — {band}**"

def allocate_portfolio(results):
    daily_cap=BANKROLL*MAX_DAILY_EXPOSURE_PCT;game_cap=BANKROLL*MAX_GAME_EXPOSURE_PCT;remaining=daily_cap;chosen={};candidates=[]
    for r in results:
        if r["phase"]=="EARLY":
            for e in r["evals"]:
                if e.get("qualified") and e.get("model_recommended"):e["portfolio_reason"]="WATCHLIST EARLY — aucune mise autorisée"
            continue
        for e in r["evals"]:
            if e.get("qualified") and e.get("model_recommended"):candidates.append((e["ev"]*e["quality"]+max(0,e["edge"])*.5,r,e))
    for _,r,e in sorted(candidates,key=lambda x:x[0],reverse=True):
        gid=str(r["game_pk"]);existing=chosen.setdefault(gid,[])
        if len(existing)>=MAX_BETS_PER_GAME:e["portfolio_reason"]="limite de paris par match";continue
        used=sum(x["stake_eur"] for x in existing);room_game=max(0,game_cap-used)
        if remaining<=0:e["portfolio_reason"]="exposition quotidienne maximale atteinte";continue
        f=correlation_factor(existing,e);target=min(e["candidate_stake_eur"]*f,remaining,room_game);u,stake=round_down_units(target)
        if u<1:e["portfolio_reason"]="mise réduite sous 1u par contrôle portefeuille";continue
        e.update({"selected":True,"units":u,"stake_eur":stake,"portfolio_reason":"OK"});existing.append(e);remaining-=stake
    return {"daily_cap":round(daily_cap,2),"allocated":round(daily_cap-remaining,2),"remaining":round(remaining,2),"game_cap":round(game_cap,2)}

def analyze_base(g,event,delta,states,hist):
    run_state,disp_state,cal_state,skill=states;seconds=(parse_dt(g["gameDate"])-NOW).total_seconds();phase=snapshot_phase(seconds);ctx=game_context(g);quality=phase_quality(ctx,phase);hmu,amu=project_runs(ctx,run_state);engine="learned-runs" if run_state["active"] else "base-runs";extra=extra_innings_home_prob(ctx);raw=ml_prob(hmu,amu,disp_state["alpha_home"],disp_state["alpha_away"],extra);p_model=platt_predict(cal_state["model"],raw) if cal_state["active"] else raw;con=consensus(event,"h2h",ctx["home"]);p_market=con["p"];p_ensemble=p_model if p_market is None else clamp(skill["model_weight"]*p_model+(1-skill["model_weight"])*p_market);verdict=market_verdict(ctx,p_model,p_market,con,skill,hist,engine,quality);evals=[]
    _,wm=winamax_outcomes(event,"h2h")
    if wm:
        for o in wm.get("outcomes",[]):
            price=num(o.get("price"));name=o.get("name")
            if price>1:
                p=p_model if norm_name(name)==norm_name(ctx["home"]) else 1-p_model;evals.append(evaluate(ctx,quality,"ML",name,price,None,(p,0,1-p),consensus(event,"h2h",name)))
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
    qualified={recommendation_key(e):e for e in evals if e.get("qualified") and e.get("model_recommended")};now=snap["analyzed_at"]
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
    sid=f"{result['game_pk']}-{NOW.strftime('%Y%m%dT%H%M%S')}";sel=[e for e in result["evals"] if e.get("selected")];qualified=[e for e in result["evals"] if e.get("qualified") and e.get("model_recommended")]
    return {"snapshot_id":sid,"feature_version":FEATURE_VERSION,"model_version":MODEL_VERSION,"verdict_version":VERDICT_VERSION,"distribution_version":DIST_VERSION,"recommendation_version":RECOMMENDATION_VERSION,"engine_mode":result["engine"],"phase":result["phase"],"role":snapshot_role(rec,result["phase"]),"analyzed_at":NOW.isoformat(),"seconds_to_game":round(result["seconds"]),"odds_event_id":result["event"].get("id"),"odds_commence":result["event"].get("commence_time"),"match_delta_min":round(result["delta"],1),"base_home":round(result["ctx"]["base_home"],4),"base_away":round(result["ctx"]["base_away"],4),"home_mu":round(result["hmu"],4),"away_mu":round(result["amu"],4),"run_features_home":[round(x,6) for x in result["ctx"]["run_features_home"]],"run_features_away":[round(x,6) for x in result["ctx"]["run_features_away"]],"p_model_raw":round(result["p_model_raw"],6),"p_model":round(result["p_model"],6),"market_home":round(result["con"]["p"],6) if result["con"]["p"] is not None else None,"p_ensemble":round(result["p_ensemble"],6),"market_refs":result["con"]["n"],"market_disp":result["con"]["disp"],"market_age_min":result["con"]["age_min"],"quality":round(result["quality"],4),"verdict_type":result["verdict"]["type"],"directional_pick":result["verdict"]["side"],"confidence_base":round(result["verdict"]["confidence_base"],3),"direction_confidence":round(result["verdict"]["confidence"],3),"home_lineup_count":result["ctx"]["home_lineup"]["count"],"away_lineup_count":result["ctx"]["away_lineup"]["count"],"home_statcast":result["ctx"]["home_statcast"],"away_statcast":result["ctx"]["away_statcast"],"model_recommendations":{k:model_rec_payload(v) for k,v in result.get("model_recs",{}).items()},"market_snapshot":serialize_market(result["event"]),"qualified_candidates":[{k:v for k,v in e.items() if k not in ("portfolio_reason",)} for e in qualified],"selected_picks":[{k:v for k,v in e.items() if k not in ("portfolio_reason",)} for e in sel]}

def should_publish(rec,s):
    snaps=rec.get("snapshots",[])
    if not snaps:return True
    last=snaps[-1]
    if last.get("feature_version")!=s.get("feature_version"):return True
    if last.get("phase")!=s.get("phase"):return True
    if last.get("directional_pick")!=s.get("directional_pick"):return True
    if abs(num(last.get("direction_confidence"))-num(s.get("direction_confidence")))>=.7:return True
    if last.get("home_lineup_count",0)<8<=s.get("home_lineup_count",0) or last.get("away_lineup_count",0)<8<=s.get("away_lineup_count",0):return True
    last_h=bool((last.get("home_statcast") or {}).get("available"));new_h=bool((s.get("home_statcast") or {}).get("available"))
    last_a=bool((last.get("away_statcast") or {}).get("available"));new_a=bool((s.get("away_statcast") or {}).get("available"))
    if (not last_h and new_h) or (not last_a and new_a):return True
    a={(p["market"],p["name"],p.get("point")) for p in last.get("selected_picks",[])}
    b={(p["market"],p["name"],p.get("point")) for p in s.get("selected_picks",[])}
    return a!=b

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
    if e["selected"]:return base+f"\n✅ **PARI RETENU** • {int(num(e['units'],0))}u = {e['stake_eur']:.2f} €"
    if e["qualified"] and phase=="EARLY":return base+"\n👀 **WATCHLIST EARLY** • critères passés, mais aucune mise autorisée avant LATE/FINAL"
    if e["qualified"]:return base+"\n🟠 Qualifié mais non retenu par le portefeuille • "+(e["portfolio_reason"] or "limite de risque")
    return base+"\n⚪ Non retenu • "+e["reason"]
def fmt_statcast(x):
    if not x.get("available"):return "N/A"
    return " • ".join(z for z in [f"xwOBA {x['xwoba']:.3f}" if x.get("xwoba") is not None else "",f"xSLG {x['xslg']:.3f}" if x.get("xslg") is not None else "",f"xBA {x['xba']:.3f}" if x.get("xba") is not None else ""] if z)
def representative(evals,market):
    xs=[x for x in evals if x["market"]==market];return max(xs,key=lambda z:(z["selected"],z["qualified"],z["ev"])) if xs else None
def send_game(result,snap,portfolio):
    ctx=result["ctx"];v=result["verdict"];emoji,label,color=confidence_band(v["confidence"]);disp=result["disp_state"];recs=result.get("model_recs",{})
    probs=f"Modèle indépendant **{ctx['home']} {pct(result['p_model'])}** • {ctx['away']} {pct(1-result['p_model'])}\nMarché de référence **{pct(result['con']['p'])} {ctx['home']}** ({result['con']['n']} books)\nProjection: **{ctx['home']} {result['hmu']:.2f} – {result['amu']:.2f} {ctx['away']}** • total {result['hmu']+result['amu']:.2f}\nNB α H/A={disp['alpha_home']:.2f}/{disp['alpha_away']:.2f} • extras domicile {pct(result['extra_home'])} • phase **{result['phase']}** / {snap['role']}"
    direction=v["text"]+f"\n{emoji} Confiance lecture marché: **{v['confidence']:.1f}/10 — {label}**"
    starters=f"{ctx['away']}: **{ctx['away_sp']}** • {pitcher_line(ctx['away_sp_stats'],ctx['away_hand'])}\n{ctx['home']}: **{ctx['home_sp']}** • {pitcher_line(ctx['home_sp_stats'],ctx['home_hand'])}"
    advanced=f"Lineups H/A: **{ctx['home_lineup']['count']}/9 – {ctx['away_lineup']['count']}/9** • OPS pondéré {ctx['home_lineup']['weighted_ops'] if ctx['home_lineup']['weighted_ops'] else 'N/A'} / {ctx['away_lineup']['weighted_ops'] if ctx['away_lineup']['weighted_ops'] else 'N/A'}\nSplits vs main opposée PA: {int(num(ctx['home_split'].get('_pa')))} / {int(num(ctx['away_split'].get('_pa')))}\nStatcast {ctx['home']}: {fmt_statcast(ctx['home_statcast'])}\nStatcast {ctx['away']}: {fmt_statcast(ctx['away_statcast'])}\nBullpen ERA H/A: {ctx['home_bp']['era']:.2f}/{ctx['away_bp']['era']:.2f} • fatigue {ctx['home_bp']['load']:.2f}/{ctx['away_bp']['load']:.2f}"
    context=f"Park {ctx['park']:.3f} • météo: {ctx['weather']['text']}\nForme 10: {ctx['home']} {ctx['home_recent']['win_pct']*100:.0f}% (RD {ctx['home_recent']['run_diff_pg']:+.2f}/g) • {ctx['away']} {ctx['away_recent']['win_pct']*100:.0f}% (RD {ctx['away_recent']['run_diff_pg']:+.2f}/g)\nQualité adaptée à la phase: **{result['quality']*10:.1f}/10**"
    model_text="\n\n".join(f"**{'🏆 MONEYLINE' if m=='ML' else '⚾ RUN LINE' if m=='RUNLINE' else '📈 TOTAL'}**\n{model_rec_text(recs.get(m))}" for m in ("ML","RUNLINE","TOTAL"))
    exec_text="\n\n".join(f"**{'ML' if m=='ML' else 'RUN LINE' if m=='RUNLINE' else 'TOTAL'}** — {execution_status(recs.get(m),result['phase'])}" for m in ("ML","RUNLINE","TOTAL"))
    selected=[e for e in result["evals"] if e.get("selected")]
    final="\n".join(f"• **{e['market']} {e['name']} {e['point'] if e['point'] is not None else ''} @ {e['price']:.2f}** • {int(num(e['units'],0))}u" for e in selected) if selected else ("👀 Aucune mise en phase EARLY — les recommandations du modèle restent valides comme watchlist." if result["phase"]=="EARLY" else "Aucune mise exécutée : les recommandations et le prix disponible sont deux décisions séparées.")
    risk=f"Exposition journée: **{portfolio['allocated']:.2f} € / {portfolio['daily_cap']:.2f} €** • plafond/match {portfolio['game_cap']:.2f} €"
    return send_embed(f"⚾ MLB V{VERSION} • {ctx['away']} @ {ctx['home']}",[("🕒 Match",local_time(result["game"]["gameDate"])+" (Paris)"),("🎯 Modèle indépendant",probs),("🧭 Benchmark marché",direction),("🧑 Starters",starters),("🧪 Lineup / splits / Statcast / bullpen",advanced),("🔬 Contexte",context),("🎯 Recommandations du modèle",model_text),("💰 Winamax — uniquement exécution",exec_text),("🛡️ Risque portefeuille",risk),("✅ Verdict de mise",final)],color)

def send_top_messages(results,state):
    ok=True
    for market,title in (("ML","🏆 TOP 3 MONEYLINE — MODÈLE"),("RUNLINE","⚾ TOP 3 RUN LINE — MODÈLE"),("TOTAL","📈 TOP 3 TOTAUX — MODÈLE")):
        xs=[]
        for r in results:
            rec=r.get("model_recs",{}).get(market)
            if rec:xs.append((r,rec))
        xs=sorted(xs,key=lambda x:(x[1]["confidence"],x[1]["p_model"],x[1].get("market_gap") or -9),reverse=True)[:3]
        blocks=[]
        for i,(r,rec) in enumerate(xs):
            pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if market=="RUNLINE" else f" {rec['point']:g}")
            emoji,band,_=confidence_band(rec["confidence"]);mp=pct(rec.get("p_market")) if rec.get("p_market") is not None else "N/A";gap=f"{rec['market_gap']*100:+.1f} pts" if rec.get("market_gap") is not None else "N/A"
            blocks.append(f"**#{i+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{emoji} **{rec['name']}{pt}** • modèle **{pct(rec['p_model'])}** • marché {mp} • écart {gap}\nFair **{rec['fair']:.2f}** • **cote mini {rec['min_price']:.2f}** • confiance **{rec['confidence']:.1f}/10 — {band}**\n{execution_status(rec,r['phase'])}")
        txt="\n\n".join(blocks) if blocks else "Aucune recommandation modèle suffisamment définie."
        ok=send_embed(title,[("Classement prédictif V9.1.1",txt)],16766720) and ok
    logging.info("Top 3 modèle envoyés pour ce run");return ok

def daily_plan_pool(results):
    pool=[]
    for r in results:
        for market in ("ML","RUNLINE","TOTAL"):
            rec=r.get("model_recs",{}).get(market)
            if not rec:continue
            gap=max(0.0,num(rec.get("market_gap"),0.0));score=num(rec.get("confidence"),0)+gap*4+max(0,num(rec.get("p_model"),.5)-.5)*1.5;pool.append({"result":r,"rec":rec,"score":score})
    return sorted(pool,key=lambda x:(x["score"],x["rec"]["confidence"],x["rec"]["p_model"]),reverse=True)
def choose_distinct_games(pool,n,banned_games=None,min_conf=None):
    banned=set(banned_games or []);used=set();out=[]
    for item in pool:
        r=item["result"];rec=item["rec"];gid=str(r["game_pk"])
        if gid in banned or gid in used:continue
        if min_conf is not None and num(rec.get("confidence"),0)<min_conf:continue
        out.append(item);used.add(gid)
        if len(out)>=n:break
    return out
def plan_pick_text(item,index=None):
    r=item["result"];rec=item["rec"];market=rec["market"];pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if market=="RUNLINE" else f" {rec['point']:g}");label="ML" if market=="ML" else "RL" if market=="RUNLINE" else "TOTAL";emoji,band,_=confidence_band(rec["confidence"]);prefix=f"**#{index}** " if index is not None else "• ";return f"{prefix}{emoji} **{rec['name']}{pt} [{label}]**\n{r['ctx']['away']} @ {r['ctx']['home']} • phase {r['phase']}\nModèle **{pct(rec['p_model'])}** • confiance **{rec['confidence']:.1f}/10 — {band}** • fair {rec['fair']:.2f} • **cote mini {rec['min_price']:.2f}**\n{execution_status(rec,r['phase'])}"
def build_daily_plan(results):
    pool=daily_plan_pool(results);singles=choose_distinct_games(pool,3);single_games={str(x["result"]["game_pk"]) for x in singles};combo=choose_distinct_games(pool,3,banned_games=single_games,min_conf=5.8)
    if len(combo)<2:combo=choose_distinct_games(pool,2,banned_games=single_games)
    return singles,combo
def send_daily_plan(results):
    singles,combo=build_daily_plan(results);phase_note=" • ".join(sorted({x["result"]["phase"] for x in singles+combo})) if singles or combo else "N/A";simples="\n\n".join(plan_pick_text(x,i+1) for i,x in enumerate(singles)) if singles else "Pas assez de recommandations modèle pour proposer des simples aujourd'hui."
    if len(combo)>=2:
        legs=[];min_combo=1.0;current_combo=1.0;all_prices=True;all_prices_ok=True
        for item in combo:
            r=item["result"];rec=item["rec"];market=rec["market"];pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if market=="RUNLINE" else f" {rec['point']:g}");label="ML" if market=="ML" else "RL" if market=="RUNLINE" else "TOTAL";min_combo*=num(rec.get("min_price"),1);e=rec.get("winamax_eval");price=num(e.get("price"),0) if e else 0
            if price<=1:all_prices=False
            else:
                current_combo*=price
                if price+1e-9<num(rec.get("min_price"),99):all_prices_ok=False
            legs.append(f"• **{rec['name']}{pt} [{label}]** — {r['ctx']['away']} @ {r['ctx']['home']} • conf {rec['confidence']:.1f}/10 • mini {rec['min_price']:.2f}"+(f" • Winamax {price:.2f}" if price>1 else " • cote Winamax à vérifier"))
        price_status=(f"✅ Toutes les jambes passent leur cote mini • cote combinée actuelle ≈ **{current_combo:.2f}**" if all_prices_ok else f"❌ Au moins une jambe est sous sa cote mini • cote combinée actuelle ≈ **{current_combo:.2f}**") if all_prices else "⚠️ Une ou plusieurs cotes Winamax sont absentes du flux : vérifier chaque cote avant de jouer."
        combo_text="\n".join(legs)+f"\n\nCote mini combinée théorique : **{min_combo:.2f}**\n{price_status}"
    else:combo_text="Pas assez de sélections indépendantes pour recommander un combiné sans forcer des choix faibles."
    note=("Ce plan est généré à chaque run. En phase EARLY, il s'agit d'un plan provisoire : les lineups et les prix peuvent encore évoluer. Le combiné exclut volontairement tous les matchs utilisés dans les 3 simples.")
    return send_embed("🎟️ PLAN DE PARIS DU RUN — 3 SIMPLES + 1 COMBINÉ",[("🕒 État du run",f"{NOW.astimezone(PARIS).strftime('%d/%m/%Y %H:%M')} (Paris) • phases présentes : {phase_note}"),("🎯 3 SIMPLES DU MODÈLE",simples),("🧩 COMBINÉ DU MODÈLE — hors simples",combo_text),("ℹ️ Règle",note)],5763719)

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
    early={"game_pk":1,"phase":"EARLY","evals":[{"qualified":True,"ev":.1,"quality":.9,"edge":.05,"candidate_stake_eur":1.0,"candidate_units":2,"selected":False,"units":0,"stake_eur":0,"portfolio_reason":"","market":"ML","name":"A","model_recommended":True}]};allocate_portfolio([early]);assert not early["evals"][0]["selected"]
    late={"game_pk":2,"phase":"FINAL","evals":[{"qualified":True,"ev":.1,"quality":.9,"edge":.05,"candidate_stake_eur":1.5,"candidate_units":3,"selected":False,"units":0,"stake_eur":0,"portfolio_reason":"","market":"ML","name":"A","model_recommended":True}]};port=allocate_portfolio([late]);assert late["evals"][0]["selected"] and port["allocated"]<=BANKROLL*MAX_DAILY_EXPOSURE_PCT+.001
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
        try:r=analyze_base(g,pair[0],pair[1],states,hist);r["disp_state"]=disp_state;attach_model_recommendations(r);results.append(r)
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
    if discord_ok and results:
        send_top_messages(results,state);send_daily_plan(results)
    perf=performance(hist);logging.info("V%s terminé | analyses=%d | messages=%d | exposition=%.2f/%.2f€ | snapshots=%d",VERSION,len(results),published,portfolio["allocated"],portfolio["daily_cap"],sum(len(r.get("snapshots",[])) for r in hist.values()));logging.info("Performance | games=%d direction=%s Brier modèle=%s marché=%s | bets=%d profit=%.2f€ ROI=%s | CLV=%s pts n=%d",perf["games"],pct(perf["direction"]) if perf["direction"] is not None else "-",f"{perf['brier_model']:.4f}" if perf["brier_model"] is not None else "-",f"{perf['brier_market']:.4f}" if perf["brier_market"] is not None else "-",perf["bets"],perf["profit"],pct(perf["roi"]) if perf["roi"] is not None else "-",f"{perf['clv_pts']:+.2f}" if perf["clv_pts"] is not None else "-",perf["clv_n"])

# ============================== V10 PROFESSIONAL ==============================
VERSION="10.0.4"
SCHEMA_VERSION=10
FEATURE_VERSION="10.2.0"
MODEL_VERSION="runs-structural-phase-residual-v6"
VERDICT_VERSION="direction-calibrated-v5"
RECOMMENDATION_VERSION="model-first-mainline-calibrated-v10"
HISTORY_FILE=Path(os.getenv("HISTORY_FILE","data/mlb_history_v10.jsonl"))
ARCHIVE_DIR=HISTORY_FILE.parent/"archive_v10"
STATE_FILE=HISTORY_FILE.parent/"v10_state.json"
RUN_MODEL_MIN_GAMES=max(450,int(os.getenv("RUN_MODEL_MIN_GAMES","450") or 450))
CAL_MIN_GAMES=max(500,int(os.getenv("CAL_MIN_GAMES","500") or 500))
MIN_PLAN_CONF=float(os.getenv("MIN_PLAN_CONF","6.2") or 6.2)
MIN_COMBO_CONF=float(os.getenv("MIN_COMBO_CONF","6.5") or 6.5)
MAX_COMBO_EXPOSURE_PCT=float(os.getenv("MAX_COMBO_EXPOSURE_PCT","0.05") or .05)
V10_PHASES=("EARLY","LATE","FINAL");V10_MARKETS=("ML","RUNLINE","TOTAL")
_V10_HIST={};_V10_MARKET_CAL=None;_V10_RUN_PARENT=None;_V10_LAST_PORTFOLIO={"allocated":0.0,"daily_cap":BANKROLL*MAX_DAILY_EXPOSURE_PCT,"remaining":BANKROLL*MAX_DAILY_EXPOSURE_PCT}
_V9_GAME_CONTEXT=game_context;_V9_ANALYZE_BASE=analyze_base;_V9_ATTACH_RECS=attach_model_recommendations;_V9_ALLOCATE=allocate_portfolio;_V9_BUILD_SNAPSHOT=build_snapshot;_V9_SYNC_RECS=sync_recommendations;_V9_ENSURE_RECORD=ensure_record;_V9_SETTLE_HISTORY=settle_history;_V9_WRITE_HISTORY=write_history;_V9_PERFORMANCE=performance;_V9_MARKET_VERDICT=market_verdict;_V9_SELF_TEST=self_test

def v10_safe_ratio(v,base,lo=.65,hi=1.55):return 1.0 if base<=0 else clamp(num(v,base)/base,lo,hi)
def v10_expected_starter_ip(sp):
    gs=max(0.0,num((sp or {}).get("gs"),0));ip=max(0.0,num((sp or {}).get("ip"),0));raw=ip/gs if gs>=3 and ip>0 else 5.3;w=gs/(gs+8.0);return clamp(5.3+w*(raw-5.3),4.0,6.5)
def v10_advanced_base_runs(own_h,opp_p,own_recent,opp_sp,opp_bp,lineup,split,statcast,park,wx,home):
    lg=league_baselines();rpg=num(own_h.get("runsPerGame"),lg["rpg"]);ops=num(own_h.get("ops"),lg["ops"]);gp=max(1.0,num(opp_p.get("gamesPlayed"),0));runs_allowed=num(opp_p.get("runs"),0);opp_ra=runs_allowed/gp if runs_allowed>0 else lg["rpg"]*v10_safe_ratio(num(opp_p.get("era"),lg["era"]),lg["era"],.72,1.35);log_mu=math.log(lg["rpg"]);log_mu+=.34*math.log(v10_safe_ratio(rpg,lg["rpg"],.70,1.35));log_mu+=.20*math.log(v10_safe_ratio(ops,lg["ops"],.82,1.18));log_mu+=.14*math.log(v10_safe_ratio(opp_ra,lg["rpg"],.72,1.38))
    if num((own_recent or {}).get("games"),0)>=5:log_mu+=.08*math.log(v10_safe_ratio(num(own_recent.get("runs_pg"),rpg),lg["rpg"],.72,1.38))
    sip=v10_expected_starter_ip(opp_sp);starter_share=sip/9.0;bullpen_share=1-starter_share;sp_era=num(opp_sp.get("era"),lg["era"]);sp_whip=num(opp_sp.get("whip"),lg["whip"]);sp_k9=num(opp_sp.get("k9"),8.3);sp_bb9=num(opp_sp.get("bb9"),3.2);sp_quality=(sp_era-lg["era"])/1.45+.45*(sp_whip-lg["whip"])/.28+.18*((sp_bb9-3.2)/1.4-(sp_k9-8.3)/2.4);log_mu+=starter_share*clamp(sp_quality,-1.10,1.10)*.23;bp_era=num((opp_bp or {}).get("era"),lg["era"]);bp_whip=num((opp_bp or {}).get("whip"),lg["whip"]);bp_load=num((opp_bp or {}).get("load"),.5);bp_quality=(bp_era-lg["era"])/1.55+.35*(bp_whip-lg["whip"])/.30+.35*(bp_load-.5)/.60;log_mu+=bullpen_share*clamp(bp_quality,-1.0,1.2)*.22
    lineup_ops=(lineup or {}).get("weighted_ops");lineup_count=int(num((lineup or {}).get("count"),0))
    if lineup_ops is not None and lineup_count>=7:log_mu+=clamp(lineup_count/9.0,0,1)*.18*clamp((num(lineup_ops,ops)-ops)/.080,-1,1)
    split_ops=(split or {}).get("_shrunk_ops");split_pa=num((split or {}).get("_pa"),0)
    if split_ops is not None and split_pa>=40:log_mu+=clamp(split_pa/250.0,.20,1.0)*.13*clamp((num(split_ops,ops)-ops)/.080,-1,1)
    xwoba=(statcast or {}).get("xwoba");pa=num((statcast or {}).get("pa"),0)
    if xwoba is not None:log_mu+=clamp(pa/1800.0,.25,1.0)*.12*clamp((num(xwoba,.317)-.317)/.045,-1,1)
    log_mu+=.55*math.log(clamp(num(park,1.0),.88,1.16));log_mu+=clamp(num((wx or {}).get("run_adj"),0),-.25,.30)*.10;return clamp(math.exp(log_mu)+(0.08 if home else 0.0),2.0,8.2)
def game_context(g):
    ctx=_V9_GAME_CONTEXT(g);hh=season_stats(ctx["home_id"],"hitting");hp=season_stats(ctx["home_id"],"pitching");ah=season_stats(ctx["away_id"],"hitting");ap=season_stats(ctx["away_id"],"pitching");hs=dict(shrunk_pitcher(ctx.get("home_sp_stats") or {}));ass=dict(shrunk_pitcher(ctx.get("away_sp_stats") or {}));hs["gs"]=max(0,num((ctx.get("home_sp_stats") or {}).get("gamesStarted"),0));ass["gs"]=max(0,num((ctx.get("away_sp_stats") or {}).get("gamesStarted"),0));h=v10_advanced_base_runs(hh,ap,ctx["home_recent"],ass,ctx["away_bp"],ctx["home_lineup"],ctx["home_split"],ctx["home_statcast"],ctx["park"],ctx["weather"],True);a=v10_advanced_base_runs(ah,hp,ctx["away_recent"],hs,ctx["home_bp"],ctx["away_lineup"],ctx["away_split"],ctx["away_statcast"],ctx["park"],ctx["weather"],False);ctx["base_home_v9"]=ctx["base_home"];ctx["base_away_v9"]=ctx["base_away"];ctx["base_home"]=h;ctx["base_away"]=a;ctx["structural_adj_home"]=h-ctx["base_home_v9"];ctx["structural_adj_away"]=a-ctx["base_away_v9"];ctx["base_engine"]="advanced-baseball-v10";ctx["expected_home_sp_ip"]=v10_expected_starter_ip(hs);ctx["expected_away_sp_ip"]=v10_expected_starter_ip(ass);logging.info("V10 RUN BASE | %s @ %s | H %.2f→%.2f (%+.2f) | A %.2f→%.2f (%+.2f)",ctx["away"],ctx["home"],ctx["base_home_v9"],h,ctx["structural_adj_home"],ctx["base_away_v9"],a,ctx["structural_adj_away"]);return ctx

def v10_phase_snapshot(record,phase):
    xs=[s for s in record.get("snapshots",[]) if num(s.get("seconds_to_game"),-1)>=0 and s.get("phase")==phase and s.get("feature_version")==FEATURE_VERSION and s.get("model_version")==MODEL_VERSION and s.get("distribution_version")==DIST_VERSION];return max(xs,key=lambda s:s.get("analyzed_at","")) if xs else None
def latest_pregame_snapshot(record,feature=None):
    feature=feature or FEATURE_VERSION;xs=[s for s in record.get("snapshots",[]) if num(s.get("seconds_to_game"),-1)>=0 and s.get("feature_version")==feature and s.get("model_version")==MODEL_VERSION and s.get("distribution_version")==DIST_VERSION];return max(xs,key=lambda s:s.get("analyzed_at","")) if xs else None
def v10_training_games_phase(hist,phase):
    out=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=v10_phase_snapshot(r,phase)
        if not s:continue
        try:out.append((r.get("game_date",""),s,float(r["home_score"]),float(r["away_score"])))
        except Exception:pass
    out.sort(key=lambda x:x[0]);return out
def v10_run_state_phase(hist,phase):
    games=v10_training_games_phase(hist,phase);out={"phase":phase,"active":False,"model":None,"n":len(games),"rmse_model":None,"rmse_base":None,"gain_prob":0.0,"folds":0}
    if len(games)<RUN_MODEL_MIN_GAMES:return out
    base_losses=[];new_losses=[];folds=walk_folds(len(games),180)
    for cut,end in folds:
        rows=[]
        for _,s,hs,as_ in games[:cut]:rows += [(s["run_features_home"],hs-num(s["base_home"])),(s["run_features_away"],as_-num(s["base_away"]))]
        if not rows:continue
        m=fit_linear(rows)
        for _,s,hs,as_ in games[cut:end]:
            ph=num(s["base_home"])+clamp(linear_predict(m,s["run_features_home"]),-2,2);pa=num(s["base_away"])+clamp(linear_predict(m,s["run_features_away"]),-2,2);base_losses += [rmse_loss(num(s["base_home"]),hs),rmse_loss(num(s["base_away"]),as_)];new_losses += [rmse_loss(ph,hs),rmse_loss(pa,as_)]
    if not base_losses:return out
    rb=math.sqrt(mean(base_losses));rn=math.sqrt(mean(new_losses));gp=bootstrap_gain_prob(base_losses,new_losses);out.update({"rmse_base":rb,"rmse_model":rn,"gain_prob":gp,"folds":len(folds)})
    if rn+.035<rb and gp>=.90:
        rows=[]
        for _,s,hs,as_ in games:rows += [(s["run_features_home"],hs-num(s["base_home"])),(s["run_features_away"],as_-num(s["base_away"]))]
        out.update({"active":True,"model":fit_linear(rows)})
    return out
def run_model_state(hist):
    global _V10_RUN_PARENT,_V10_HIST,_V10_MARKET_CAL
    _V10_HIST=hist;_V10_MARKET_CAL=None;states={p:v10_run_state_phase(hist,p) for p in V10_PHASES};_V10_RUN_PARENT={"active":any(x["active"] for x in states.values()),"model":None,"n":sum(x["n"] for x in states.values()),"rmse_model":next((x["rmse_model"] for x in reversed(tuple(states.values())) if x["rmse_model"] is not None),None),"rmse_base":next((x["rmse_base"] for x in reversed(tuple(states.values())) if x["rmse_base"] is not None),None),"gain_prob":max((x["gain_prob"] for x in states.values()),default=0),"folds":sum(x["folds"] for x in states.values()),"phase_states":states};return _V10_RUN_PARENT
def v10_ml_cal_state_phase(hist,phase,engine):
    rows=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=v10_phase_snapshot(r,phase)
        if s and s.get("engine_mode")==engine and s.get("p_model_raw") is not None:rows.append((r.get("game_date",""),num(s["p_model_raw"],.5),int(r.get("home_win",0))))
    rows.sort();out={"phase":phase,"active":False,"model":None,"n":len(rows),"brier_raw":None,"brier_cal":None,"gain_prob":0.0,"folds":0}
    if len(rows)<CAL_MIN_GAMES:return out
    base_losses=[];new_losses=[];folds=walk_folds(len(rows),220)
    for cut,end in folds:
        m=fit_platt([(p,y) for _,p,y in rows[:cut]])
        for _,p,y in rows[cut:end]:base_losses.append((p-y)**2);new_losses.append((platt_predict(m,p)-y)**2)
    if not base_losses:return out
    br=mean(base_losses);bc=mean(new_losses);gp=bootstrap_gain_prob(base_losses,new_losses);out.update({"brier_raw":br,"brier_cal":bc,"gain_prob":gp,"folds":len(folds)})
    if bc+.001<br and gp>=.90:out.update({"active":True,"model":fit_platt([(p,y) for _,p,y in rows])})
    return out
def calibration_state(hist,_engine_mode):
    parent=_V10_RUN_PARENT or run_model_state(hist);states={ph:v10_ml_cal_state_phase(hist,ph,"learned-runs" if parent["phase_states"][ph]["active"] else "base-runs") for ph in V10_PHASES};return {"active":any(x["active"] for x in states.values()),"model":None,"n":sum(x["n"] for x in states.values()),"brier_raw":None,"brier_cal":None,"gain_prob":max((x["gain_prob"] for x in states.values()),default=0),"folds":sum(x["folds"] for x in states.values()),"phase_states":states}
def v10_skill_state_phase(hist,phase,engine):
    pm=[];pk=[];ys=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=v10_phase_snapshot(r,phase)
        if not s or s.get("engine_mode")!=engine or s.get("p_model") is None or s.get("market_home") is None:continue
        pm.append(num(s["p_model"],.5));pk.append(num(s["market_home"],.5));ys.append(int(r.get("home_win",0)))
    if len(ys)<60:return {"phase":phase,"n":len(ys),"brier_model":None,"brier_market":None,"model_weight":.42}
    bm=brier(pm,ys);bk=brier(pk,ys);return {"phase":phase,"n":len(ys),"brier_model":bm,"brier_market":bk,"model_weight":clamp(.42+(bk-bm)*8,.25,.68)}
def skill_state(hist,_engine_mode):
    parent=_V10_RUN_PARENT or run_model_state(hist);states={ph:v10_skill_state_phase(hist,ph,"learned-runs" if parent["phase_states"][ph]["active"] else "base-runs") for ph in V10_PHASES};return {"n":sum(x["n"] for x in states.values()),"brier_model":None,"brier_market":None,"model_weight":.42,"phase_states":states}
def v10_select_phase_states(states,phase):
    rp,disp,cp,sp=states;return rp.get("phase_states",{}).get(phase,{"active":False,"model":None,"n":0}),disp,cp.get("phase_states",{}).get(phase,{"active":False,"model":None,"n":0}),sp.get("phase_states",{}).get(phase,{"n":0,"model_weight":.42})
def analyze_base(g,event,delta,states,hist):
    phase=snapshot_phase((parse_dt(g["gameDate"])-NOW).total_seconds());chosen=v10_select_phase_states(states,phase);r=_V9_ANALYZE_BASE(g,event,delta,chosen,hist);r["phase_model_n"]=chosen[0].get("n",0);r["phase_cal_n"]=chosen[2].get("n",0);r["phase_skill_n"]=chosen[3].get("n",0);return r

def v10_refs_cap(refs):refs=int(max(0,num(refs,0)));return 5.4 if refs<=0 else 6.0 if refs==1 else 7.5 if refs==2 else 8.8 if refs==3 else 9.5
def v10_quality_cap(q):q=clamp(num(q,0),0,1);return 5.3 if q<.50 else 6.2 if q<.60 else 7.3 if q<.70 else 8.4 if q<.80 else 9.5
def model_signal_confidence(p_model,quality,p_market=None,refs=0):
    p=clamp(num(p_model,.5),.001,.999);q=clamp(num(quality,0),0,1);refs_i=int(max(0,num(refs,0)));score=4.15+clamp((q-.45)/.45,0,1)*2.05+clamp(abs(p-.5)/.20,0,1)*1.15+{0:0,1:.15,2:.40,3:.62}.get(min(refs_i,3),.62)
    if refs_i>=4:score+=min(.28,(refs_i-3)*.07)
    if p_market is None:score-=.20
    else:
        gap=abs(p-num(p_market,.5));score += .25 if gap<=.025 and refs_i>=3 else .10 if gap<=.05 and refs_i>=3 else 0 if gap<=.08 else -.25 if gap<=.11 else -.55 if gap<=.15 else -.90
    if q<.60 and abs(p-.5)>.12:score-=.35
    if q<.50:score-=.25
    return round(min(clamp(score,4.0,9.5),v10_refs_cap(refs_i),v10_quality_cap(q)),2)
def market_verdict(ctx,p_model,p_market,meta,skill,hist,engine_mode,quality):
    v=_V9_MARKET_VERDICT(ctx,p_model,p_market,meta,skill,hist,engine_mode,quality);v["confidence"]=min(num(v.get("confidence"),0),v10_refs_cap(meta.get("n",0)),v10_quality_cap(quality));return v

def v10_fresh_market_rows(event,key):
    for b,m in market_rows(event,key):
        if b.get("key") not in REF_BOOKS:continue
        try:stamp=m.get("last_update",b.get("last_update"));age=max(0,(NOW-parse_dt(stamp)).total_seconds()/60) if stamp else 0
        except Exception:age=0
        if age<=90:yield b,m
def v10_main_total_line(event):
    votes=[]
    for b,m in v10_fresh_market_rows(event,"totals"):
        points={}
        for o in m.get("outcomes",[]):
            n=str(o.get("name","")).lower()
            if n in ("over","under") and o.get("point") is not None:points.setdefault(round(num(o["point"]),3),{})[n]=num(o.get("price"))
        cand=[]
        for pt,pair in points.items():
            if pair.get("over",0)>1 and pair.get("under",0)>1:a=1/pair["over"];c=1/pair["under"];cand.append((abs(a/(a+c)-.5),pt))
        if cand:votes.append((b.get("key"),min(cand)[1]))
    if not votes:return None
    counts={pt:sum(v==pt for _,v in votes) for _,pt in votes};mx=max(counts.values());med=median([v for _,v in votes]);pt=min([p for p,n in counts.items() if n==mx],key=lambda x:(abs(x-med),x));return {"point":pt,"votes":counts[pt],"total_books":len(votes),"support_ratio":counts[pt]/len(votes)}
def v10_main_spread_line(event,home,away):
    votes=[]
    for b,m in v10_fresh_market_rows(event,"spreads"):
        homes=[];aways=[]
        for o in m.get("outcomes",[]):
            if o.get("point") is None:continue
            row=(round(num(o["point"]),3),num(o.get("price")))
            if norm_name(o.get("name"))==norm_name(home):homes.append(row)
            elif norm_name(o.get("name"))==norm_name(away):aways.append(row)
        cand=[]
        for hp,hpr in homes:
            for ap,apr in aways:
                if abs(hp+ap)<=1e-6 and hpr>1 and apr>1:a=1/hpr;c=1/apr;cand.append((abs(abs(hp)-1.5),abs(a/(a+c)-.5),hp))
        if cand:votes.append((b.get("key"),min(cand)[2]))
    if not votes:return None
    counts={pt:sum(v==pt for _,v in votes) for _,pt in votes};mx=max(counts.values());med=median([v for _,v in votes]);pt=min([p for p,n in counts.items() if n==mx],key=lambda x:(abs(abs(x)-1.5),abs(x-med),x));return {"home_point":pt,"away_point":-pt,"votes":counts[pt],"total_books":len(votes),"support_ratio":counts[pt]/len(votes)}
def v10_main_line_view(result,market,name,point,meta):
    mk="spreads" if market=="RUNLINE" else "totals";con=consensus(result["event"],mk,name,point);pw,pp,pl=line_probs(result["hmu"],result["amu"],result["disp_state"]["alpha_home"],result["disp_state"]["alpha_away"],market,name,point,result["ctx"]["home"],result["ctx"]["away"]);nonpush=pw+pl
    if nonpush<=0:return None
    pm=pw/nonpush;mp=con.get("p");return {"market":market,"name":name,"point":point,"p_model":pm,"p_win":pw,"p_push":pp,"p_loss":pl,"p_market":mp,"market_gap":pm-mp if mp is not None else None,"refs":con.get("n",0),"fair":(1-pp)/pw if pw>0 else 99,"min_price":min_acceptable_price(pw,pp,pl),"confidence":model_signal_confidence(pm,result["quality"],mp,con.get("n",0)),"winamax_eval":winamax_eval_for(result,market,name,point),"main_line":True,"main_line_votes":meta["votes"],"main_line_total_books":meta["total_books"],"main_line_support":meta["support_ratio"]}
def model_line_views(result,market):
    if market=="RUNLINE":meta=v10_main_spread_line(result["event"],result["ctx"]["home"],result["ctx"]["away"]);pairs=[] if not meta else [(result["ctx"]["home"],meta["home_point"]),(result["ctx"]["away"],meta["away_point"])]
    elif market=="TOTAL":meta=v10_main_total_line(result["event"]);pairs=[] if not meta else [("Over",meta["point"]),("Under",meta["point"])]
    else:return []
    return [v for name,pt in pairs for v in [v10_main_line_view(result,market,name,pt,meta)] if v]
def best_model_line(result,market):xs=model_line_views(result,market);return max(xs,key=lambda v:(v["p_model"],v["confidence"],v["refs"])) if xs else None

def v10_logloss(ps,ys):return mean(-(y*math.log(clamp(p,.001,.999))+(1-y)*math.log(clamp(1-p,.001,.999))) for p,y in zip(ps,ys)) if ps else None
def v10_fit_platt(ps,ys,epochs=700,lr=.035,l2=.015):
    if len(ps)<8:return None
    a,b=1.0,0.0;xs=[logit(clamp(p,.001,.999)) for p in ps];n=len(xs)
    for _ in range(epochs):
        ga=gb=0.0
        for x,y in zip(xs,ys):q=sigmoid(a*x+b);e=q-y;ga+=e*x;gb+=e
        a-=lr*(ga/n+l2*(a-1));b-=lr*(gb/n+l2*b)
    return a,b
def v10_platt_predict(m,p):return clamp(sigmoid(m[0]*logit(clamp(p,.001,.999))+m[1])) if m else clamp(p,.001,.999)
def v10_calibrate_tuple(m,pw,pp,pl):
    s=max(0,pw)+max(0,pp)+max(0,pl)
    if s<=0:return .5,0,.5
    pw,pp,pl=max(0,pw)/s,max(0,pp)/s,max(0,pl)/s;np=pw+pl
    if np<=0:return 0,1,0
    q=v10_platt_predict(m,pw/np);mass=1-pp;return mass*q,pp,mass*(1-q)
def v10_settled_predictions(hist,market=None,phase=None):
    rows=[]
    for r in hist.values():
        for p in r.get("predictions",[]):
            if market and p.get("market")!=market:continue
            if phase and p.get("phase")!=phase:continue
            if p.get("result") in ("W","L","P"):rows.append(p)
    rows.sort(key=lambda x:(x.get("analyzed_at",""),x.get("prediction_id","")));return rows
def v10_market_cal_state(hist,market,phase):
    rows=[r for r in v10_settled_predictions(hist,market,phase) if r.get("result") in ("W","L")];out={"market":market,"phase":phase,"n":len(rows),"active":False,"model":None,"brier_raw":None,"brier_cal":None,"logloss_raw":None,"logloss_cal":None}
    if len(rows)<CAL_MIN_GAMES:return out
    cut=max(30,int(len(rows)*.8));train,val=rows[:cut],rows[cut:]
    if len(val)<20:return out
    tp=[clamp(num(r.get("p_model_raw",r.get("p_model",.5))),.001,.999) for r in train];ty=[1 if r["result"]=="W" else 0 for r in train];vp=[clamp(num(r.get("p_model_raw",r.get("p_model",.5))),.001,.999) for r in val];vy=[1 if r["result"]=="W" else 0 for r in val];m=v10_fit_platt(tp,ty);cp=[v10_platt_predict(m,p) for p in vp];br0=brier(vp,vy);br1=brier(cp,vy);ll0=v10_logloss(vp,vy);ll1=v10_logloss(cp,vy);active=br1 is not None and br1<=br0*.997 and ll1 is not None and ll1<=ll0*.997;out.update({"active":active,"model":v10_fit_platt([clamp(num(r.get("p_model_raw",r.get("p_model",.5))),.001,.999) for r in rows],[1 if r["result"]=="W" else 0 for r in rows]) if active else None,"brier_raw":br0,"brier_cal":br1,"logloss_raw":ll0,"logloss_cal":ll1});return out
def v10_market_cal_states():
    global _V10_MARKET_CAL
    if _V10_MARKET_CAL is None:_V10_MARKET_CAL={ph:{m:v10_market_cal_state(_V10_HIST,m,ph) for m in V10_MARKETS} for ph in V10_PHASES}
    return _V10_MARKET_CAL
def v10_refresh_execution(rec,result):
    e=rec.get("winamax_eval")
    if not e:return
    price=num(e.get("price"),0)
    if price<=1:return
    pw,pp,pl=rec["p_win"],rec["p_push"],rec["p_loss"];np=pw+pl;pcond=pw/np if np else .5;edge=pcond-1/price;ev=pw*price+pp-1;cu,cs=stake_candidate(pw,pp,pl,price);reasons=[]
    if result["quality"]<MIN_QUALITY:reasons.append("qualité insuffisante")
    if edge<MIN_EDGE:reasons.append("edge prix insuffisant")
    if ev<MIN_EV:reasons.append("EV prix insuffisante")
    if not reasons and cu<=0:reasons.append("Kelly prudent < 0.25u")
    e.update({"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":pcond,"fair":rec["fair"],"min_price":rec["min_price"],"edge":edge,"ev":ev,"quality":result["quality"],"qualified":not reasons,"reason":"OK" if not reasons else " ; ".join(reasons),"candidate_units":cu,"candidate_stake_eur":cs})
def attach_model_recommendations(result):
    recs=_V9_ATTACH_RECS(result);states=v10_market_cal_states();phase=result.get("phase","EARLY")
    for market,rec in recs.items():
        if not rec:continue
        s=states.get(phase,{}).get(market,{});rec["p_model_raw"]=rec.get("p_model");rec["market_calibration_n"]=s.get("n",0);rec["market_calibration_active"]=bool(s.get("active"))
        if s.get("active") and s.get("model"):
            pw,pp,pl=v10_calibrate_tuple(s["model"],num(rec.get("p_win"),rec["p_model"]),num(rec.get("p_push"),0),num(rec.get("p_loss"),1-rec["p_model"]));np=pw+pl
            if np>0:pm=pw/np;rec.update({"p_model":pm,"p_win":pw,"p_push":pp,"p_loss":pl});rec["fair"]=(1-pp)/pw if pw>0 else 99;rec["min_price"]=min_acceptable_price(pw,pp,pl);rec["market_gap"]=pm-rec["p_market"] if rec.get("p_market") is not None else None;rec["confidence"]=model_signal_confidence(pm,result["quality"],rec.get("p_market"),rec.get("refs",0));v10_refresh_execution(rec,result)
    return recs

def allocate_portfolio(results):
    global _V10_LAST_PORTFOLIO
    _V10_LAST_PORTFOLIO=_V9_ALLOCATE(results);return _V10_LAST_PORTFOLIO
def ensure_record(hist,g):r=_V9_ENSURE_RECORD(hist,g);r["schema_version"]=10;r.setdefault("predictions",[]);return r
def v10_prediction_id(game_pk,sid,market,name,point):return hashlib.sha1(f"{game_pk}|{sid}|{market}|{norm_name(name)}|{point}".encode()).hexdigest()[:20]
def v10_prediction_payload(result,sid,rec,at):
    e=rec.get("winamax_eval") or {};return {"prediction_id":v10_prediction_id(result["game_pk"],sid,rec["market"],rec["name"],rec.get("point")),"snapshot_id":sid,"game_pk":result["game_pk"],"analyzed_at":at,"phase":result["phase"],"market":rec["market"],"name":rec["name"],"point":rec.get("point"),"home":result["ctx"]["home"],"away":result["ctx"]["away"],"p_model_raw":rec.get("p_model_raw",rec.get("p_model")),"p_model":rec.get("p_model"),"p_win":rec.get("p_win"),"p_push":rec.get("p_push",0),"p_loss":rec.get("p_loss"),"p_market":rec.get("p_market"),"refs":rec.get("refs",0),"confidence":rec.get("confidence"),"fair":rec.get("fair"),"min_price":rec.get("min_price"),"quality":result.get("quality"),"winamax_price":e.get("price"),"winamax_qualified":bool(e.get("qualified")),"winamax_selected":bool(e.get("selected")),"result":None}
def build_snapshot(result,rec):
    snap=_V9_BUILD_SNAPSHOT(result,rec);snap["schema_version"]=10;snap["base_home_v9"]=round(result["ctx"].get("base_home_v9",result["ctx"]["base_home"]),4);snap["base_away_v9"]=round(result["ctx"].get("base_away_v9",result["ctx"]["base_away"]),4);snap["predictions"]=[v10_prediction_payload(result,snap["snapshot_id"],x,snap["analyzed_at"]) for x in (result.get("model_recs") or {}).values() if x];return snap
def sync_recommendations(rec,evals,snap):
    out=_V9_SYNC_RECS(rec,evals,snap)
    if not any(s.get("snapshot_id")==snap.get("snapshot_id") for s in rec.get("snapshots",[])):return out
    ledger=rec.setdefault("predictions",[]);known={x.get("prediction_id") for x in ledger}
    for p in snap.get("predictions",[]):
        if p["prediction_id"] not in known:ledger.append(dict(p));known.add(p["prediction_id"])
    return out
def v10_settle_market(market,name,point,home,away,hs,as_):
    hs,as_=num(hs),num(as_)
    if market=="ML":return "W" if ((hs>as_) if norm_name(name)==norm_name(home) else (as_>hs)) else "L"
    if market=="RUNLINE":picked_home=norm_name(name)==norm_name(home);v=(hs if picked_home else as_)+num(point)-(as_ if picked_home else hs);return "W" if v>1e-9 else "L" if v<-1e-9 else "P"
    if market=="TOTAL":v=hs+as_-num(point);return "P" if abs(v)<1e-9 else "W" if ((v>0)==(str(name).lower()=="over")) else "L"
    return None
def v10_settle_prediction_ledger(hist):
    changed=0
    for rec in hist.values():
        if rec.get("status")!="FINAL":continue
        hs=rec.get("home_score");as_=rec.get("away_score")
        if hs is None or as_ is None:continue
        for p in rec.get("predictions",[]):
            if p.get("result") in ("W","L","P"):continue
            z=v10_settle_market(p.get("market"),p.get("name"),p.get("point"),rec.get("home",""),rec.get("away",""),hs,as_)
            if z:p["result"]=z;changed+=1
    return changed
def write_history(hist):v10_settle_prediction_ledger(hist);return _V9_WRITE_HISTORY(hist)
def settle_history(hist):
    n=_V9_SETTLE_HISTORY(hist);changed=v10_settle_prediction_ledger(hist)
    if changed:_V9_WRITE_HISTORY(hist)
    return n
def v10_prediction_metrics(xs):
    settled=[p for p in xs if p.get("result") in ("W","L","P")];wl=[p for p in settled if p["result"] in ("W","L")];ps=[num(p.get("p_model"),.5) for p in wl];ys=[1 if p["result"]=="W" else 0 for p in wl];return {"n":len(settled),"n_wl":len(wl),"pushes":len(settled)-len(wl),"wins":sum(ys),"accuracy":sum(ys)/len(ys) if ys else None,"brier":brier(ps,ys) if ps else None,"logloss":v10_logloss(ps,ys)}
def v10_performance_report(hist):
    xs=[p for r in hist.values() for p in r.get("predictions",[])];return {"overall":v10_prediction_metrics(xs),"by_market":{m:v10_prediction_metrics([p for p in xs if p.get("market")==m]) for m in V10_MARKETS},"by_phase":{ph:v10_prediction_metrics([p for p in xs if p.get("phase")==ph]) for ph in V10_PHASES},"by_confidence":{f"{lo}-{lo+1}":v10_prediction_metrics([p for p in xs if lo<=num(p.get("confidence"))<lo+1]) for lo in (4,5,6,7,8,9)}}
def performance(hist):
    out=_V9_PERFORMANCE(hist);report=v10_performance_report(hist);out["prediction_report"]=report;o=report["overall"];logging.info("V10 PRED METRICS | n=%d WL=%d pushes=%d accuracy=%s Brier=%s LogLoss=%s",o["n"],o["n_wl"],o["pushes"],pct(o["accuracy"]) if o["accuracy"] is not None else "-",f"{o['brier']:.4f}" if o["brier"] is not None else "-",f"{o['logloss']:.4f}" if o["logloss"] is not None else "-");return out

def daily_plan_pool(results):
    pool=[]
    for r in results:
        for market in V10_MARKETS:
            rec=(r.get("model_recs") or {}).get(market)
            if rec:pool.append({"result":r,"rec":rec,"score":num(rec.get("confidence"))+max(0,num(rec.get("p_model"),.5)-.5)*.80+num(r.get("quality"),.5)*.25})
    return sorted(pool,key=lambda x:(x["score"],num(x["rec"].get("confidence")),num(x["rec"].get("p_model"))),reverse=True)
def choose_distinct_games(pool,n,banned_games=None,min_conf=None):
    banned={str(x) for x in (banned_games or set())};used=set();out=[]
    for item in pool:
        gid=str(item["result"]["game_pk"])
        if gid in banned or gid in used or (min_conf is not None and num(item["rec"].get("confidence"))<min_conf):continue
        out.append(item);used.add(gid)
        if len(out)>=n:break
    return out
def build_daily_plan(results):
    pool=daily_plan_pool(results);singles=choose_distinct_games(pool,3,min_conf=MIN_PLAN_CONF);banned={str(x["result"]["game_pk"]) for x in singles};combo=choose_distinct_games(pool,3,banned,min_conf=MIN_COMBO_CONF)
    if len(combo)<2:combo=choose_distinct_games(pool,2,banned,min_conf=MIN_COMBO_CONF)
    return singles,combo if len(combo)>=2 else []
def v10_combo_metrics(combo):
    if len(combo)<2:return {"valid":False,"legs":len(combo)}
    pwin=noloss=expected=fair=minprod=quoted=1.0;all_prices=True;all_min=True
    for item in combo:
        r=item["rec"];pw=num(r.get("p_win"));pp=num(r.get("p_push"));pl=num(r.get("p_loss"));s=pw+pp+pl
        if s<=0:return {"valid":False,"legs":len(combo)}
        pw,pp,pl=pw/s,pp/s,pl/s;np=pw+pl
        if np<=0:return {"valid":False,"legs":len(combo)}
        e=r.get("winamax_eval") or {};price=num(e.get("price"),0);minimum=num(r.get("min_price"),99);pwin*=pw;noloss*=pw+pp;fair*=1/(pw/np);minprod*=minimum
        if price<=1:all_prices=False
        else:quoted*=price;expected*=pw*price+pp;all_min=all_min and price+1e-9>=minimum
    return {"valid":True,"legs":len(combo),"p_all_win":pwin,"p_no_loss":noloss,"fair_conditional":fair,"min_product":minprod,"quoted_price":quoted if all_prices else None,"expected_multiplier":expected if all_prices else None,"ev":expected-1 if all_prices else None,"all_prices":all_prices,"all_legs_above_min":all_min if all_prices else False}
def v10_combo_stake(combo):
    m=v10_combo_metrics(combo)
    if not m.get("valid") or not m.get("all_prices") or not m.get("all_legs_above_min") or m.get("ev") is None or m["ev"]<MIN_EV or any(x["result"].get("phase")=="EARLY" for x in combo):return 0.0
    room=max(0,num(_V10_LAST_PORTFOLIO.get("daily_cap"),BANKROLL*MAX_DAILY_EXPOSURE_PCT)-num(_V10_LAST_PORTFOLIO.get("allocated"),0));cap=min(BANKROLL*MAX_COMBO_EXPOSURE_PCT,UNIT,room);q=max(.01,UNIT/4);return round(math.floor((cap/q)+1e-9)*q,2) if cap>=q else 0.0
def send_daily_plan(results):
    singles,combo=build_daily_plan(results);phase_note=" • ".join(sorted({x["result"]["phase"] for x in singles+combo})) if singles or combo else "N/A";simples="\n\n".join(plan_pick_text(x,i+1) for i,x in enumerate(singles)) if singles else f"**Aucun simple forcé.** Aucune sélection n'atteint le seuil V10 de {MIN_PLAN_CONF:.1f}/10."
    if combo:
        m=v10_combo_metrics(combo);legs=[]
        for x in combo:
            r=x["result"];rec=x["rec"];pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if rec["market"]=="RUNLINE" else f" {rec['point']:g}");price=num((rec.get("winamax_eval") or {}).get("price"),0);legs.append(f"• **{rec['name']}{pt}** — {r['ctx']['away']} @ {r['ctx']['home']} • conf {rec['confidence']:.1f}/10 • mini {rec['min_price']:.2f}"+(f" • Winamax {price:.2f}" if price>1 else " • cote Winamax à vérifier"))
        stake=v10_combo_stake(combo);combo_text="\n".join(legs)+f"\n\nP(toutes gagnantes) **{pct(m['p_all_win'])}** • P(aucune perdante) **{pct(m['p_no_loss'])}**\nFair conditionnelle ≈ **{m['fair_conditional']:.2f}** • produit cotes mini **{m['min_product']:.2f}**"
        if m.get("quoted_price") is not None:combo_text+=f"\nCote actuelle ≈ **{m['quoted_price']:.2f}** • EV avec pushes **{m['ev']*100:+.1f}%**"
        combo_text+=(f"\n✅ **COMBINÉ JOUABLE** • mise prudente **{stake:.2f} €**" if stake>0 else "\n⚠️ **SURVEILLANCE / NON JOUABLE aux prix actuels**")
    else:combo_text=f"**Aucun combiné forcé.** Il faut au moins 2 matchs hors simples à ≥ {MIN_COMBO_CONF:.1f}/10."
    return send_embed("🎟️ PLAN V10 — JUSQU'À 3 SIMPLES + COMBINÉ",[("🕒 État du run",f"{NOW.astimezone(PARIS).strftime('%d/%m/%Y %H:%M')} (Paris) • phases : {phase_note}"),("🎯 SIMPLES QUALIFIÉS",simples),("🧩 COMBINÉ HORS SIMPLES",combo_text),("🛡️ Règle V10","Jusqu'à 3 simples, jamais forcés. Combiné hors matchs des simples, pushes et exposition bankroll pris en compte.")],5763719)

def v10_self_test():
    _V9_SELF_TEST();neutral={"runsPerGame":4.45,"ops":.710};opp={"gamesPlayed":100,"runs":445,"era":4.35};recent={"games":10,"runs_pg":4.45};bp={"era":4.35,"whip":1.32,"load":.5};line={"count":9,"weighted_ops":.710};split={"_shrunk_ops":.710,"_pa":300};sc={"xwoba":.317,"pa":2000};wx={"run_adj":0};sp={"gs":20,"ip":106,"era":4.35,"whip":1.32,"k9":8.3,"bb9":3.2};base=v10_advanced_base_runs(neutral,opp,recent,sp,bp,line,split,sc,1,wx,False);ace=dict(sp);ace.update({"era":2.3,"whip":1.0,"k9":11,"bb9":2});weak=dict(sp);weak.update({"era":6.2,"whip":1.65,"k9":6.2,"bb9":5});assert v10_advanced_base_runs(neutral,opp,recent,ace,bp,line,split,sc,1,wx,False)<base<v10_advanced_base_runs(neutral,opp,recent,weak,bp,line,split,sc,1,wx,False);assert model_signal_confidence(.72,.95,.58,1)<=6 and model_signal_confidence(.72,.95,.58,2)<=7.5;assert v10_settle_market("RUNLINE","Away",1,"Home","Away",5,4)=="P" and v10_settle_market("TOTAL","Over",9,"Home","Away",5,4)=="P";pw,pp,pl=v10_calibrate_tuple((1,0),.55,.08,.37);assert abs(pp-.08)<1e-9 and abs(pw+pp+pl-1)<1e-9;assert SCHEMA_VERSION==10 and RUN_MODEL_MIN_GAMES>=450 and CAL_MIN_GAMES>=500;assert "2u" in execution_status({"confidence":7.5,"min_price":1.80,"winamax_eval":{"price":1.50}},"EARLY") and "sous la cote mini" in execution_status({"confidence":7.5,"min_price":1.80,"winamax_eval":{"price":1.50}},"EARLY");assert "2u" in execution_status({"confidence":7.5,"min_price":1.80,"winamax_eval":None},"EARLY");assert displayed_stake_units({"confidence":6.19})==0 and displayed_stake_units({"confidence":6.2})==1 and displayed_stake_units({"confidence":6.99})==1 and displayed_stake_units({"confidence":7.0})==2 and displayed_stake_units({"confidence":7.99})==2 and displayed_stake_units({"confidence":8.0})==min(3,int(MAX_STAKE_UNITS));assert MAX_STAKE_UNITS<3 or (integer_stake_units(.24*UNIT)[0]==0 and integer_stake_units(.25*UNIT)[0]==1 and integer_stake_units(1.49*UNIT)[0]==1 and integer_stake_units(1.50*UNIT)[0]==2 and integer_stake_units(2.49*UNIT)[0]==2 and integer_stake_units(2.50*UNIT)[0]==3);assert round_down_units(1.99*UNIT)[0]<=1 and round_down_units(2.00*UNIT)[0]<=2;print("SELF-TEST MLB BETTING BOT V10 OK")

# ========================== V10.0.5 METHODOLOGY FIXES ==========================
_V10_GAME_CONTEXT_004=game_context
_V10_BUILD_SNAPSHOT_004=build_snapshot
_V10_SELF_TEST_004=v10_self_test

VERSION="10.0.5"
RECOMMENDATION_VERSION="model-first-mainline-calibrated-v11"
V10_STRUCTURAL_CAP_RUNS=max(.10,float(os.getenv("V10_STRUCTURAL_CAP_RUNS","0.75") or .75))

def v1005_component_terms(own_h,opp_p,own_recent,opp_sp,opp_bp,lineup,split,statcast,park,wx,home):
    lg=league_baselines();rpg=num(own_h.get("runsPerGame"),lg["rpg"]);ops=num(own_h.get("ops"),lg["ops"])
    gp=max(1.0,num(opp_p.get("gamesPlayed"),0));runs_allowed=num(opp_p.get("runs"),0)
    opp_ra=runs_allowed/gp if runs_allowed>0 else lg["rpg"]*v10_safe_ratio(num(opp_p.get("era"),lg["era"]),lg["era"],.72,1.35)
    terms=[
        ("season_rpg",.34*math.log(v10_safe_ratio(rpg,lg["rpg"],.70,1.35))),
        ("ops",.20*math.log(v10_safe_ratio(ops,lg["ops"],.82,1.18))),
        ("opp_runs_allowed",.14*math.log(v10_safe_ratio(opp_ra,lg["rpg"],.72,1.38))),
    ]
    if num((own_recent or {}).get("games"),0)>=5:
        terms.append(("recent_rpg",.08*math.log(v10_safe_ratio(num(own_recent.get("runs_pg"),rpg),lg["rpg"],.72,1.38))))
    sip=v10_expected_starter_ip(opp_sp);starter_share=sip/9.0;bullpen_share=1-starter_share
    sp_era=num(opp_sp.get("era"),lg["era"]);sp_whip=num(opp_sp.get("whip"),lg["whip"]);sp_k9=num(opp_sp.get("k9"),8.3);sp_bb9=num(opp_sp.get("bb9"),3.2)
    sp_quality=(sp_era-lg["era"])/1.45+.45*(sp_whip-lg["whip"])/.28+.18*((sp_bb9-3.2)/1.4-(sp_k9-8.3)/2.4)
    terms.append(("opposing_starter",starter_share*clamp(sp_quality,-1.10,1.10)*.23))
    bp_era=num((opp_bp or {}).get("era"),lg["era"]);bp_whip=num((opp_bp or {}).get("whip"),lg["whip"]);bp_load=num((opp_bp or {}).get("load"),.5)
    bp_quality=(bp_era-lg["era"])/1.55+.35*(bp_whip-lg["whip"])/.30+.35*(bp_load-.5)/.60
    terms.append(("opposing_bullpen",bullpen_share*clamp(bp_quality,-1.0,1.2)*.22))
    lineup_ops=(lineup or {}).get("weighted_ops");lineup_count=int(num((lineup or {}).get("count"),0))
    if lineup_ops is not None and lineup_count>=7:
        terms.append(("confirmed_lineup",clamp(lineup_count/9.0,0,1)*.18*clamp((num(lineup_ops,ops)-ops)/.080,-1,1)))
    split_ops=(split or {}).get("_shrunk_ops");split_pa=num((split or {}).get("_pa"),0)
    if split_ops is not None and split_pa>=40:
        terms.append(("platoon_split",clamp(split_pa/250.0,.20,1.0)*.13*clamp((num(split_ops,ops)-ops)/.080,-1,1)))
    xwoba=(statcast or {}).get("xwoba");pa=num((statcast or {}).get("pa"),0)
    if xwoba is not None:
        terms.append(("statcast_xwoba",clamp(pa/1800.0,.25,1.0)*.12*clamp((num(xwoba,.317)-.317)/.045,-1,1)))
    terms.append(("park",.55*math.log(clamp(num(park,1.0),.88,1.16))))
    terms.append(("weather",clamp(num((wx or {}).get("run_adj"),0),-.25,.30)*.10))
    log_mu=math.log(lg["rpg"]);components=[];before=math.exp(log_mu)
    for name,term in terms:
        log_mu+=term;after=math.exp(log_mu);components.append({"name":name,"log_term":round(term,6),"delta_runs":round(after-before,4)});before=after
    pre_clamp=math.exp(log_mu)+(0.08 if home else 0.0)
    if home:components.append({"name":"home_bonus","log_term":None,"delta_runs":0.08})
    return {"league_base":round(lg["rpg"],4),"components":components,"pre_clamp":round(pre_clamp,4),"formula_raw":round(clamp(pre_clamp,2.0,8.2),4),"expected_starter_ip":round(sip,3)}

def v1005_side_diag(ctx,home_side,raw_v10,base_v9):
    if home_side:
        own_h=season_stats(ctx["home_id"],"hitting");opp_p=season_stats(ctx["away_id"],"pitching")
        opp_sp=dict(shrunk_pitcher(ctx.get("away_sp_stats") or {}));opp_sp["gs"]=max(0,num((ctx.get("away_sp_stats") or {}).get("gamesStarted"),0))
        diag=v1005_component_terms(own_h,opp_p,ctx["home_recent"],opp_sp,ctx["away_bp"],ctx["home_lineup"],ctx["home_split"],ctx["home_statcast"],ctx["park"],ctx["weather"],True)
    else:
        own_h=season_stats(ctx["away_id"],"hitting");opp_p=season_stats(ctx["home_id"],"pitching")
        opp_sp=dict(shrunk_pitcher(ctx.get("home_sp_stats") or {}));opp_sp["gs"]=max(0,num((ctx.get("home_sp_stats") or {}).get("gamesStarted"),0))
        diag=v1005_component_terms(own_h,opp_p,ctx["away_recent"],opp_sp,ctx["home_bp"],ctx["away_lineup"],ctx["away_split"],ctx["away_statcast"],ctx["park"],ctx["weather"],False)
    raw_adj=raw_v10-base_v9;applied=clamp(raw_adj,-V10_STRUCTURAL_CAP_RUNS,V10_STRUCTURAL_CAP_RUNS);final=clamp(base_v9+applied,2.0,8.2)
    diag.update({"v9_base":round(base_v9,4),"v10_raw":round(raw_v10,4),"raw_adjustment":round(raw_adj,4),"cap_runs":round(V10_STRUCTURAL_CAP_RUNS,3),"applied_adjustment":round(applied,4),"final_base":round(final,4),"capped":abs(applied-raw_adj)>1e-9})
    return final,diag

def game_context(g):
    ctx=_V10_GAME_CONTEXT_004(g);raw_h=num(ctx.get("base_home"));raw_a=num(ctx.get("base_away"));v9_h=num(ctx.get("base_home_v9"),raw_h);v9_a=num(ctx.get("base_away_v9"),raw_a)
    h,dh=v1005_side_diag(ctx,True,raw_h,v9_h);a,da=v1005_side_diag(ctx,False,raw_a,v9_a)
    ctx["base_home_v10_raw"]=raw_h;ctx["base_away_v10_raw"]=raw_a
    ctx["structural_adj_home_raw"]=raw_h-v9_h;ctx["structural_adj_away_raw"]=raw_a-v9_a
    ctx["structural_adj_home"]=h-v9_h;ctx["structural_adj_away"]=a-v9_a
    ctx["base_home"]=h;ctx["base_away"]=a;ctx["run_diagnostics_home"]=dh;ctx["run_diagnostics_away"]=da;ctx["structural_cap_runs"]=V10_STRUCTURAL_CAP_RUNS;ctx["base_engine"]="advanced-baseball-v10-safe-cap"
    logging.info("V10 RUN SAFE | %s @ %s | H %.2f raw %.2f -> %.2f (%+.2f cap %.2f) | A %.2f raw %.2f -> %.2f (%+.2f cap %.2f)",ctx["away"],ctx["home"],v9_h,raw_h,h,h-v9_h,V10_STRUCTURAL_CAP_RUNS,v9_a,raw_a,a,a-v9_a,V10_STRUCTURAL_CAP_RUNS)
    return ctx

def build_snapshot(result,rec):
    snap=_V10_BUILD_SNAPSHOT_004(result,rec);ctx=result.get("ctx") or {}
    snap["structural_cap_runs"]=round(V10_STRUCTURAL_CAP_RUNS,3)
    snap["base_home_v10_raw"]=round(num(ctx.get("base_home_v10_raw"),ctx.get("base_home")),4);snap["base_away_v10_raw"]=round(num(ctx.get("base_away_v10_raw"),ctx.get("base_away")),4)
    snap["run_diagnostics_home"]=ctx.get("run_diagnostics_home");snap["run_diagnostics_away"]=ctx.get("run_diagnostics_away")
    return snap

def v10_settled_predictions(hist,market=None,phase=None):
    best={}
    for rec in hist.values():
        gid=rec.get("game_pk")
        for p in rec.get("predictions",[]):
            if p.get("result") not in ("W","L","P"):continue
            if market and p.get("market")!=market:continue
            if phase and p.get("phase")!=phase:continue
            pgid=p.get("game_pk",gid);key=(pgid,p.get("market"),p.get("phase")) if phase else (pgid,p.get("market"))
            old=best.get(key)
            if old is None or (str(p.get("analyzed_at","")),str(p.get("prediction_id","")))>(str(old.get("analyzed_at","")),str(old.get("prediction_id",""))):best[key]=p
    return sorted(best.values(),key=lambda x:(x.get("analyzed_at",""),x.get("prediction_id","")))

def v10_performance_report(hist):
    xs=v10_settled_predictions(hist);by_phase={ph:v10_prediction_metrics(v10_settled_predictions(hist,phase=ph)) for ph in V10_PHASES}
    return {"overall":v10_prediction_metrics(xs),"unique_games":len({p.get("game_pk") for p in xs}),"by_market":{m:v10_prediction_metrics([p for p in xs if p.get("market")==m]) for m in V10_MARKETS},"by_phase":by_phase,"by_confidence":{f"{lo}-{lo+1}":v10_prediction_metrics([p for p in xs if lo<=num(p.get("confidence"))<lo+1]) for lo in (4,5,6,7,8,9)}}

def performance(hist):
    out=_V9_PERFORMANCE(hist);report=v10_performance_report(hist);out["prediction_report"]=report;o=report["overall"]
    logging.info("V10 PRED METRICS DEDUP | games=%d predictions=%d WL=%d pushes=%d accuracy=%s Brier=%s LogLoss=%s",report["unique_games"],o["n"],o["n_wl"],o["pushes"],pct(o["accuracy"]) if o["accuracy"] is not None else "-",f"{o['brier']:.4f}" if o["brier"] is not None else "-",f"{o['logloss']:.4f}" if o["logloss"] is not None else "-")
    return out

def execution_status(rec,phase):
    if not rec:return "⚠️ Pas de recommandation modèle exploitable."
    e=rec.get("winamax_eval");minimum=num(rec.get("min_price"),0);force=displayed_stake_units(rec);force_eur=round(force*UNIT,2);phase_txt=f" • phase {phase}" if phase else ""
    force_txt=f"🔥 **Force modèle : {force}u**"+(f" = {force_eur:.2f} €" if force>0 else "")
    actual=0
    if not e or num(e.get("price"),0)<=1:
        price_txt=f"ℹ️ **Winamax : cote absente du flux** • cote mini **{minimum:.2f}**{phase_txt}"
    else:
        price=num(e.get("price"),0)
        if price+1e-9>=minimum:
            actual=force;price_txt=f"✅ **Winamax {price:.2f}** • cote mini **{minimum:.2f}** atteinte{phase_txt}"
        else:price_txt=f"⚠️ **Winamax {price:.2f} sous la cote mini {minimum:.2f}**{phase_txt}"
    actual_eur=round(actual*UNIT,2);stake_txt=f"💰 **Mise recommandée : {actual}u"+(f" = {actual_eur:.2f} €" if actual>0 else "")+"**"
    return f"{price_txt}\n{force_txt} • basée sur la confiance modèle\n{stake_txt} • prix utilisé uniquement comme filtre d'exécution"

def v10_self_test():
    _V10_SELF_TEST_004()
    assert V10_STRUCTURAL_CAP_RUNS>0
    assert abs(clamp(2.0,-V10_STRUCTURAL_CAP_RUNS,V10_STRUCTURAL_CAP_RUNS))<=V10_STRUCTURAL_CAP_RUNS+1e-9
    fake={"1":{"game_pk":1,"predictions":[{"game_pk":1,"phase":"EARLY","market":"ML","analyzed_at":"2026-08-11T10:00:00+00:00","prediction_id":"a","p_model":.60,"result":"W"},{"game_pk":1,"phase":"EARLY","market":"ML","analyzed_at":"2026-08-11T11:00:00+00:00","prediction_id":"b","p_model":.61,"result":"W"},{"game_pk":1,"phase":"FINAL","market":"ML","analyzed_at":"2026-08-11T12:00:00+00:00","prediction_id":"c","p_model":.62,"result":"W"}]}}
    assert len(v10_settled_predictions(fake))==1 and v10_settled_predictions(fake)[0]["prediction_id"]=="c"
    assert len(v10_settled_predictions(fake,phase="EARLY"))==1 and v10_settled_predictions(fake,phase="EARLY")[0]["prediction_id"]=="b"
    low=execution_status({"confidence":7.5,"min_price":1.80,"winamax_eval":{"price":1.50}},"EARLY");good=execution_status({"confidence":7.5,"min_price":1.80,"winamax_eval":{"price":1.85}},"EARLY")
    assert "Force modèle : 2u" in low and "Mise recommandée : 0u" in low and "Mise recommandée : 2u" in good
    print("SELF-TEST MLB BETTING BOT V10.0.5 OK")

# ======================== V10.0.6 RESIDUAL RUN SEED =========================
# The historical walk-forward dataset is used ONLY for the FINAL-phase residual
# run model. Calibration, market skill, confidence, dispersion, ledger, Winamax,
# EV/Kelly and staking continue to use the real live history exclusively.
_V1005_TRAINING_GAMES_PHASE=v10_training_games_phase
_V1005_RUN_STATE_PHASE=v10_run_state_phase
_V1005_RUN_MODEL_STATE=run_model_state
_V1005_ANALYZE_BASE=analyze_base
_V1005_BUILD_SNAPSHOT_FINAL=build_snapshot
_V1005_SELF_TEST_FINAL=v10_self_test

VERSION="10.0.6"
RUN_SEED_VERSION="backtest-2026-walkforward-final-v1"
RUN_SEED_FILE=Path(os.getenv("RUN_SEED_FILE","data/mlb_run_seed_2026.jsonl"))
RUN_SEED_ENABLED=os.getenv("RUN_SEED_ENABLED","1").strip().lower() not in ("0","false","no","off")
_V1006_RUN_SEED=None

def v1006_load_run_seed():
    global _V1006_RUN_SEED
    if _V1006_RUN_SEED is not None:return _V1006_RUN_SEED
    if not RUN_SEED_ENABLED:
        _V1006_RUN_SEED=[];return _V1006_RUN_SEED
    if not RUN_SEED_FILE.exists():
        logging.warning("V10.0.6 run seed absent: %s — fallback live-only",RUN_SEED_FILE)
        _V1006_RUN_SEED=[];return _V1006_RUN_SEED
    rows=[];seen=set();bad=[]
    for lineno,line in enumerate(RUN_SEED_FILE.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        try:
            r=json.loads(line);gid=str(r["game_pk"])
            if gid in seen:continue
            fh=[float(x) for x in r["run_features_home"]];fa=[float(x) for x in r["run_features_away"]]
            if r.get("phase")!="FINAL" or len(fh)!=17 or len(fa)!=17:raise ValueError("invalid phase/features")
            vals=[num(r["base_home"],float("nan")),num(r["base_away"],float("nan")),*fh,*fa,float(r["home_score"]),float(r["away_score"])]
            if not all(math.isfinite(x) for x in vals):raise ValueError("non-finite seed value")
            rows.append({"game_pk":gid,"game_date":r.get("game_date",""),"home":r.get("home"),"away":r.get("away"),"home_score":float(r["home_score"]),"away_score":float(r["away_score"]),"base_home":float(r["base_home"]),"base_away":float(r["base_away"]),"run_features_home":fh,"run_features_away":fa})
            seen.add(gid)
        except Exception as e:bad.append((lineno,str(e)))
    if bad:raise RuntimeError(f"Run seed V10.0.6 invalide: {len(bad)} ligne(s), première={bad[0]}")
    rows.sort(key=lambda r:(r["game_date"],r["game_pk"]));_V1006_RUN_SEED=rows
    logging.info("V10.0.6 RUN SEED | %d matchs FINAL chargés depuis %s",len(rows),RUN_SEED_FILE)
    return rows

def v1006_live_phase_ids(hist,phase):
    ids=set()
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        if v10_phase_snapshot(r,phase):ids.add(str(r.get("game_pk")))
    return ids

def v10_training_games_phase(hist,phase):
    live=_V1005_TRAINING_GAMES_PHASE(hist,phase)
    if phase!="FINAL" or not RUN_SEED_ENABLED:return live
    live_ids=v1006_live_phase_ids(hist,"FINAL");seed=[]
    for r in v1006_load_run_seed():
        if r["game_pk"] in live_ids:continue
        snap={"run_features_home":r["run_features_home"],"run_features_away":r["run_features_away"],"base_home":r["base_home"],"base_away":r["base_away"],"run_seed_version":RUN_SEED_VERSION,"run_seed":True}
        seed.append((r["game_date"],snap,r["home_score"],r["away_score"]))
    out=seed+live;out.sort(key=lambda x:x[0]);return out

def v10_run_state_phase(hist,phase):
    live_n=len(_V1005_TRAINING_GAMES_PHASE(hist,phase));state=_V1005_RUN_STATE_PHASE(hist,phase)
    state["live_n"]=live_n;state["seed_n"]=max(0,state.get("n",0)-live_n) if phase=="FINAL" else 0
    state["run_seed_version"]=RUN_SEED_VERSION if state["seed_n"] else None
    state["training_source"]="backtest-seed+live" if state["seed_n"] else "live-only"
    return state

def run_model_state(hist):
    out=_V1005_RUN_MODEL_STATE(hist);final=(out.get("phase_states") or {}).get("FINAL",{})
    out["seed_n"]=final.get("seed_n",0);out["live_n"]=sum((x or {}).get("live_n",0) for x in (out.get("phase_states") or {}).values())
    if final.get("seed_n"):
        logging.info("V10.0.6 RUN TRAINING | FINAL seed=%d live=%d total=%d active=%s RMSE %.3f/%.3f gainProb=%.2f",final.get("seed_n",0),final.get("live_n",0),final.get("n",0),final.get("active",False),num(final.get("rmse_model")),num(final.get("rmse_base")),num(final.get("gain_prob")))
    return out

def analyze_base(g,event,delta,states,hist):
    r=_V1005_ANALYZE_BASE(g,event,delta,states,hist);phase=r.get("phase");st=((states[0].get("phase_states") or {}).get(phase) or {})
    r["run_seed_n"]=st.get("seed_n",0);r["run_live_n"]=st.get("live_n",0);r["run_training_source"]=st.get("training_source","live-only");r["run_seed_version"]=st.get("run_seed_version")
    return r

def build_snapshot(result,rec):
    snap=_V1005_BUILD_SNAPSHOT_FINAL(result,rec);snap["run_training_source"]=result.get("run_training_source","live-only");snap["run_seed_n"]=int(num(result.get("run_seed_n"),0));snap["run_live_n"]=int(num(result.get("run_live_n"),0));snap["run_seed_version"]=result.get("run_seed_version");return snap

def v10_self_test():
    _V1005_SELF_TEST_FINAL()
    seed=v1006_load_run_seed()
    if RUN_SEED_ENABLED and RUN_SEED_FILE.exists():
        assert len(seed)>=1700
        assert len({r["game_pk"] for r in seed})==len(seed)
        assert all(len(r["run_features_home"])==17 and len(r["run_features_away"])==17 for r in seed)
        # Historical reconstruction is FINAL-only: EARLY/LATE must remain live-only.
        assert v10_training_games_phase({},"EARLY")==[] and v10_training_games_phase({},"LATE")==[]
        final=v10_training_games_phase({},"FINAL");assert len(final)==len(seed)
        # A genuine live FINAL snapshot with the same game_pk replaces, never duplicates, its seed row.
        r0=seed[0];fake_snap={"seconds_to_game":3600,"phase":"FINAL","feature_version":FEATURE_VERSION,"model_version":MODEL_VERSION,"distribution_version":DIST_VERSION,"run_features_home":r0["run_features_home"],"run_features_away":r0["run_features_away"],"base_home":r0["base_home"],"base_away":r0["base_away"]}
        fake={r0["game_pk"]:{"game_pk":r0["game_pk"],"game_date":r0["game_date"],"status":"FINAL","home_score":r0["home_score"],"away_score":r0["away_score"],"snapshots":[fake_snap]}}
        assert len(v10_training_games_phase(fake,"FINAL"))==len(seed)
        # Betting/calibration paths receive the live history only; seed rows are never injected there.
        assert v10_ml_cal_state_phase({},"FINAL","base-runs")["n"]==0
        assert v10_skill_state_phase({},"FINAL","base-runs")["n"]==0
        assert v10_market_cal_state({},"ML","FINAL")["n"]==0
    print("SELF-TEST MLB BETTING BOT V10.0.6 OK")

# ======================= V10.0.7 SELECTIVE BETTING ========================
# Risk layer built from the 2026 walk-forward evidence. It does NOT change the
# baseball direction engine. It converts raw probabilities into a conservative
# effective probability for betting decisions, caps residual corrections,
# validates the residual challenger on a recent holdout, and limits the official
# slate to at most 3 bets / 4 units / 1 bet per game. Top-3 messages remain
# informational; only the PLAN OFFICIEL is considered playable.
_V1006_SELF_TEST=v10_self_test
_V1006_RUN_STATE_PHASE=v10_run_state_phase
_V1006_ANALYZE_BASE=analyze_base
_V1006_ATTACH_MODEL_RECS=attach_model_recommendations
_V1006_ALLOCATE_PORTFOLIO=allocate_portfolio
_V1006_EXECUTION_STATUS=execution_status
_V1006_BUILD_SNAPSHOT=build_snapshot

VERSION="10.0.7"
RECOMMENDATION_VERSION="selective-effective-prob-v12"
SELECTION_VERSION="slate-risk-v1"
V1007_RESIDUAL_CAP_RUNS=max(.10,float(os.getenv("V1007_RESIDUAL_CAP_RUNS","0.65") or .65))
V1007_MAX_DAILY_UNITS=max(1,int(os.getenv("V1007_MAX_DAILY_UNITS","4") or 4))
V1007_MAX_OFFICIAL_BETS=max(1,min(3,int(os.getenv("V1007_MAX_OFFICIAL_BETS","3") or 3)))
V1007_MAX_BETS_PER_GAME=1
V1007_MIN_CONF=max(6.0,float(os.getenv("V1007_MIN_CONF","6.5") or 6.5))
V1007_MIN_QUALITY=max(.50,float(os.getenv("V1007_MIN_QUALITY","0.70") or .70))
V1007_MIN_REFS=max(1,int(os.getenv("V1007_MIN_REFS","2") or 2))
V1007_MIN_EFFECTIVE={"ML":.60,"RUNLINE":.59,"TOTAL":.59}
V1007_PREMIUM_EFFECTIVE=.64
V1007_PREMIUM_CONF=7.8
V1007_PREMIUM_QUALITY=.80
V1007_PREMIUM_REFS=3
V1007_RECENT_HOLDOUT=150
V1007_RECENT_GAIN_PROB=.80
V1007_ML_EMPIRICAL_ANCHORS=((.500,.500),(.524,.507),(.574,.523),(.623,.554),(.669,.592),(.718,.648),(.750,.660))
_V1007_LAST_SLATE={"score":0.0,"grade":"FAIBLE","max_bets":0,"official_count":0,"units":0}

def v1007_interp(x,anchors):
    x=clamp(num(x,.5),anchors[0][0],anchors[-1][0])
    for i in range(1,len(anchors)):
        x0,y0=anchors[i-1];x1,y1=anchors[i]
        if x<=x1:
            t=(x-x0)/(x1-x0) if x1>x0 else 0
            return y0+t*(y1-y0)
    return anchors[-1][1]

def v1007_effective_probability(p,market,phase):
    p=clamp(num(p,.5),.5,.999)
    phase=str(phase or "EARLY").upper()
    if market=="ML":
        q=v1007_interp(p,V1007_ML_EMPIRICAL_ANCHORS)
        phase_factor={"EARLY":.78,"LATE":.88,"FINAL":1.0}.get(phase,.78)
        q=.5+(q-.5)*phase_factor
    else:
        phase_factor={"EARLY":.66,"LATE":.74,"FINAL":.82}.get(phase,.66)
        q=.5+(p-.5)*phase_factor
        q=min(q,.68)
    return clamp(q,.5,.72)

def project_runs(ctx,state):
    h=num(ctx.get("base_home"),4.45);a=num(ctx.get("base_away"),4.45);rh=ra=0.0;raw_h=raw_a=0.0
    if state.get("active") and state.get("model"):
        raw_h=linear_predict(state["model"],ctx["run_features_home"]);raw_a=linear_predict(state["model"],ctx["run_features_away"])
        rh=clamp(raw_h,-V1007_RESIDUAL_CAP_RUNS,V1007_RESIDUAL_CAP_RUNS);ra=clamp(raw_a,-V1007_RESIDUAL_CAP_RUNS,V1007_RESIDUAL_CAP_RUNS)
        h+=rh;a+=ra
    ctx["residual_home_raw"]=round(raw_h,4);ctx["residual_away_raw"]=round(raw_a,4);ctx["residual_home_applied"]=round(rh,4);ctx["residual_away_applied"]=round(ra,4);ctx["residual_cap_runs"]=V1007_RESIDUAL_CAP_RUNS
    return clamp(h,2,8),clamp(a,2,8)

def v1007_recent_residual_guard(hist,state,phase):
    state=dict(state)
    state.update({"recent_guard_pass":None,"recent_guard_n":0,"recent_rmse_base":None,"recent_rmse_model":None,"recent_gain_prob":0.0})
    if phase!="FINAL" or not state.get("active"):return state
    games=v10_training_games_phase(hist,"FINAL");hold=min(V1007_RECENT_HOLDOUT,max(60,int(len(games)*.12)))
    if len(games)<RUN_MODEL_MIN_GAMES+hold or hold<60:return state
    train=games[:-hold];val=games[-hold:];rows=[]
    for _,s,hs,as_ in train:rows += [(s["run_features_home"],hs-num(s["base_home"])),(s["run_features_away"],as_-num(s["base_away"]))]
    if not rows:return state
    m=fit_linear(rows);base_losses=[];new_losses=[]
    for _,s,hs,as_ in val:
        ph=num(s["base_home"])+clamp(linear_predict(m,s["run_features_home"]),-V1007_RESIDUAL_CAP_RUNS,V1007_RESIDUAL_CAP_RUNS)
        pa=num(s["base_away"])+clamp(linear_predict(m,s["run_features_away"]),-V1007_RESIDUAL_CAP_RUNS,V1007_RESIDUAL_CAP_RUNS)
        base_losses += [rmse_loss(num(s["base_home"]),hs),rmse_loss(num(s["base_away"]),as_)]
        new_losses += [rmse_loss(ph,hs),rmse_loss(pa,as_)]
    rb=math.sqrt(mean(base_losses));rn=math.sqrt(mean(new_losses));gp=bootstrap_gain_prob(base_losses,new_losses)
    passed=rn+.01<rb and gp>=V1007_RECENT_GAIN_PROB
    state.update({"recent_guard_pass":passed,"recent_guard_n":hold,"recent_rmse_base":rb,"recent_rmse_model":rn,"recent_gain_prob":gp})
    if not passed:
        state["active"]=False;state["model"]=None;state["training_source"]=(state.get("training_source") or "")+"+recent-guard-disabled"
    logging.info("V10.0.7 RESIDUAL GUARD | phase=%s n=%d pass=%s RMSE %.3f/%.3f gainProb=%.2f",phase,hold,passed,rn,rb,gp)
    return state

def v10_run_state_phase(hist,phase):
    return v1007_recent_residual_guard(hist,_V1006_RUN_STATE_PHASE(hist,phase),phase)

def analyze_base(g,event,delta,states,hist):
    r=_V1006_ANALYZE_BASE(g,event,delta,states,hist);ctx=r["ctx"];disp=states[1]
    p_struct=ml_prob(num(ctx.get("base_home")),num(ctx.get("base_away")),disp["alpha_home"],disp["alpha_away"],r["extra_home"])
    p_resid=num(r.get("p_model_raw"),p_struct);d=abs(p_resid-p_struct);flip=(p_resid-.5)*(p_struct-.5)<0
    alert="FLIP" if flip else "HIGH" if d>=.06 else "WATCH" if d>=.04 else "OK"
    r.update({"p_structural_raw":p_struct,"stability_delta":d,"stability_alert":alert})
    logging.info("V10.0.7 STABILITY | %s @ %s | structural %.3f residual %.3f delta %.3f alert=%s",ctx["away"],ctx["home"],p_struct,p_resid,d,alert)
    return r

def v1007_apply_effective(rec,result):
    if not rec:return None
    phase=result.get("phase","EARLY");market=rec.get("market");pe=v1007_effective_probability(rec.get("p_model"),market,phase);pp=clamp(num(rec.get("p_push"),0),0,.95);mass=1-pp;pw=mass*pe;pl=mass*(1-pe)
    rec["p_effective"]=pe;rec["p_effective_win"]=pw;rec["p_effective_loss"]=pl;rec["fair_effective"]=(1-pp)/pw if pw>0 else 99;rec["min_price_effective"]=min_acceptable_price(pw,pp,pl);rec["selection_version"]=SELECTION_VERSION;rec["stability_alert"]=result.get("stability_alert","OK");rec["stability_delta"]=result.get("stability_delta",0)
    e=rec.get("winamax_eval")
    if e:
        price=num(e.get("price"),0);np=pw+pl;pcond=pw/np if np else .5
        e.update({"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":pcond,"fair":rec["fair_effective"],"min_price":rec["min_price_effective"],"effective_probability":pe,"effective_probability_source":"2026-walkforward-shrinkage","effective_min_price":rec["min_price_effective"],"edge":pcond-1/price if price>1 else -1,"ev":pw*price+pp-1 if price>1 else -1,"official_v1007":True,"official_selected":False,"official_units":0,"official_reason":"non évalué"})
    return rec

def attach_model_recommendations(result):
    recs=_V1006_ATTACH_MODEL_RECS(result)
    for rec in recs.values():v1007_apply_effective(rec,result)
    return recs

def v1007_starters_ok(ctx):
    return all(str(ctx.get(k,"Non annoncé")).strip().lower() not in ("","non annoncé","none") for k in ("home_sp","away_sp"))

def v1007_profile(rec):
    if rec["market"]=="TOTAL":return "TOTAL_OVER" if str(rec.get("name","")).lower()=="over" else "TOTAL_UNDER"
    mp=rec.get("p_market");e=rec.get("winamax_eval") or {};fav=(num(mp)>=.5) if mp is not None else num(e.get("price"),2.01)<2
    return "SIDE_FAVORITE" if fav else "SIDE_UNDERDOG"

def v1007_candidate(result,rec,require_phase=True):
    reasons=[];phase=result.get("phase","EARLY");market=rec.get("market");pe=num(rec.get("p_effective"),.5);conf=num(rec.get("confidence"),0);q=num(result.get("quality"),0);refs=int(num(rec.get("refs"),0));e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);minimum=num(rec.get("min_price_effective"),99);alert=result.get("stability_alert","OK")
    if pe<V1007_MIN_EFFECTIVE.get(market,.60):reasons.append(f"proba effective {pe*100:.1f}% trop faible")
    if conf<V1007_MIN_CONF:reasons.append(f"confiance {conf:.1f}< {V1007_MIN_CONF:.1f}")
    if q<V1007_MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10 insuffisante")
    if refs<V1007_MIN_REFS:reasons.append(f"seulement {refs} book(s) référence")
    if alert in ("HIGH","FLIP"):reasons.append(f"instabilité modèle {alert}")
    if price<=1:reasons.append("cote Winamax absente")
    elif price+1e-9<minimum:reasons.append(f"Winamax {price:.2f}<mini effective {minimum:.2f}")
    if require_phase and phase=="EARLY":reasons.append("phase EARLY: pré-sélection uniquement")
    surplus=(price/minimum-1) if price>1 and minimum>1 else 0
    score=60+120*(pe-.58)+4*(conf-6.5)+15*(q-.70)+2*min(refs,4)+min(3,max(0,surplus)*30)
    if alert=="WATCH":score-=6
    score=clamp(score,0,100)
    premium=(phase=="FINAL" and pe>=V1007_PREMIUM_EFFECTIVE and conf>=V1007_PREMIUM_CONF and q>=V1007_PREMIUM_QUALITY and refs>=V1007_PREMIUM_REFS and result.get("stability_alert")=="OK" and result["ctx"]["home_lineup"].get("count",0)>=8 and result["ctx"]["away_lineup"].get("count",0)>=8 and v1007_starters_ok(result["ctx"]) and price>=minimum*1.01)
    units=2 if premium else 1
    return {"eligible":not reasons,"reasons":reasons,"score":score,"units":units,"profile":v1007_profile(rec),"result":result,"rec":rec,"price":price,"minimum":minimum,"premium":premium}

def v1007_build_slate(results,require_phase=True):
    pool=[]
    for r in results:
        for rec in (r.get("model_recs") or {}).values():
            if not rec:continue
            c=v1007_candidate(r,rec,require_phase=require_phase)
            if c["eligible"]:pool.append(c)
    pool.sort(key=lambda c:(c["score"],num(c["rec"].get("p_effective")),num(c["rec"].get("confidence"))),reverse=True)
    unique=[];seen=set()
    for c in pool:
        gid=str(c["result"]["game_pk"])
        if gid in seen:continue
        unique.append(c);seen.add(gid)
    top=unique[:3];slate_score=mean([c["score"] for c in top]) if top else 0.0
    max_bets=0
    thresholds=(70,72,74)
    for i,c in enumerate(top[:V1007_MAX_OFFICIAL_BETS]):
        if c["score"]>=thresholds[i]:max_bets=i+1
        else:break
    grade="FORT" if slate_score>=82 else "BON" if slate_score>=76 else "MOYEN" if slate_score>=70 else "FAIBLE"
    return {"pool":pool,"unique":unique,"score":round(slate_score,1),"grade":grade,"max_bets":max_bets}

def allocate_portfolio(results):
    global _V10_LAST_PORTFOLIO,_V1007_LAST_SLATE
    if not results or not all("model_recs" in r for r in results):return _V1006_ALLOCATE_PORTFOLIO(results)
    for r in results:
        for e in r.get("evals",[]):e.update({"selected":False,"units":0.0,"stake_eur":0.0})
        for rec in (r.get("model_recs") or {}).values():
            if rec and rec.get("winamax_eval"):
                rec["winamax_eval"].update({"official_v1007":True,"official_selected":False,"official_units":0,"official_reason":"hors plan officiel"})
    slate=v1007_build_slate(results,True);preview=v1007_build_slate(results,False);chosen=[];used_games=set();profiles={};units_used=0
    thresholds=(70,72,74)
    for c in slate["pool"]:
        if len(chosen)>=slate["max_bets"] or len(chosen)>=V1007_MAX_OFFICIAL_BETS:break
        if c["score"]<thresholds[len(chosen)]:break
        gid=str(c["result"]["game_pk"]);profile=c["profile"]
        if gid in used_games:continue
        if profiles.get(profile,0)>=2:
            c["rec"]["winamax_eval"]["official_reason"]="corrélation: déjà 2 paris du même profil";continue
        units=c["units"]
        if units_used+units>V1007_MAX_DAILY_UNITS:
            if units==2 and units_used+1<=V1007_MAX_DAILY_UNITS:units=1
            else:
                c["rec"]["winamax_eval"]["official_reason"]="plafond quotidien 4u";continue
        e=c["rec"]["winamax_eval"];e.update({"selected":True,"official_selected":True,"official_units":units,"units":float(units),"stake_eur":round(units*UNIT,2),"qualified":True,"reason":"OK V10.0.7","portfolio_reason":"PARI OFFICIEL V10.0.7","official_reason":"retenu dans le plan officiel","candidate_units":float(units),"candidate_stake_eur":round(units*UNIT,2)})
        chosen.append(c);used_games.add(gid);profiles[profile]=profiles.get(profile,0)+1;units_used+=units
    chosen_ids={id(c["rec"]) for c in chosen}
    for c in slate["pool"]:
        if id(c["rec"]) not in chosen_ids and c["rec"].get("winamax_eval") and c["rec"]["winamax_eval"].get("official_reason")=="hors plan officiel":c["rec"]["winamax_eval"]["official_reason"]="non retenu par le Slate Score / limite 0-3 paris"
    early_preview=[];seen=set()
    for c in preview["pool"]:
        if c["result"].get("phase")!="EARLY" or c["score"]<70:continue
        gid=str(c["result"]["game_pk"])
        if gid in seen:continue
        c["rec"]["winamax_eval"]["official_preview_units"]=1;early_preview.append(c);seen.add(gid)
        if len(early_preview)>=3:break
    allocated=round(units_used*UNIT,2);cap=round(V1007_MAX_DAILY_UNITS*UNIT,2)
    _V1007_LAST_SLATE={"score":slate["score"],"grade":slate["grade"],"max_bets":slate["max_bets"],"official_count":len(chosen),"units":units_used,"preview_count":len(early_preview)}
    _V10_LAST_PORTFOLIO={"daily_cap":cap,"allocated":allocated,"remaining":round(cap-allocated,2),"game_cap":round(2*UNIT,2),"slate_score":slate["score"],"slate_grade":slate["grade"],"official_count":len(chosen),"official_units":units_used}
    for r in results:r["slate_score"]=slate["score"];r["slate_grade"]=slate["grade"]
    logging.info("V10.0.7 OFFICIAL SLATE | score=%.1f grade=%s max=%d selected=%d units=%du/%du",slate["score"],slate["grade"],slate["max_bets"],len(chosen),units_used,V1007_MAX_DAILY_UNITS)
    return _V10_LAST_PORTFOLIO

def execution_status(rec,phase):
    if not rec:return "⚠️ Pas de recommandation modèle exploitable."
    e=rec.get("winamax_eval")
    if not e or "official_v1007" not in e:return _V1006_EXECUTION_STATUS(rec,phase)
    raw=num(rec.get("p_model"),.5);eff=num(rec.get("p_effective"),raw);minimum=num(rec.get("min_price_effective"),rec.get("min_price",99));price=num(e.get("price"),0);force=displayed_stake_units(rec)
    price_txt=(f"ℹ️ **Winamax : cote absente** • mini effective **{minimum:.2f}**" if price<=1 else f"✅ **Winamax {price:.2f}** ≥ mini effective **{minimum:.2f}**" if price+1e-9>=minimum else f"⚠️ **Winamax {price:.2f}** < mini effective **{minimum:.2f}**")
    force_note=f"🔥 Force modèle **{force}u** • brut {pct(raw)} → effective **{pct(eff)}**"
    if force>=3:force_note+=" • 3u désactivé en V10.0.7"
    if e.get("official_selected"):
        u=int(num(e.get("official_units"),1));return f"{price_txt}\n{force_note}\n✅ **PARI OFFICIEL V10.0.7 — {u}u = {u*UNIT:.2f} €**"
    if phase=="EARLY" and e.get("official_preview_units"):
        return f"{price_txt}\n{force_note}\n👀 **PRÉ-SÉLECTION EARLY — cible 1u si confirmée LATE/FINAL** • 0u officiel maintenant"
    return f"{price_txt}\n{force_note}\n⛔ **0u OFFICIEL** • {e.get('official_reason','non retenu par le plan officiel')}"

def model_rec_text(rec):
    if not rec:return "Aucune recommandation modèle suffisamment définie."
    pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if rec["market"]=="RUNLINE" else f" {rec['point']:g}");mp=pct(rec.get("p_market")) if rec.get("p_market") is not None else "N/A";gap=f"{num(rec.get('market_gap'))*100:+.1f} pts" if rec.get("market_gap") is not None else "N/A";emoji,band,_=confidence_band(rec["confidence"]);eff=num(rec.get("p_effective"),rec.get("p_model",.5));fair=num(rec.get("fair_effective"),rec.get("fair",99));minimum=num(rec.get("min_price_effective"),rec.get("min_price",99));stab=rec.get("stability_alert","OK")
    return f"**{rec['name']}{pt}** • modèle brut **{pct(rec['p_model'])}** → effective **{pct(eff)}** • marché réf. {mp} • écart {gap}\nFair effective **{fair:.2f}** • cote mini effective **{minimum:.2f}** • stabilité **{stab}** • {emoji} **{rec['confidence']:.1f}/10 — {band}**"

def v1007_selected_items(results):
    out=[]
    for r in results:
        for rec in (r.get("model_recs") or {}).values():
            e=(rec or {}).get("winamax_eval") if rec else None
            if e and e.get("official_selected"):out.append({"result":r,"rec":rec,"score":num(rec.get("p_effective"),.5)*100+num(rec.get("confidence"))})
    return sorted(out,key=lambda x:x["score"],reverse=True)

def plan_pick_text(item,index=None):
    r=item["result"];rec=item["rec"];e=rec.get("winamax_eval") or {};pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if rec["market"]=="RUNLINE" else f" {rec['point']:g}");label="ML" if rec["market"]=="ML" else "RL" if rec["market"]=="RUNLINE" else "TOTAL";u=int(num(e.get("official_units"),0));prefix=f"**#{index}** " if index is not None else "• "
    return f"{prefix}✅ **{rec['name']}{pt} [{label}] — {u}u = {u*UNIT:.2f} €**\n{r['ctx']['away']} @ {r['ctx']['home']} • {r['phase']} • brut {pct(rec['p_model'])} → effective **{pct(rec['p_effective'])}**\nConfiance **{rec['confidence']:.1f}/10** • qualité {r['quality']*10:.1f}/10 • mini effective {rec['min_price_effective']:.2f} • Winamax {num(e.get('price')):.2f}"

def build_daily_plan(results):return v1007_selected_items(results),[]

def send_daily_plan(results):
    official=v1007_selected_items(results);simples="\n\n".join(plan_pick_text(x,i+1) for i,x in enumerate(official)) if official else "**AUCUN PARI OFFICIEL.** Le bot préfère 0 pari à un pari marginal."
    preview=v1007_build_slate(results,False);pre=[];seen=set()
    for c in preview["pool"]:
        if c["result"].get("phase")!="EARLY":continue
        gid=str(c["result"]["game_pk"])
        if gid in seen:continue
        rec=c["rec"];e=rec.get("winamax_eval") or {};pt="" if rec.get("point") is None else (f" {rec['point']:+g}" if rec["market"]=="RUNLINE" else f" {rec['point']:g}")
        pre.append(f"• 👀 **{rec['name']}{pt} [{rec['market']}]** • effective {pct(rec['p_effective'])} • conf {rec['confidence']:.1f}/10 • cible **1u max** si confirmée • Winamax {num(e.get('price')):.2f}");seen.add(gid)
        if len(pre)>=3:break
    pretxt="\n".join(pre) if pre else "Aucune pré-sélection EARLY suffisamment forte."
    slate=f"**{_V1007_LAST_SLATE.get('score',0):.1f}/100 — {_V1007_LAST_SLATE.get('grade','FAIBLE')}** • {_V1007_LAST_SLATE.get('official_count',0)} pari(s) officiel(s) • {_V1007_LAST_SLATE.get('units',0)}u/{V1007_MAX_DAILY_UNITS}u"
    return send_embed("🎟️ PLAN OFFICIEL V10.0.7 — 0 À 3 PARIS",[("📊 Slate Score",slate),("✅ PARIS OFFICIELS",simples),("👀 PRÉ-SÉLECTIONS EARLY",pretxt),("🚫 Combiné","**Désactivé temporairement** en V10.0.7 : priorité à la validation des simples et à la réduction de variance."),("🛡️ Discipline","Maximum **3 paris**, **4u/jour**, **1 pari/match**, **2u uniquement premium FINAL**, **aucun 3u**. Les Top 3 sont informatifs et ne sont pas des paris officiels.")],5763719)

def send_top_messages(results,state):
    ok=True
    for market,title in (("ML","🔎 TOP 3 MONEYLINE — INFORMATIF"),("RUNLINE","🔎 TOP 3 RUN LINE — INFORMATIF"),("TOTAL","🔎 TOP 3 TOTAUX — INFORMATIF")):
        xs=[]
        for r in results:
            rec=(r.get("model_recs") or {}).get(market)
            if rec:xs.append((r,rec))
        xs=sorted(xs,key=lambda x:(num(x[1].get("p_effective"),.5),num(x[1].get("confidence"))),reverse=True)[:3];blocks=[]
        for i,(r,rec) in enumerate(xs):blocks.append(f"**#{i+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{model_rec_text(rec)}\n{execution_status(rec,r['phase'])}")
        txt="\n\n".join(blocks) if blocks else "Aucun signal suffisamment défini."
        ok=send_embed(title,[("⚠️ Classement de signaux — seul le PLAN OFFICIEL est jouable",txt)],16766720) and ok
    return ok

def build_snapshot(result,rec):
    snap=_V1006_BUILD_SNAPSHOT(result,rec);snap["selection_version"]=SELECTION_VERSION;snap["slate_score"]=result.get("slate_score");snap["slate_grade"]=result.get("slate_grade");snap["stability_alert"]=result.get("stability_alert");snap["stability_delta"]=round(num(result.get("stability_delta"),0),6);snap["p_structural_raw"]=round(num(result.get("p_structural_raw"),.5),6);snap["residual_cap_runs"]=V1007_RESIDUAL_CAP_RUNS;return snap

def v10_self_test():
    _V1006_SELF_TEST()
    assert VERSION=="10.0.7" and V1007_MAX_OFFICIAL_BETS<=3 and V1007_MAX_DAILY_UNITS==4 and V1007_MAX_BETS_PER_GAME==1
    assert .545<v1007_effective_probability(.623,"ML","FINAL")<.565
    assert v1007_effective_probability(.80,"ML","FINAL")<=.66+1e-9
    assert v1007_effective_probability(.65,"ML","EARLY")<v1007_effective_probability(.65,"ML","FINAL")
    m={"w":[0.0]*17,"b":2.0,"mean":[0.0]*17,"std":[1.0]*17};ctx={"base_home":4.5,"base_away":4.5,"run_features_home":[0.0]*17,"run_features_away":[0.0]*17};h,a=project_runs(ctx,{"active":True,"model":m});assert abs(h-4.5)<=V1007_RESIDUAL_CAP_RUNS+1e-9 and abs(a-4.5)<=V1007_RESIDUAL_CAP_RUNS+1e-9
    e={"price":1.90};rec={"market":"ML","name":"H","point":None,"p_model":.72,"p_effective":.65,"p_push":0,"confidence":8.2,"refs":4,"min_price_effective":1.70,"winamax_eval":e,"p_market":.60};fake={"phase":"FINAL","quality":.85,"stability_alert":"OK","game_pk":1,"ctx":{"home":"H","away":"A","home_sp":"Starter H","away_sp":"Starter A","home_lineup":{"count":9},"away_lineup":{"count":9}}};c=v1007_candidate(fake,rec,True);assert c["eligible"] and c["units"]==2
    fake_early=dict(fake);fake_early["phase"]="EARLY";c2=v1007_candidate(fake_early,rec,True);assert not c2["eligible"] and any("EARLY" in x for x in c2["reasons"])
    print("SELF-TEST MLB BETTING BOT V10.0.7 OK")



# ==================== V10.0.8 DISCORD DELIVERY =====================
# Presentation/delivery-only layer: no change to prediction, calibration or
# official slate logic. Every analyzed game is published on every manual run.
_V1007_SELF_TEST_008=v10_self_test

VERSION="10.0.8"

def lineup_discord_status(lineup):
    lineup=lineup or {}
    count=int(num(lineup.get("count"),0))
    if bool(lineup.get("confirmed")) and count>=8:
        return "✅ CONFIRMÉE",f"{count}/9 joueurs officiels"
    return "🟠 PROJETÉE / NON CONFIRMÉE",(f"{count}/9 joueurs disponibles" if count else "lineup officielle pas encore publiée")

def should_publish(rec,s):
    # V10.0.8: every analyzed game is sent on every manual run.
    return True

def send_game(result,snap,portfolio):
    ctx=result["ctx"];v=result["verdict"];emoji,label,color=confidence_band(v["confidence"]);disp=result["disp_state"];recs=result.get("model_recs",{})
    probs=f"Modèle indépendant **{ctx['home']} {pct(result['p_model'])}** • {ctx['away']} {pct(1-result['p_model'])}\nMarché de référence **{pct(result['con']['p'])} {ctx['home']}** ({result['con']['n']} books)\nProjection: **{ctx['home']} {result['hmu']:.2f} – {result['amu']:.2f} {ctx['away']}** • total {result['hmu']+result['amu']:.2f}\nNB α H/A={disp['alpha_home']:.2f}/{disp['alpha_away']:.2f} • extras domicile {pct(result['extra_home'])} • phase **{result['phase']}** / {snap['role']}"
    direction=v["text"]+f"\n{emoji} Confiance lecture marché: **{v['confidence']:.1f}/10 — {label}**"
    starters=f"{ctx['away']}: **{ctx['away_sp']}** • {pitcher_line(ctx['away_sp_stats'],ctx['away_hand'])}\n{ctx['home']}: **{ctx['home_sp']}** • {pitcher_line(ctx['home_sp_stats'],ctx['home_hand'])}"
    hs,hd=lineup_discord_status(ctx.get("home_lineup"));as_,ad=lineup_discord_status(ctx.get("away_lineup"))
    hop=ctx['home_lineup'].get('weighted_ops');aop=ctx['away_lineup'].get('weighted_ops')
    advanced=f"{ctx['away']}: **{as_}** • {ad}\n{ctx['home']}: **{hs}** • {hd}\nOPS pondéré H/A: {hop if hop else 'N/A'} / {aop if aop else 'N/A'}\nSplits vs main opposée PA: {int(num(ctx['home_split'].get('_pa')))} / {int(num(ctx['away_split'].get('_pa')))}\nStatcast {ctx['home']}: {fmt_statcast(ctx['home_statcast'])}\nStatcast {ctx['away']}: {fmt_statcast(ctx['away_statcast'])}\nBullpen ERA H/A: {ctx['home_bp']['era']:.2f}/{ctx['away_bp']['era']:.2f} • fatigue {ctx['home_bp']['load']:.2f}/{ctx['away_bp']['load']:.2f}"
    context=f"Park {ctx['park']:.3f} • météo: {ctx['weather']['text']}\nForme 10: {ctx['home']} {ctx['home_recent']['win_pct']*100:.0f}% (RD {ctx['home_recent']['run_diff_pg']:+.2f}/g) • {ctx['away']} {ctx['away_recent']['win_pct']*100:.0f}% (RD {ctx['away_recent']['run_diff_pg']:+.2f}/g)\nQualité adaptée à la phase: **{result['quality']*10:.1f}/10**"
    model_text="\n\n".join(f"**{'🏆 MONEYLINE' if m=='ML' else '⚾ RUN LINE' if m=='RUNLINE' else '📈 TOTAL'}**\n{model_rec_text(recs.get(m))}" for m in ("ML","RUNLINE","TOTAL"))
    exec_text="\n\n".join(f"**{'ML' if m=='ML' else 'RUN LINE' if m=='RUNLINE' else 'TOTAL'}** — {execution_status(recs.get(m),result['phase'])}" for m in ("ML","RUNLINE","TOTAL"))
    selected=[e for e in result["evals"] if e.get("selected")]
    final="\n".join(f"• **{e['market']} {e['name']} {e['point'] if e['point'] is not None else ''} @ {e['price']:.2f}** • {int(num(e['units'],0))}u" for e in selected) if selected else ("👀 Aucune mise en phase EARLY — les recommandations du modèle restent valides comme watchlist." if result["phase"]=="EARLY" else "Aucune mise exécutée : les recommandations et le prix disponible sont deux décisions séparées.")
    risk=f"Exposition journée: **{portfolio['allocated']:.2f} € / {portfolio['daily_cap']:.2f} €** • plafond/match {portfolio['game_cap']:.2f} €"
    return send_embed(f"⚾ MLB V{VERSION} • {ctx['away']} @ {ctx['home']}",[("🕒 Match",local_time(result["game"]["gameDate"])+" (Paris)"),("🎯 Modèle indépendant",probs),("🧭 Benchmark marché",direction),("🧑 Starters",starters),("🧪 Lineups / splits / Statcast / bullpen",advanced),("🔬 Contexte",context),("🎯 Recommandations du modèle",model_text),("💰 Winamax — uniquement exécution",exec_text),("🛡️ Risque portefeuille",risk),("✅ Verdict de mise",final)],color)

def v10_self_test():
    global VERSION
    current=VERSION
    VERSION="10.0.7"
    try:
        _V1007_SELF_TEST_008()
    finally:
        VERSION=current
    assert VERSION=="10.0.8"
    assert lineup_discord_status({"confirmed":True,"count":9})[0]=="✅ CONFIRMÉE"
    assert "PROJETÉE" in lineup_discord_status({"confirmed":False,"count":0})[0]
    assert should_publish({},{}) is True
    print("SELF-TEST MLB BETTING BOT V10.0.8 OK")




# ==================== V10.0.9 DISCORD SIMPLE =====================
# Presentation-only layer for a beginner-friendly Discord UX.
# All advanced stats remain in the model/history but are hidden from Discord.
_V1008_SELF_TEST_009=v10_self_test

VERSION="10.0.9"

def v1009_phase_text(phase):
    phase=str(phase or "EARLY").upper()
    return {
        "EARLY":"🟡 EARLY — aperçu, pas de pari officiel",
        "LATE":"🟠 LATE — analyse affinée avant match",
        "FINAL":"🟢 FINAL — version la plus fiable avant match",
    }.get(phase,phase)

def v1009_lineup_text(lineup):
    lineup=lineup or {};count=int(num(lineup.get("count"),0))
    if bool(lineup.get("confirmed")) and count>=8:return f"✅ confirmée ({count}/9)"
    return f"🟠 projetée / non confirmée ({count}/9)"

def v1009_market_label(rec):
    if not rec:return "—"
    market=rec.get("market")
    if market=="ML":return f"Vainqueur : {rec.get('name','—')}"
    if market=="RUNLINE":return f"Handicap : {rec.get('name','—')} {num(rec.get('point')):+g}"
    if market=="TOTAL":
        side="Plus de" if str(rec.get("name","")).lower()=="over" else "Moins de"
        return f"Total : {side} {num(rec.get('point')):g} runs"
    return str(rec.get("name","—"))

def v1009_pick_status(rec,phase):
    if not rec:return "⚪ Pas de recommandation"
    e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);minimum=num(rec.get("min_price_effective",rec.get("min_price")),0)
    if e.get("official_selected"):
        units=int(num(e.get("official_units",e.get("units",1)),1));return f"✅ PARI OFFICIEL — {units}u"
    if str(phase).upper()=="EARLY":return "👀 À SURVEILLER — attendre LATE/FINAL"
    if price<=1:return "⏳ Cote Winamax absente"
    if minimum>1 and price+1e-9<minimum:return "❌ Cote Winamax trop basse"
    return "⚪ Non retenu dans le plan officiel"

def v1009_pick_text(rec,phase):
    if not rec:return "⚪ Aucune recommandation claire."
    pe=num(rec.get("p_effective",rec.get("p_model")),.5);conf=num(rec.get("confidence"),0);minimum=num(rec.get("min_price_effective",rec.get("min_price")),0);e=rec.get("winamax_eval") or {};price=num(e.get("price"),0)
    price_txt=f"{price:.2f}" if price>1 else "—"
    return f"**{v1009_market_label(rec)}**\nChance estimée **{pct(pe)}** • confiance **{conf:.1f}/10**\nCote mini **{minimum:.2f}** • Winamax **{price_txt}** • {v1009_pick_status(rec,phase)}"

def v1009_market_summary(result):
    ctx=result["ctx"];p=num(result.get("con",{}).get("p"),.5);n=int(num(result.get("con",{}).get("n"),0))
    if n<=0:return "Marché de référence indisponible"
    side=ctx["home"] if p>=.5 else ctx["away"];prob=p if p>=.5 else 1-p
    return f"Marché : **{side} {pct(prob)}** ({n} books)"

def v1009_ml_summary(result):
    rec=(result.get("model_recs") or {}).get("ML");ctx=result["ctx"]
    if rec:return f"Modèle : **{rec.get('name','—')} {pct(num(rec.get('p_effective',rec.get('p_model')),.5))}**"
    p=num(result.get("p_model"),.5);side=ctx["home"] if p>=.5 else ctx["away"];return f"Modèle : **{side} {pct(max(p,1-p))}**"

def send_game(result,snap,portfolio):
    ctx=result["ctx"];v=result["verdict"];_,_,color=confidence_band(v["confidence"]);recs=result.get("model_recs",{});phase=result.get("phase","EARLY")
    summary=(f"{v1009_phase_text(phase)}\n"
             f"{v1009_ml_summary(result)}\n"
             f"{v1009_market_summary(result)}\n"
             f"Score projeté : **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**")
    teams=(f"{ctx['away']} : {v1009_lineup_text(ctx.get('away_lineup'))}\n"
           f"{ctx['home']} : {v1009_lineup_text(ctx.get('home_lineup'))}\n"
           f"Lanceurs prévus : **{ctx['away_sp']}** / **{ctx['home_sp']}**")
    picks=(f"🏆 {v1009_pick_text(recs.get('ML'),phase)}\n\n"
           f"⚾ {v1009_pick_text(recs.get('RUNLINE'),phase)}\n\n"
           f"📈 {v1009_pick_text(recs.get('TOTAL'),phase)}")
    selected=[]
    for rec in recs.values():
        if not rec:continue
        e=rec.get("winamax_eval") or {}
        if e.get("official_selected"):selected.append(f"• **{v1009_market_label(rec)}** — {int(num(e.get('official_units',1),1))}u @ {num(e.get('price')):.2f}")
    verdict="\n".join(selected) if selected else ("**Aucun pari officiel.** Relancer en LATE/FINAL pour une décision plus fiable." if phase=="EARLY" else "**Aucun pari officiel sur ce match.**")
    help_txt="ML = vainqueur • Handicap/RL = avance ou retard en runs • Total = nombre total de runs. **Cote mini** = ne pas jouer en dessous."
    return send_embed(f"⚾ {ctx['away']} @ {ctx['home']} • {phase}",[("🧭 En bref",summary),("👥 Équipes",teams),("🎯 Paris possibles",picks),("✅ Décision du bot",verdict),("ℹ️ Repères",help_txt)],color)

def v1009_top_line(result,rec,index):
    phase=result.get("phase","EARLY");e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "—";pe=num(rec.get("p_effective",rec.get("p_model")),.5);minimum=num(rec.get("min_price_effective",rec.get("min_price")),0)
    return f"**#{index} {v1009_market_label(rec)}**\n{result['ctx']['away']} @ {result['ctx']['home']} • {phase}\nChance **{pct(pe)}** • conf. **{num(rec.get('confidence')):.1f}/10** • mini **{minimum:.2f}** • Winamax **{price_txt}**"

def send_top_messages(results,state):
    ok=True
    for market,title in (("ML","🏆 TOP 3 — VAINQUEUR (informatif)"),("RUNLINE","⚾ TOP 3 — HANDICAP (informatif)"),("TOTAL","📈 TOP 3 — TOTAL (informatif)")):
        xs=[(r,(r.get("model_recs") or {}).get(market)) for r in results if (r.get("model_recs") or {}).get(market)]
        xs=sorted(xs,key=lambda x:(num(x[1].get("p_effective",x[1].get("p_model")),.5),num(x[1].get("confidence"))),reverse=True)[:3]
        txt="\n\n".join(v1009_top_line(r,rec,i+1) for i,(r,rec) in enumerate(xs)) if xs else "Aucune recommandation claire."
        ok=send_embed(title,[("Classement du modèle",txt),("ℹ️ Important","Ce classement est informatif. **Seul le PLAN OFFICIEL est destiné à être joué.**")],16766720) and ok
    logging.info("Top 3 simplifiés envoyés");return ok

def send_daily_plan(results):
    official=[]
    for r in results:
        for rec in (r.get("model_recs") or {}).values():
            if not rec:continue
            e=rec.get("winamax_eval") or {}
            if e.get("official_selected"):
                official.append((r,rec,e))
    official.sort(key=lambda x:(num(x[1].get("p_effective",x[1].get("p_model")),.5),num(x[1].get("confidence"))),reverse=True)
    if official:
        lines=[]
        for i,(r,rec,e) in enumerate(official,1):
            lines.append(f"**#{i} {v1009_market_label(rec)}** — **{int(num(e.get('official_units',1),1))}u** @ **{num(e.get('price')):.2f}**\n{r['ctx']['away']} @ {r['ctx']['home']} • chance {pct(num(rec.get('p_effective',rec.get('p_model')),.5))} • conf. {num(rec.get('confidence')):.1f}/10")
        plan="\n\n".join(lines)
    else:
        phases=sorted({r.get("phase","EARLY") for r in results});plan="**AUCUN PARI OFFICIEL SUR CE RUN.**\n"+("Les matchs sont encore en EARLY : relancer plus près du début des rencontres." if phases==["EARLY"] else "Aucune sélection ne passe tous les filtres du bot.")
    slate=_V1007_LAST_SLATE or {};score=num(slate.get("score"),0);grade=slate.get("grade","FAIBLE");units=int(num(slate.get("units"),0));count=int(num(slate.get("official_count"),len(official)))
    status=f"Qualité de la journée : **{grade} ({score:.0f}/100)**\nParis officiels : **{count}/3** • exposition : **{units}/4u**"
    return send_embed("🎟️ PLAN OFFICIEL",[("✅ À jouer selon le bot",plan),("📊 Journée",status),("ℹ️ Règle","Les Top 3 sont des idées à surveiller. **Seuls les paris listés ici sont officiels.**")],5763719)

def v10_self_test():
    global VERSION
    current=VERSION;VERSION="10.0.8"
    try:_V1008_SELF_TEST_009()
    finally:VERSION=current
    assert VERSION=="10.0.9"
    assert "EARLY" in v1009_phase_text("EARLY")
    assert "confirmée" in v1009_lineup_text({"confirmed":True,"count":9})
    fake={"market":"ML","name":"Team A","p_effective":.61,"confidence":7.2,"min_price_effective":1.75,"winamax_eval":{"price":1.80,"official_selected":True,"official_units":1}}
    assert "PARI OFFICIEL" in v1009_pick_text(fake,"FINAL") and "Vainqueur" in v1009_market_label(fake)
    print("SELF-TEST MLB BETTING BOT V10.0.9 OK")




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





# ==================== V10.0.11 OPEN MARKET OPTIONS =====================
# Open-option / selection layer:
# - six readable options per game (2 ML, favorite -1.5, dog +1.5,
#   best available Over, best available Under)
# - Winamax price is informational only and never compared with model minimum
#   for eligibility, score or premium staking
# - the official plan still keeps the strict portfolio limits (0-3 bets,
#   4u/day, 1 bet/game) and requires the market to actually be available
# - FINAL runs optionally enrich totals with event-level alternate_totals
#   from The Odds API; EARLY/LATE fall back to featured totals to save quota
_V1010_SELF_TEST_011=v10_self_test
_V1010_ATTACH_RECS_011=attach_model_recommendations
_V1010_BUILD_SNAPSHOT_011=build_snapshot
_V1010_ALLOCATE_011=allocate_portfolio

VERSION="10.0.11"
SELECTION_VERSION="open-market-winamax-info-v2"
V1011_ALT_TOTALS_ENABLED=str(os.getenv("V1011_ALT_TOTALS_ENABLED","1")).strip().lower() not in ("0","false","no","off")
V1011_ALT_TOTALS_PHASES={x.strip().upper() for x in os.getenv("V1011_ALT_TOTALS_PHASES","FINAL").split(",") if x.strip()}
V1011_ALT_TOTALS_MAX_CALLS=max(0,int(os.getenv("V1011_ALT_TOTALS_MAX_CALLS","12") or 12))
V1011_TOTAL_TARGET_EFFECTIVE=clamp(float(os.getenv("V1011_TOTAL_TARGET_EFFECTIVE","0.62") or .62),.58,.67)
_V1011_ALT_CALLS=0


def v1011_effective_probability(p,market,phase):
    p=clamp(num(p,.5),.001,.999)
    if p>=.5:return v1007_effective_probability(p,market,phase)
    return 1-v1007_effective_probability(1-p,market,phase)


def v1011_consensus_rows(rows,name,point=None,market="totals"):
    vals=[];ages=[]
    for b,m in rows:
        if b.get("key") not in REF_BOOKS:continue
        p=fair_book_probability(m.get("outcomes",[]),name,point,market)
        if p is None:continue
        try:age=max(0,(NOW-parse_dt(m.get("last_update",b.get("last_update")))).total_seconds()/60)
        except Exception:age=10
        if age>90:continue
        weight=max(.25,1-age/120);vals += [p]*max(1,int(round(weight*4)));ages.append(age)
    if not vals:return {"p":None,"n":0,"disp":None,"age_min":None}
    return {"p":median(vals),"n":len(ages),"disp":pstdev(vals) if len(vals)>1 else 0,"age_min":median(ages) if ages else None}


def v1011_calibrate_tuple(result,market,probs):
    pw,pp,pl=(num(probs[0]),num(probs[1]),num(probs[2]));s=pw+pp+pl
    if s<=0:return .5,0,.5
    pw,pp,pl=pw/s,pp/s,pl/s
    try:state=v10_market_cal_states().get(result.get("phase","EARLY"),{}).get(market,{})
    except Exception:state={}
    if state.get("active") and state.get("model"):
        return v10_calibrate_tuple(state["model"],pw,pp,pl)
    return pw,pp,pl


def v1011_apply_effective(rec,result):
    if not rec:return None
    phase=result.get("phase","EARLY");market=rec.get("market");pm=clamp(num(rec.get("p_model"),.5),.001,.999)
    pe=v1011_effective_probability(pm,market,phase);pp=clamp(num(rec.get("p_push"),0),0,.95);mass=1-pp;pw=mass*pe;pl=mass*(1-pe)
    rec["p_effective"]=pe;rec["p_effective_win"]=pw;rec["p_effective_loss"]=pl
    rec["fair_effective"]=(1-pp)/pw if pw>0 else 99
    rec["min_price_effective"]=min_acceptable_price(pw,pp,pl)
    rec["selection_version"]=SELECTION_VERSION;rec["stability_alert"]=result.get("stability_alert","OK");rec["stability_delta"]=result.get("stability_delta",0)
    e=rec.get("winamax_eval")
    if e:
        price=num(e.get("price"),0);np=pw+pl;pcond=pw/np if np else .5
        e.update({"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":pcond,"fair":rec["fair_effective"],"min_price":rec["min_price_effective"],
                  "effective_probability":pe,"effective_probability_source":"2026-walkforward-shrinkage-symmetric",
                  "effective_min_price":rec["min_price_effective"],"edge":pcond-1/price if price>1 else None,
                  "ev":pw*price+pp-1 if price>1 else None,"official_v1011":True,"official_selected":False,
                  "official_units":0,"official_reason":"hors plan officiel","price_gate_enabled":False,"price_informational":True})
    return rec


def v1011_make_rec(result,market,name,point,probs,cons,role):
    pw,pp,pl=probs;s=num(pw)+num(pp)+num(pl)
    if s<=0:return None
    pw,pp,pl=num(pw)/s,num(pp)/s,num(pl)/s;np=pw+pl
    if np<=0:return None
    pm=pw/np;mp=(cons or {}).get("p");refs=int(num((cons or {}).get("n"),0))
    e=winamax_eval_for(result,market,name,point)
    rec={"market":market,"name":name,"point":point,"option_role":role,"p_model":pm,"p_model_raw":pm,
         "p_win":pw,"p_push":pp,"p_loss":pl,"p_market":mp,"market_gap":pm-mp if mp is not None else None,
         "refs":refs,"fair":(1-pp)/pw if pw>0 else 99,"min_price":min_acceptable_price(pw,pp,pl),
         "confidence":model_signal_confidence(pm,result.get("quality",0),mp,refs),"winamax_eval":e}
    return v1011_apply_effective(rec,result)


def v1011_alt_totals_event(result):
    global _V1011_ALT_CALLS
    phase=str(result.get("phase","EARLY")).upper();event=result.get("event") or {};eid=event.get("id")
    if not V1011_ALT_TOTALS_ENABLED or phase not in V1011_ALT_TOTALS_PHASES or not eid:return None
    key=("v1011-alt-totals",eid)
    if key in _CACHE:return _CACHE[key]
    if _V1011_ALT_CALLS>=V1011_ALT_TOTALS_MAX_CALLS:
        _CACHE[key]=None;return None
    _V1011_ALT_CALLS+=1
    try:
        d,h=http_json(f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eid}/odds",
                      {"apiKey":ODDS_KEY,"bookmakers":BOOKMAKERS,"markets":"alternate_totals","oddsFormat":"decimal","dateFormat":"iso"},
                      return_headers=True,retries=1)
        logging.info("V10.0.11 ALT TOTALS | %s @ %s | coût=%s restant=%s",
                     result["ctx"]["away"],result["ctx"]["home"],h.get("x-requests-last","?"),h.get("x-requests-remaining","?"))
        _CACHE[key]=d or None
    except Exception as e:
        logging.info("V10.0.11 ALT TOTALS indisponibles | %s @ %s | %s",result["ctx"]["away"],result["ctx"]["home"],e)
        _CACHE[key]=None
    return _CACHE[key]


def v1011_total_rows(result):
    rows=list(market_rows(result.get("event") or {},"totals"))
    alt=v1011_alt_totals_event(result)
    if alt:rows.extend(market_rows(alt,"alternate_totals"))
    return rows


def v1011_enrich_alt_total_evals(result,rows):
    existing={(e.get("market"),str(e.get("name","")).lower(),round(num(e.get("point")),3)) for e in result.get("evals",[]) if e.get("point") is not None}
    for b,m in rows:
        if b.get("key")!="winamax_fr" or m.get("key")!="alternate_totals":continue
        for o in m.get("outcomes",[]):
            name=str(o.get("name",""));point=round(num(o.get("point")),3);price=num(o.get("price"),0);key=("TOTAL",name.lower(),point)
            if price<=1 or key in existing:continue
            probs=line_probs(result["hmu"],result["amu"],result["disp_state"]["alpha_home"],result["disp_state"]["alpha_away"],"TOTAL",name,point,result["ctx"]["home"],result["ctx"]["away"])
            con=v1011_consensus_rows(rows,name,point,"totals")
            e=evaluate(result["ctx"],result["quality"],"TOTAL",name,price,point,probs,con);e["source_market"]="alternate_totals"
            result.setdefault("evals",[]).append(e);existing.add(key)


def v1011_total_interest(rec,result):
    pe=num(rec.get("p_effective"),.5);gap=num(rec.get("market_gap"),0) if rec.get("market_gap") is not None else 0
    refs=int(num(rec.get("refs"),0));conf=num(rec.get("confidence"),0);price=num((rec.get("winamax_eval") or {}).get("price"),0)
    # "Best" deliberately means a strong, useful line around the bot's selection
    # band, not the easiest extreme line. Winamax price is not part of the score.
    return ((1 if price>1 else 0),-abs(pe-V1011_TOTAL_TARGET_EFFECTIVE)+.45*clamp(gap,-.12,.12)+.006*conf+.002*min(refs,4))


def v1011_build_options(result):
    home=result["ctx"]["home"];away=result["ctx"]["away"];disp=result["disp_state"]
    options=[]
    old_ml=(result.get("model_recs") or {}).get("ML")
    if old_ml:
        hp=num(old_ml.get("p_model"),.5) if norm_name(old_ml.get("name"))==norm_name(home) else 1-num(old_ml.get("p_model"),.5)
    else:hp=num(result.get("p_model"),.5)
    hp=clamp(hp,.001,.999)
    options.append(v1011_make_rec(result,"ML",home,None,(hp,0,1-hp),consensus(result["event"],"h2h",home),"ML_HOME"))
    options.append(v1011_make_rec(result,"ML",away,None,(1-hp,0,hp),consensus(result["event"],"h2h",away),"ML_AWAY"))

    fav=home if hp>=.5 else away;dog=away if fav==home else home
    fp=line_probs(result["hmu"],result["amu"],disp["alpha_home"],disp["alpha_away"],"RUNLINE",fav,-1.5,home,away)
    fp=v1011_calibrate_tuple(result,"RUNLINE",fp);dp=(fp[2],fp[1],fp[0])
    options.append(v1011_make_rec(result,"RUNLINE",fav,-1.5,fp,consensus(result["event"],"spreads",fav,-1.5),"RL_FAVORITE"))
    options.append(v1011_make_rec(result,"RUNLINE",dog,1.5,dp,consensus(result["event"],"spreads",dog,1.5),"RL_UNDERDOG"))

    rows=v1011_total_rows(result);v1011_enrich_alt_total_evals(result,rows)
    points=set()
    for b,m in rows:
        if b.get("key")!="winamax_fr":continue
        for o in m.get("outcomes",[]):
            if o.get("point") is not None:points.add(round(num(o.get("point")),3))
    if not points:
        for _,m in rows:
            for o in m.get("outcomes",[]):
                if o.get("point") is not None:points.add(round(num(o.get("point")),3))
    overs=[];unders=[]
    for point in sorted(points):
        op=line_probs(result["hmu"],result["amu"],disp["alpha_home"],disp["alpha_away"],"TOTAL","Over",point,home,away)
        op=v1011_calibrate_tuple(result,"TOTAL",op);up=(op[2],op[1],op[0])
        ro=v1011_make_rec(result,"TOTAL","Over",point,op,v1011_consensus_rows(rows,"Over",point,"totals"),"TOTAL_OVER_BEST")
        ru=v1011_make_rec(result,"TOTAL","Under",point,up,v1011_consensus_rows(rows,"Under",point,"totals"),"TOTAL_UNDER_BEST")
        if ro:overs.append(ro)
        if ru:unders.append(ru)
    if overs:options.append(max(overs,key=lambda x:v1011_total_interest(x,result)))
    if unders:options.append(max(unders,key=lambda x:v1011_total_interest(x,result)))
    options=[x for x in options if x]
    result["option_recs"]=options
    return options


def attach_model_recommendations(result):
    recs=_V1010_ATTACH_RECS_011(result)
    v1011_build_options(result)
    return recs


def v1011_iter_options(result):
    xs=result.get("option_recs")
    return list(xs) if xs else [x for x in (result.get("model_recs") or {}).values() if x]


def v1011_profile(rec):
    if rec.get("market")=="TOTAL":return "TOTAL_OVER" if str(rec.get("name","")).lower()=="over" else "TOTAL_UNDER"
    mp=rec.get("p_market")
    fav=(num(mp)>=.5) if mp is not None else num(rec.get("p_model"),.5)>=.5
    return "SIDE_FAVORITE" if fav else "SIDE_UNDERDOG"


def v1011_candidate(result,rec,require_phase=True):
    reasons=[];phase=str(result.get("phase","EARLY")).upper();market=rec.get("market");pe=num(rec.get("p_effective"),.5)
    conf=num(rec.get("confidence"),0);q=num(result.get("quality"),0);refs=int(num(rec.get("refs"),0));e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);alert=result.get("stability_alert","OK")
    if pe<V1007_MIN_EFFECTIVE.get(market,.60):reasons.append(f"proba effective {pe*100:.1f}% trop faible")
    if conf<V1007_MIN_CONF:reasons.append(f"confiance {conf:.1f}< {V1007_MIN_CONF:.1f}")
    if q<V1007_MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10 insuffisante")
    if refs<V1007_MIN_REFS:reasons.append(f"seulement {refs} book(s) référence")
    if alert in ("HIGH","FLIP"):reasons.append(f"instabilité modèle {alert}")
    # Price LEVEL never blocks a bet in V10.0.11. Availability still matters:
    # an official Winamax bet cannot be executed if that exact market is absent.
    if price<=1:reasons.append("marché Winamax indisponible")
    if require_phase and phase=="EARLY":reasons.append("phase EARLY: pré-sélection uniquement")
    score=60+120*(pe-.58)+4*(conf-6.5)+15*(q-.70)+2*min(refs,4)
    if alert=="WATCH":score-=6
    score=clamp(score,0,100)
    premium=(phase=="FINAL" and pe>=V1007_PREMIUM_EFFECTIVE and conf>=V1007_PREMIUM_CONF and q>=V1007_PREMIUM_QUALITY and refs>=V1007_PREMIUM_REFS and result.get("stability_alert")=="OK" and result["ctx"]["home_lineup"].get("count",0)>=8 and result["ctx"]["away_lineup"].get("count",0)>=8 and v1007_starters_ok(result["ctx"]))
    return {"eligible":not reasons,"reasons":reasons,"score":score,"units":2 if premium else 1,"profile":v1011_profile(rec),"result":result,"rec":rec,"price":price,"minimum":num(rec.get("min_price_effective"),0),"premium":premium}


def v1011_build_slate(results,require_phase=True):
    pool=[]
    for r in results:
        for rec in v1011_iter_options(r):
            c=v1011_candidate(r,rec,require_phase)
            if c["eligible"]:pool.append(c)
    pool.sort(key=lambda c:(c["score"],num(c["rec"].get("p_effective"),.5),num(c["rec"].get("confidence"))),reverse=True)
    unique=[];seen=set()
    for c in pool:
        gid=str(c["result"]["game_pk"])
        if gid in seen:continue
        unique.append(c);seen.add(gid)
    top=unique[:V1007_MAX_OFFICIAL_BETS];slate_score=mean([c["score"] for c in top]) if top else 0.0
    thresholds=(70,72,74);max_bets=0
    for i,c in enumerate(top):
        if c["score"]>=thresholds[i]:max_bets=i+1
        else:break
    grade="FORT" if slate_score>=82 else "BON" if slate_score>=76 else "MOYEN" if slate_score>=70 else "FAIBLE"
    return {"pool":pool,"unique":unique,"score":round(slate_score,1),"grade":grade,"max_bets":max_bets}


def allocate_portfolio(results):
    global _V10_LAST_PORTFOLIO,_V1007_LAST_SLATE
    if not results or not all(("option_recs" in r or "model_recs" in r) for r in results):
        return _V1010_ALLOCATE_011(results)
    for r in results:
        for e in r.get("evals",[]):e.update({"selected":False,"units":0.0,"stake_eur":0.0,"official_selected":False,"official_units":0,"official_preview_units":0})
        for rec in v1011_iter_options(r):
            e=rec.get("winamax_eval") or {}
            if e:e.update({"official_v1011":True,"official_selected":False,"official_units":0,"official_preview_units":0,"official_reason":"hors plan officiel","price_gate_enabled":False,"price_informational":True})
    slate=v1011_build_slate(results,True);preview=v1011_build_slate(results,False);chosen=[];used_games=set();profiles={};units_used=0;thresholds=(70,72,74)
    for c in slate["pool"]:
        if len(chosen)>=slate["max_bets"] or len(chosen)>=V1007_MAX_OFFICIAL_BETS:break
        if c["score"]<thresholds[len(chosen)]:break
        gid=str(c["result"]["game_pk"]);profile=c["profile"]
        if gid in used_games:continue
        e=c["rec"].get("winamax_eval") or {}
        if profiles.get(profile,0)>=2:
            e["official_reason"]="corrélation: déjà 2 paris du même profil";continue
        units=c["units"]
        if units_used+units>V1007_MAX_DAILY_UNITS:
            if units==2 and units_used+1<=V1007_MAX_DAILY_UNITS:units=1
            else:e["official_reason"]="plafond quotidien 4u";continue
        if not e:continue
        e.update({"selected":True,"official_selected":True,"official_units":units,"units":float(units),"stake_eur":round(units*UNIT,2),
                  "qualified":True,"model_recommended":True,"reason":"OK V10.0.11","portfolio_reason":"PARI OFFICIEL V10.0.11",
                  "official_reason":"retenu dans le plan officiel","candidate_units":float(units),"candidate_stake_eur":round(units*UNIT,2)})
        chosen.append(c);used_games.add(gid);profiles[profile]=profiles.get(profile,0)+1;units_used+=units
    chosen_ids={id(c["rec"]) for c in chosen}
    for c in slate["pool"]:
        e=c["rec"].get("winamax_eval") or {}
        if id(c["rec"]) not in chosen_ids and e.get("official_reason")=="hors plan officiel":e["official_reason"]="option intéressante non retenue par le Slate Score / limite 0-3"
    early_preview=[];seen=set()
    for c in preview["pool"]:
        if str(c["result"].get("phase")).upper()!="EARLY" or c["score"]<70:continue
        gid=str(c["result"]["game_pk"])
        if gid in seen:continue
        e=c["rec"].get("winamax_eval") or {}
        if e:e["official_preview_units"]=1
        early_preview.append(c);seen.add(gid)
        if len(early_preview)>=3:break
    allocated=round(units_used*UNIT,2);cap=round(V1007_MAX_DAILY_UNITS*UNIT,2)
    _V1007_LAST_SLATE={"score":slate["score"],"grade":slate["grade"],"max_bets":slate["max_bets"],"official_count":len(chosen),"units":units_used,"preview_count":len(early_preview)}
    _V10_LAST_PORTFOLIO={"daily_cap":cap,"allocated":allocated,"remaining":round(cap-allocated,2),"game_cap":round(2*UNIT,2),"slate_score":slate["score"],"slate_grade":slate["grade"],"official_count":len(chosen),"official_units":units_used}
    for r in results:r["slate_score"]=slate["score"];r["slate_grade"]=slate["grade"]
    logging.info("V10.0.11 OPEN SLATE | score=%.1f grade=%s max=%d selected=%d units=%du/%du | Winamax price gate=OFF",slate["score"],slate["grade"],slate["max_bets"],len(chosen),units_used,V1007_MAX_DAILY_UNITS)
    return _V10_LAST_PORTFOLIO


def v1011_selected_items(results):
    out=[]
    for r in results:
        for rec in v1011_iter_options(r):
            e=rec.get("winamax_eval") or {}
            if e.get("official_selected"):out.append({"result":r,"rec":rec,"score":num(rec.get("p_effective"),.5)*100+num(rec.get("confidence"))})
    return sorted(out,key=lambda x:x["score"],reverse=True)


def v1007_selected_items(results):
    return v1011_selected_items(results)


def v1011_market_label(rec):
    if not rec:return "—"
    if rec.get("market")=="ML":return f"{rec.get('name','—')} ML"
    if rec.get("market")=="RUNLINE":return f"{rec.get('name','—')} {num(rec.get('point')):+g}"
    side="Over" if str(rec.get("name","")).lower()=="over" else "Under"
    return f"{side} {num(rec.get('point')):g}"


def v1011_option_status(result,rec):
    e=rec.get("winamax_eval") or {};price=num(e.get("price"),0)
    if e.get("official_selected"):return f"✅ OFFICIEL {int(num(e.get('official_units'),1))}u"
    c=v1011_candidate(result,rec,False)
    if c["eligible"]:
        return "👀 INTÉRESSANT — attendre LATE/FINAL" if str(result.get("phase")).upper()=="EARLY" else "🟢 OPTION INTÉRESSANTE"
    if price<=1:return "⏳ Winamax indisponible"
    return "⚪ Option analysée"


def v1011_option_line(result,rec):
    if not rec:return "—"
    e=rec.get("winamax_eval") or {};price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "—"
    return f"{v1011_option_status(result,rec)} • **{v1011_market_label(rec)}**\nChance prudente **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • Winamax **{price_txt}** *(info)*"


def send_game(result,snap,portfolio):
    ctx=result["ctx"];opts=v1011_iter_options(result);phase=v1009_phase_text(result.get("phase"));raw=num(result.get("p_model"),.5);side=ctx["home"] if raw>=.5 else ctx["away"];raw_side=max(raw,1-raw);con=result.get("con") or {}
    market_side=ctx["home"] if num(con.get("p"),.5)>=.5 else ctx["away"]
    market_p=max(num(con.get("p"),.5),1-num(con.get("p"),.5)) if con.get("p") is not None else None
    brief=f"{phase}\nModèle brut : **{side} {pct(raw_side)}**\nMarché réf. : **{market_side} {pct(market_p)}** ({int(num(con.get('n'),0))} books)\nScore projeté : **{ctx['away']} {result['amu']:.1f} – {result['hmu']:.1f} {ctx['home']}**"
    teams=f"{ctx['away']} : {v1009_lineup_text(ctx.get('away_lineup'))} • starter **{ctx.get('away_sp','—')}**\n{ctx['home']} : {v1009_lineup_text(ctx.get('home_lineup'))} • starter **{ctx.get('home_sp','—')}**"
    ml=[x for x in opts if x.get("market")=="ML"];rl=[x for x in opts if x.get("market")=="RUNLINE"];tot=[x for x in opts if x.get("market")=="TOTAL"]
    official=[x for x in opts if (x.get("winamax_eval") or {}).get("official_selected")]
    decision="\n".join(f"• ✅ **{v1011_market_label(x)} — {int(num((x.get('winamax_eval') or {}).get('official_units'),1))}u**" for x in official)
    if not decision:decision="**Aucun pari officiel sur ce match.** Les options ci-dessus restent visibles pour comparaison."
    fields=[("🧭 En bref",brief),("👥 Équipes",teams),
            ("🏆 Vainqueur — les 2 côtés","\n\n".join(v1011_option_line(result,x) for x in ml) or "—"),
            ("⚾ Handicap ±1,5 — les 2 côtés","\n\n".join(v1011_option_line(result,x) for x in rl) or "—"),
            ("📊 Total — meilleur Over + meilleur Under","\n\n".join(v1011_option_line(result,x) for x in tot) or "—"),
            ("✅ Décision du bot",decision),
            ("ℹ️ Lecture","La **cote Winamax est informative** : son niveau ne bloque plus une option et n'entre plus dans le Slate Score. L'absence du marché exact empêche seulement de l'exécuter. Les lignes alternatives de Total sont recherchées en FINAL quand l'API les fournit.")]
    return send_embed(f"⚾ MLB V{VERSION} • {ctx['away']} @ {ctx['home']}",fields,5763719)


def v1011_plan_pick_text(item,index=None):
    r=item["result"];rec=item["rec"];e=rec.get("winamax_eval") or {};u=int(num(e.get("official_units"),0));price=num(e.get("price"),0);prefix=f"**#{index}** " if index is not None else "• "
    return f"{prefix}✅ **{v1011_market_label(rec)} — {u}u = {u*UNIT:.2f} €**\n{r['ctx']['away']} @ {r['ctx']['home']} • {r['phase']} • chance prudente **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • Winamax **{price:.2f}** *(info)*"


def plan_pick_text(item,index=None):return v1011_plan_pick_text(item,index)


def send_daily_plan(results):
    official=v1011_selected_items(results)
    plan="\n\n".join(v1011_plan_pick_text(x,i+1) for i,x in enumerate(official)) if official else "**AUCUN PARI OFFICIEL SUR CE RUN.**"
    others=[];official_ids={id(x["rec"]) for x in official}
    for c in v1011_build_slate(results,False)["pool"]:
        if id(c["rec"]) in official_ids:continue
        e=c["rec"].get("winamax_eval") or {};price=num(e.get("price"),0)
        others.append(f"• **{v1011_market_label(c['rec'])}** • {c['result']['ctx']['away']} @ {c['result']['ctx']['home']} • {pct(c['rec'].get('p_effective'))} • conf {num(c['rec'].get('confidence')):.1f}/10 • Winamax {price:.2f} *(info)*")
        if len(others)>=5:break
    other_txt="\n".join(others) if others else "Aucune autre option ne passe actuellement les filtres statistiques."
    slate=_V1007_LAST_SLATE or {};status=f"Qualité de la journée : **{slate.get('grade','FAIBLE')} ({num(slate.get('score')):.0f}/100)**\nParis officiels : **{int(num(slate.get('official_count'),len(official)))}/3** • exposition : **{int(num(slate.get('units'),0))}/4u**"
    return send_embed("🎟️ PLAN OFFICIEL",[("✅ À jouer selon le bot",plan),("🟢 Autres options intéressantes",other_txt),("📊 Journée",status),("ℹ️ Règle","Le Plan Officiel reste limité à **3 paris / 4u / 1 pari par match**. La cote Winamax est affichée pour information mais **n'est plus un filtre de sélection**.")],5763719)


def send_top_messages(results,state):
    ok=True
    groups=(("ML","🏆 TOP 3 — VAINQUEUR (informatif)"),("RUNLINE","⚾ TOP 3 — HANDICAP (informatif)"),("TOTAL","📈 TOP 3 — TOTAL (informatif)"))
    for market,title in groups:
        pool=[]
        for r in results:
            for rec in v1011_iter_options(r):
                if rec.get("market")!=market:continue
                c=v1011_candidate(r,rec,False);pool.append((c["eligible"],c["score"],r,rec))
        pool.sort(key=lambda z:(z[0],z[1],num(z[3].get("p_effective"),.5)),reverse=True)
        blocks=[];seen=set()
        for _,_,r,rec in pool:
            gid=str(r.get("game_pk"))
            if gid in seen:continue
            seen.add(gid);blocks.append(f"**#{len(blocks)+1} {r['ctx']['away']} @ {r['ctx']['home']}**\n{v1011_option_line(r,rec)}")
            if len(blocks)>=3:break
        ok=send_embed(title,[("ℹ️ Classement d'options — seul le PLAN OFFICIEL est officiel","\n\n".join(blocks) if blocks else "Aucune option disponible.")],16766720) and ok
    return ok


def build_snapshot(result,rec):
    snap=_V1010_BUILD_SNAPSHOT_011(result,rec)
    snap["selection_version"]=SELECTION_VERSION
    snap["open_market_options"]=[dict(model_rec_payload(x),winamax_price=num((x.get("winamax_eval") or {}).get("price"),0) or None,option_role=x.get("option_role")) for x in v1011_iter_options(result)]
    return snap


def v1010_make_run_rows(results,run_id=None,analyzed_at=None):
    analyzed_at=analyzed_at or NOW.isoformat();run_id=run_id or hashlib.sha1(f"{analyzed_at}|{TARGET_DATE}|{VERSION}".encode()).hexdigest()[:16];out=[]
    for r in results:
        ctx=r.get("ctx") or {};phase=r.get("phase","EARLY")
        for rec in v1011_iter_options(r):
            if not rec:continue
            market=rec.get("market");e=rec.get("winamax_eval") or {};c=v1011_candidate(r,rec,True);c_no_phase=v1011_candidate(r,rec,False);point=rec.get("point")
            jid_src=f"{run_id}|{r.get('game_pk')}|{market}|{norm_name(rec.get('name'))}|{point}|{rec.get('option_role','')}";journal_id=hashlib.sha1(jid_src.encode()).hexdigest();price=num(e.get("price"),0)
            official=bool(e.get("official_selected"));preview=bool(e.get("official_preview_units"));official_units=int(num(e.get("official_units",e.get("units",0)),0)) if official else 0;official_stake=round(official_units*UNIT,2)
            official_reason=e.get("official_reason") or ("retenu dans le plan officiel" if official else "non retenu");reasons=list(c.get("reasons") or [])
            if not official and official_reason and official_reason not in reasons:reasons.append(str(official_reason))
            status="OFFICIAL" if official else "PREVIEW" if preview else "INTERESTING" if c_no_phase.get("eligible") else "ANALYZED"
            out.append({"journal_version":JOURNAL_VERSION,"journal_id":journal_id,"run_id":run_id,"bot_version":VERSION,"analyzed_at":analyzed_at,"target_date":TARGET_DATE,
                "game_pk":r.get("game_pk"),"game_date":(r.get("game") or {}).get("gameDate"),"home":ctx.get("home"),"away":ctx.get("away"),"phase":phase,"seconds_to_game":round(num(r.get("seconds"),0),1),
                "market":market,"pick":rec.get("name"),"point":point,"option_role":rec.get("option_role"),"model_proposed":True,"p_model_raw":round(num(rec.get("p_model"),.5),6),"p_effective":round(num(rec.get("p_effective",rec.get("p_model")),.5),6),
                "confidence":round(num(rec.get("confidence"),0),3),"quality":round(num(r.get("quality"),0),4),"refs":int(num(rec.get("refs"),0)),"p_market":round(num(rec.get("p_market"),0),6) if rec.get("p_market") is not None else None,
                "market_gap":round(num(rec.get("market_gap"),0),6) if rec.get("market_gap") is not None else None,"fair_raw":round(num(rec.get("fair"),0),4) if rec.get("fair") is not None else None,
                "fair_effective":round(num(rec.get("fair_effective",rec.get("fair")),0),4) if rec.get("fair_effective",rec.get("fair")) is not None else None,"min_price_raw":round(num(rec.get("min_price"),0),4) if rec.get("min_price") is not None else None,
                "min_price_effective":round(num(rec.get("min_price_effective",rec.get("min_price")),0),4) if rec.get("min_price_effective",rec.get("min_price")) is not None else None,"winamax_price":round(price,4) if price>1 else None,
                "winamax_price_informational":True,"winamax_price_gate_enabled":False,"edge_effective":round(num(e.get("edge"),0),6) if price>1 and e.get("edge") is not None else None,"ev_effective":round(num(e.get("ev"),0),6) if price>1 and e.get("ev") is not None else None,
                "eligible_before_slate":bool(c.get("eligible")),"interesting_without_phase":bool(c_no_phase.get("eligible")),"candidate_score":round(num(c.get("score"),0),2),"risk_profile":c.get("profile"),"official_selected":official,
                "official_units":official_units,"official_stake_eur":official_stake,"official_reason":official_reason,"preview_selected":preview,"rejection_reasons":reasons,"selection_status":status,
                "slate_score":round(num(r.get("slate_score"),0),2),"slate_grade":r.get("slate_grade"),"stability_alert":r.get("stability_alert"),"stability_delta":round(num(r.get("stability_delta"),0),6),"p_structural_raw":round(num(r.get("p_structural_raw"),.5),6),
                "home_lineup_confirmed":bool((ctx.get("home_lineup") or {}).get("confirmed")),"home_lineup_count":int(num((ctx.get("home_lineup") or {}).get("count"),0)),"away_lineup_confirmed":bool((ctx.get("away_lineup") or {}).get("confirmed")),"away_lineup_count":int(num((ctx.get("away_lineup") or {}).get("count"),0)),
                "home_starter":ctx.get("home_sp"),"away_starter":ctx.get("away_sp"),"unit_eur":round(UNIT,4),"result_status":"PENDING","result":None,"home_score":None,"away_score":None,"settled_at":None,"hypothetical_profit_1u_eur":None,"official_profit_eur":None})
    return out


def v1010_log_journal(journal,added=0,settled_now=0):
    m=v1010_journal_metrics(journal)
    logging.info("V%s LIVE JOURNAL | rows=%d +%d | settled=%d (+%d) | priced=%d hypROI=%s | official_settled=%d officialROI=%s",VERSION,m["rows"],added,m["settled"],settled_now,m["priced"],pct(m["hyp_roi"]) if m["hyp_roi"] is not None else "-",m["official_settled"],pct(m["official_roi"]) if m["official_roi"] is not None else "-")


def v10_self_test():
    global VERSION
    current=VERSION;VERSION="10.0.10"
    try:_V1010_SELF_TEST_011()
    finally:VERSION=current
    assert VERSION=="10.0.11"
    assert v1011_effective_probability(.40,"ML","FINAL")<.50 and v1011_effective_probability(.60,"ML","FINAL")>.50
    fake={"phase":"FINAL","quality":.85,"stability_alert":"OK","game_pk":77,"ctx":{"home":"H","away":"A","home_sp":"Starter H","away_sp":"Starter A","home_lineup":{"count":9},"away_lineup":{"count":9}}}
    rec_low={"market":"ML","name":"H","point":None,"p_model":.70,"p_effective":.63,"p_push":0,"confidence":8.0,"refs":3,"p_market":.58,"min_price_effective":1.75,"winamax_eval":{"price":1.45}}
    rec_high=dict(rec_low);rec_high["winamax_eval"]={"price":2.10}
    c1=v1011_candidate(fake,rec_low,True);c2=v1011_candidate(fake,rec_high,True)
    assert c1["eligible"] and c2["eligible"] and abs(c1["score"]-c2["score"])<1e-9
    rec_none=dict(rec_low);rec_none["winamax_eval"]={};c3=v1011_candidate(fake,rec_none,True);assert not c3["eligible"] and any("indisponible" in x for x in c3["reasons"])
    assert "info" in v1011_option_line(fake,rec_low).lower()
    print("SELF-TEST MLB BETTING BOT V10.0.11 OK")



# ==================== V10.0.12 PHASE-OPEN OFFICIAL PLAN =====================
# Selection-only layer:
# - official bets are allowed in EARLY, LATE and FINAL
# - phase is always displayed clearly; EARLY/LATE should be rechecked later
# - Winamax price AND Winamax market availability are informational only
# - statistical quality gates remain active; no forced weak pick fallback
_V1011_SELF_TEST_012=v10_self_test
_V1011_CANDIDATE_012=v1011_candidate

VERSION="10.0.12"
SELECTION_VERSION="phase-open-winamax-info-v3"


def v1012_phase_badge(phase):
    phase=str(phase or "EARLY").upper()
    if phase=="FINAL":return "🟢 FINAL"
    if phase=="LATE":return "🟠 LATE — à reconfirmer en FINAL"
    return "🟡 EARLY — à reconfirmer en LATE/FINAL"


def v1012_ensure_execution(rec):
    e=rec.get("winamax_eval")
    if not isinstance(e,dict) or not e:
        e={"price":0.0,"synthetic_execution":True,"winamax_available":False}
        rec["winamax_eval"]=e
    else:
        e["winamax_available"]=num(e.get("price"),0)>1
    e["price_gate_enabled"]=False
    e["price_informational"]=True
    e["availability_gate_enabled"]=False
    return e


def v1011_candidate(result,rec,require_phase=True):
    # `require_phase` is intentionally ignored in V10.0.12: EARLY/LATE/FINAL
    # can all produce official bets. The phase remains visible to the user.
    reasons=[];phase=str(result.get("phase","EARLY")).upper();market=rec.get("market");pe=num(rec.get("p_effective"),.5)
    conf=num(rec.get("confidence"),0);q=num(result.get("quality"),0);refs=int(num(rec.get("refs"),0));alert=result.get("stability_alert","OK")
    e=v1012_ensure_execution(rec);price=num(e.get("price"),0)
    if pe<V1007_MIN_EFFECTIVE.get(market,.60):reasons.append(f"proba effective {pe*100:.1f}% trop faible")
    if conf<V1007_MIN_CONF:reasons.append(f"confiance {conf:.1f}< {V1007_MIN_CONF:.1f}")
    if q<V1007_MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10 insuffisante")
    if refs<V1007_MIN_REFS:reasons.append(f"seulement {refs} book(s) référence")
    if alert in ("HIGH","FLIP"):reasons.append(f"instabilité modèle {alert}")
    score=60+120*(pe-.58)+4*(conf-6.5)+15*(q-.70)+2*min(refs,4)
    if alert=="WATCH":score-=6
    score=clamp(score,0,100)
    # 2u remains FINAL-only: EARLY/LATE can be official, but stay at 1u.
    premium=(phase=="FINAL" and pe>=V1007_PREMIUM_EFFECTIVE and conf>=V1007_PREMIUM_CONF and q>=V1007_PREMIUM_QUALITY and refs>=V1007_PREMIUM_REFS and result.get("stability_alert")=="OK" and result["ctx"]["home_lineup"].get("count",0)>=8 and result["ctx"]["away_lineup"].get("count",0)>=8 and v1007_starters_ok(result["ctx"]))
    return {"eligible":not reasons,"reasons":reasons,"score":score,"units":2 if premium else 1,"profile":v1011_profile(rec),"result":result,"rec":rec,"price":price,"minimum":num(rec.get("min_price_effective"),0),"premium":premium}


def allocate_portfolio(results):
    global _V10_LAST_PORTFOLIO,_V1007_LAST_SLATE
    if not results or not all(("option_recs" in r or "model_recs" in r) for r in results):
        return _V1010_ALLOCATE_011(results)
    for r in results:
        for e in r.get("evals",[]):
            e.update({"selected":False,"units":0.0,"stake_eur":0.0,"official_selected":False,"official_units":0,"official_preview_units":0})
        for rec in v1011_iter_options(r):
            e=v1012_ensure_execution(rec)
            e.update({"official_v1012":True,"official_selected":False,"official_units":0,"official_preview_units":0,
                      "official_reason":"hors plan officiel","price_gate_enabled":False,"price_informational":True,
                      "availability_gate_enabled":False})
    slate=v1011_build_slate(results,True);chosen=[];used_games=set();profiles={};units_used=0;thresholds=(70,72,74)
    for c in slate["pool"]:
        if len(chosen)>=slate["max_bets"] or len(chosen)>=V1007_MAX_OFFICIAL_BETS:break
        if c["score"]<thresholds[len(chosen)]:break
        gid=str(c["result"]["game_pk"]);profile=c["profile"]
        if gid in used_games:continue
        e=v1012_ensure_execution(c["rec"])
        if profiles.get(profile,0)>=2:
            e["official_reason"]="corrélation: déjà 2 paris du même profil";continue
        units=c["units"]
        if units_used+units>V1007_MAX_DAILY_UNITS:
            if units==2 and units_used+1<=V1007_MAX_DAILY_UNITS:units=1
            else:e["official_reason"]="plafond quotidien 4u";continue
        e.update({"selected":True,"official_selected":True,"official_units":units,"units":float(units),"stake_eur":round(units*UNIT,2),
                  "qualified":True,"model_recommended":True,"reason":"OK V10.0.12","portfolio_reason":"PARI OFFICIEL V10.0.12",
                  "official_reason":f"retenu dans le plan officiel ({str(c['result'].get('phase','EARLY')).upper()})",
                  "candidate_units":float(units),"candidate_stake_eur":round(units*UNIT,2)})
        chosen.append(c);used_games.add(gid);profiles[profile]=profiles.get(profile,0)+1;units_used+=units
    chosen_ids={id(c["rec"]) for c in chosen}
    for c in slate["pool"]:
        e=v1012_ensure_execution(c["rec"])
        if id(c["rec"]) not in chosen_ids and e.get("official_reason")=="hors plan officiel":
            e["official_reason"]="option intéressante non retenue par le Slate Score / limite 0-3"
    allocated=round(units_used*UNIT,2);cap=round(V1007_MAX_DAILY_UNITS*UNIT,2)
    _V1007_LAST_SLATE={"score":slate["score"],"grade":slate["grade"],"max_bets":slate["max_bets"],"official_count":len(chosen),"units":units_used,"preview_count":0}
    _V10_LAST_PORTFOLIO={"daily_cap":cap,"allocated":allocated,"remaining":round(cap-allocated,2),"game_cap":round(2*UNIT,2),"slate_score":slate["score"],"slate_grade":slate["grade"],"official_count":len(chosen),"official_units":units_used}
    for r in results:r["slate_score"]=slate["score"];r["slate_grade"]=slate["grade"]
    logging.info("V10.0.12 PHASE-OPEN SLATE | score=%.1f grade=%s max=%d selected=%d units=%du/%du | phase gate=OFF | Winamax gates=OFF",slate["score"],slate["grade"],slate["max_bets"],len(chosen),units_used,V1007_MAX_DAILY_UNITS)
    return _V10_LAST_PORTFOLIO


def v1011_plan_pick_text(item,index=None):
    r=item["result"];rec=item["rec"];e=v1012_ensure_execution(rec);u=int(num(e.get("official_units"),0));price=num(e.get("price"),0);prefix=f"**#{index}** " if index is not None else "• "
    price_txt=f"{price:.2f}" if price>1 else "non récupérée"
    return f"{prefix}✅ **{v1011_market_label(rec)} — {u}u = {u*UNIT:.2f} €**\n{r['ctx']['away']} @ {r['ctx']['home']} • **{v1012_phase_badge(r.get('phase'))}**\nChance prudente **{pct(rec.get('p_effective'))}** • conf. **{num(rec.get('confidence')):.1f}/10** • Winamax **{price_txt}** *(info)*"


def plan_pick_text(item,index=None):return v1011_plan_pick_text(item,index)


def send_daily_plan(results):
    official=v1011_selected_items(results)
    plan="\n\n".join(v1011_plan_pick_text(x,i+1) for i,x in enumerate(official)) if official else "**AUCUN PARI OFFICIEL SUR CE RUN.** Aucun candidat ne passe actuellement les seuils statistiques minimums."
    others=[];official_ids={id(x["rec"]) for x in official}
    for c in v1011_build_slate(results,False)["pool"]:
        if id(c["rec"]) in official_ids:continue
        e=v1012_ensure_execution(c["rec"]);price=num(e.get("price"),0);price_txt=f"{price:.2f}" if price>1 else "—"
        others.append(f"• **{v1011_market_label(c['rec'])}** • {c['result']['ctx']['away']} @ {c['result']['ctx']['home']} • **{v1012_phase_badge(c['result'].get('phase'))}** • {pct(c['rec'].get('p_effective'))} • conf {num(c['rec'].get('confidence')):.1f}/10 • Winamax {price_txt} *(info)*")
        if len(others)>=5:break
    other_txt="\n".join(others) if others else "Aucune autre option ne passe actuellement les filtres statistiques."
    slate=_V1007_LAST_SLATE or {};status=f"Qualité de la journée : **{slate.get('grade','FAIBLE')} ({num(slate.get('score')):.0f}/100)**\nParis officiels : **{int(num(slate.get('official_count'),len(official)))}/3** • exposition : **{int(num(slate.get('units'),0))}/4u**"
    rule="Le Plan Officiel peut maintenant contenir des paris **EARLY, LATE ou FINAL**. Un pari EARLY/LATE reste officiel pour le run courant mais doit idéalement être **recontrôlé sur un run plus proche du match**. Winamax est 100 % informatif : ni le niveau de cote ni l'absence de cote dans le flux ne bloquent la sélection."
    return send_embed("🎟️ PLAN OFFICIEL",[("✅ À jouer selon le bot",plan),("🟢 Autres options intéressantes",other_txt),("📊 Journée",status),("ℹ️ Règle",rule)],5763719)


def v10_self_test():
    global VERSION,v1011_candidate
    current=VERSION;current_candidate=v1011_candidate;VERSION="10.0.11";v1011_candidate=_V1011_CANDIDATE_012
    try:_V1011_SELF_TEST_012()
    finally:VERSION=current;v1011_candidate=current_candidate
    assert VERSION=="10.0.12"
    fake={"phase":"EARLY","quality":.90,"stability_alert":"OK","game_pk":88,"ctx":{"home":"H","away":"A","home_sp":"Starter H","away_sp":"Starter A","home_lineup":{"count":0},"away_lineup":{"count":0}}}
    rec={"market":"ML","name":"H","point":None,"p_model":.74,"p_effective":.625,"p_push":0,"confidence":8.0,"refs":4,"p_market":.60,"min_price_effective":1.70,"winamax_eval":None}
    c=v1011_candidate(fake,rec,True)
    assert c["eligible"] and c["units"]==1 and rec.get("winamax_eval") is not None
    assert rec["winamax_eval"].get("availability_gate_enabled") is False
    assert "EARLY" in v1012_phase_badge("EARLY") and "FINAL" in v1012_phase_badge("FINAL")
    print("SELF-TEST MLB BETTING BOT V10.0.12 OK")

if __name__=="__main__":
    try:
        if "--self-test" in sys.argv:v10_self_test()
        else:main()
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception:logging.exception("ERREUR FATALE V10");raise
