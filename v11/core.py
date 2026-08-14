from __future__ import annotations
import json, logging, math, os, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime.now(timezone.utc)
LOCAL_NOW = datetime.now(PARIS)
DEFAULT_DATE = (LOCAL_NOW.date()-timedelta(days=1)).isoformat() if LOCAL_NOW.hour < 6 else LOCAL_NOW.date().isoformat()
TARGET_DATE = os.getenv("MLB_DATE", DEFAULT_DATE)
SEASON = int(os.getenv("MLB_SEASON", TARGET_DATE[:4]))
ODDS_KEY = os.getenv("ODDS_API_KEY","").strip()
DISCORD_URL = os.getenv("DISCORD_WEBHOOK_URL","").strip()
UNIT = float(os.getenv("UNIT","0.5") or 0.5)
BANKROLL = float(os.getenv("BANKROLL","10") or 10)
TIMEOUT = int(os.getenv("HTTP_TIMEOUT","25") or 25)
BOOKMAKERS = [x.strip() for x in os.getenv(
    "ODDS_BOOKMAKERS",
    "winamax_fr,pinnacle,betfair_ex_eu,matchbook,betonlineag,betclic_fr,unibet_fr,pmu_fr,netbet_fr"
).split(",") if x.strip()]
SHARP_BOOKS = {"pinnacle","betfair_ex_eu","matchbook","betonlineag"}
WINAMAX_KEY = "winamax_fr"
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO").upper(), format="%(asctime)s | %(levelname)s | %(message)s")

PARK = {"Arizona Diamondbacks":1.04,"Athletics":1.05,"Atlanta Braves":1.01,"Baltimore Orioles":1.01,"Boston Red Sox":1.03,"Chicago White Sox":1.00,"Chicago Cubs":1.02,"Cincinnati Reds":1.05,"Cleveland Guardians":0.98,"Colorado Rockies":1.14,"Detroit Tigers":0.98,"Houston Astros":1.00,"Kansas City Royals":0.99,"Los Angeles Angels":1.01,"Los Angeles Dodgers":0.98,"Miami Marlins":0.96,"Milwaukee Brewers":1.00,"Minnesota Twins":0.99,"New York Mets":0.98,"New York Yankees":1.03,"Philadelphia Phillies":1.02,"Pittsburgh Pirates":0.97,"San Diego Padres":0.97,"San Francisco Giants":0.94,"Seattle Mariners":0.96,"St. Louis Cardinals":1.00,"Tampa Bay Rays":0.98,"Texas Rangers":1.02,"Toronto Blue Jays":1.01,"Washington Nationals":1.00}
COORD={"Arizona Diamondbacks":(33.4453,-112.0667),"Athletics":(38.5806,-121.5130),"Atlanta Braves":(33.8907,-84.4677),"Baltimore Orioles":(39.2839,-76.6217),"Boston Red Sox":(42.3467,-71.0972),"Chicago White Sox":(41.8301,-87.6338),"Chicago Cubs":(41.9484,-87.6553),"Cincinnati Reds":(39.0975,-84.5069),"Cleveland Guardians":(41.4962,-81.6852),"Colorado Rockies":(39.7559,-104.9942),"Detroit Tigers":(42.3390,-83.0485),"Houston Astros":(29.7573,-95.3555),"Kansas City Royals":(39.0517,-94.4803),"Los Angeles Angels":(33.8003,-117.8827),"Los Angeles Dodgers":(34.0739,-118.2400),"Miami Marlins":(25.7781,-80.2197),"Milwaukee Brewers":(43.0280,-87.9712),"Minnesota Twins":(44.9817,-93.2776),"New York Mets":(40.7571,-73.8458),"New York Yankees":(40.8296,-73.9262),"Philadelphia Phillies":(39.9061,-75.1665),"Pittsburgh Pirates":(40.4469,-80.0057),"San Diego Padres":(32.7076,-117.1570),"San Francisco Giants":(37.7786,-122.3893),"Seattle Mariners":(47.5914,-122.3325),"St. Louis Cardinals":(38.6226,-90.1928),"Tampa Bay Rays":(27.7683,-82.6534),"Texas Rangers":(32.7473,-97.0832),"Toronto Blue Jays":(43.6414,-79.3894),"Washington Nationals":(38.8730,-77.0074)}
_CACHE = {}

def num(x,d=0.0):
    try:
        y=float(x); return y if math.isfinite(y) else d
    except Exception:return d
def clamp(x,a=.001,b=.999): return max(a,min(b,num(x,.5)))
def pct(x): return "—" if x is None else f"{100*num(x):.1f}%"
def parse_dt(s): return datetime.fromisoformat(str(s).replace("Z","+00:00"))
def norm_name(s): return "".join(c.lower() for c in str(s or "") if c.isalnum())

def http_json(url, params=None, method="GET", payload=None, timeout=TIMEOUT, retries=2):
    if params: url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",")
    data = None; headers={"User-Agent":"MLB-Betting-Bot-V11","Accept":"application/json"}
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode(); headers["Content-Type"]="application/json"
    last=None
    for attempt in range(retries+1):
        try:
            req=urllib.request.Request(url,data=data,headers=headers,method=method)
            with urllib.request.urlopen(req,timeout=timeout) as r:
                body=r.read().decode("utf-8","replace"); return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            last=e
            if e.code not in (429,500,502,503,504) or attempt>=retries: raise
            time.sleep(1.2*(attempt+1))
        except Exception as e:
            last=e
            if attempt>=retries: raise
            time.sleep(1+attempt)
    raise last

def mlb(path,params=None): return http_json("https://statsapi.mlb.com/api/"+path.lstrip("/"),params)
def mlb_schedule(day,team_id=None,hydrate="probablePitcher,linescore"):
    p={"sportId":1,"date":day,"hydrate":hydrate}
    if team_id:p["teamId"]=team_id
    d=mlb("v1/schedule",p) or {}
    return [g for block in d.get("dates",[]) for g in block.get("games",[])]

def _stat_split(d):
    try:
        s=(d.get("stats") or [{}])[0].get("splits") or []
        return s[0].get("stat",{}) if s else {}
    except Exception:return {}

def season_stats(team_id,group):
    key=("team",team_id,group,SEASON)
    if key in _CACHE:return _CACHE[key]
    try: out=_stat_split(mlb(f"v1/teams/{team_id}/stats",{"stats":"season","group":group,"season":SEASON}))
    except Exception as e: logging.warning("Stats %s/%s indisponibles: %s",team_id,group,e); out={}
    _CACHE[key]=out; return out

def player_stats(pid,group="pitching"):
    if not pid:return {}
    key=("player",pid,group,SEASON)
    if key in _CACHE:return _CACHE[key]
    try: out=_stat_split(mlb(f"v1/people/{pid}/stats",{"stats":"season","group":group,"season":SEASON}))
    except Exception: out={}
    _CACHE[key]=out; return out

def league_baselines():
    key=("league",SEASON)
    if key in _CACHE:return _CACHE[key]
    vals={"rpg":4.45,"era":4.35,"ops":.710,"whip":1.32}
    try:
        dh=mlb("v1/teams/stats",{"stats":"season","group":"hitting","season":SEASON,"sportIds":1}) or {}
        dp=mlb("v1/teams/stats",{"stats":"season","group":"pitching","season":SEASON,"sportIds":1}) or {}
        hs=(dh.get("stats") or [{}])[0].get("splits") or []; ps=(dp.get("stats") or [{}])[0].get("splits") or []
        if hs:
            vals["rpg"]=mean(num(x.get("stat",{}).get("runsPerGame"),4.45) for x in hs)
            vals["ops"]=mean(num(x.get("stat",{}).get("ops"),.710) for x in hs)
        if ps:
            vals["era"]=mean(num(x.get("stat",{}).get("era"),4.35) for x in ps)
            vals["whip"]=mean(num(x.get("stat",{}).get("whip"),1.32) for x in ps)
    except Exception as e: logging.warning("Baselines MLB fallback: %s",e)
    _CACHE[key]=vals; return vals

def odds_api():
    if not ODDS_KEY: raise RuntimeError("ODDS_API_KEY absente")
    params={"apiKey":ODDS_KEY,"regions":"eu","markets":"h2h,spreads,totals","oddsFormat":"decimal","dateFormat":"iso","bookmakers":",".join(BOOKMAKERS)}
    return http_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",params) or []

def match_odds_events(games,events):
    index={}
    for e in events:index[(norm_name(e.get("home_team")),norm_name(e.get("away_team")))]=e
    out={}
    for g in games:
        teams=g.get("teams") or {};h=((teams.get("home") or {}).get("team") or {}).get("name","");a=((teams.get("away") or {}).get("team") or {}).get("name","")
        e=index.get((norm_name(h),norm_name(a)))
        if e:out[str(g.get("gamePk"))]=e
    return out

def _market(book,key):
    return next((m for m in book.get("markets") or [] if m.get("key")==key),None)
def _outcome_price(market,name,point=None):
    if not market:return None
    for o in market.get("outcomes") or []:
        if norm_name(o.get("name"))!=norm_name(name):continue
        if point is not None and abs(num(o.get("point"),999)-num(point))>1e-6:continue
        p=num(o.get("price"),0)
        if p>1:return p
    return None

def winamax_price(event,market,name,point=None):
    for b in event.get("bookmakers") or []:
        if b.get("key")!=WINAMAX_KEY:continue
        return _outcome_price(_market(b,{"ML":"h2h","RUNLINE":"spreads","TOTAL":"totals"}[market]),name,point)
    return None

def sharp_consensus(event,market,name,point=None):
    key={"ML":"h2h","RUNLINE":"spreads","TOTAL":"totals"}[market];probs=[];books=[]
    for b in event.get("bookmakers") or []:
        if b.get("key") not in SHARP_BOOKS:continue
        m=_market(b,key)
        if not m:continue
        relevant=[]
        for o in m.get("outcomes") or []:
            if point is not None and abs(num(o.get("point"),999)-num(point))>1e-6:continue
            if num(o.get("price"),0)>1:relevant.append(o)
        if len(relevant)<2:continue
        inv=[1/num(o.get("price")) for o in relevant];s=sum(inv);target=next((o for o in relevant if norm_name(o.get("name"))==norm_name(name)),None)
        if target is None:continue
        probs.append((1/num(target.get("price")))/s);books.append(b.get("key"))
    return {"p":sum(probs)/len(probs) if probs else None,"n":len(probs),"books":books}

def phase_for_game(game):
    try:sec=(parse_dt(game.get("gameDate"))-NOW).total_seconds()
    except Exception:return "EARLY"
    if sec<=90*60:return "FINAL"
    if sec<=5*3600:return "LATE"
    return "EARLY"

def send_embed(title,fields,color=5763719,description=None):
    if not DISCORD_URL:return False
    payload={"embeds":[{"title":title,"color":color,"fields":[{"name":n,"value":v,"inline":False} for n,v in fields]}]}
    if description:payload["embeds"][0]["description"]=description
    try:
        req=urllib.request.Request(DISCORD_URL,data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json","User-Agent":"MLB-Betting-Bot-V11"},method="POST")
        with urllib.request.urlopen(req,timeout=15) as r:r.read()
        return True
    except Exception as e:logging.warning("Discord impossible: %s",e);return False

def discord_test():
    if not DISCORD_URL:logging.warning("DISCORD_WEBHOOK_URL absente");return False
    return True
def lineup_text(lineup):
    if not lineup:return "lineup non confirmée"
    n=int(num(lineup.get("count"),0));return f"{n}/9 joueurs" if n else "lineup détectée"
def market_label(rec):
    if rec.get("market")=="ML":return f"{rec.get('name')} ML"
    if rec.get("market")=="RUNLINE":return f"{rec.get('name')} {num(rec.get('point')):+g}"
    return f"{str(rec.get('name')).title()} {num(rec.get('point')):g}"
