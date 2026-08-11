#!/usr/bin/env python3
import os, json, math, time, logging, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from statistics import median, mean, pstdev
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "8.0"
SCHEMA_VERSION = 8
FEATURE_VERSION = "8.0"
PARIS = ZoneInfo("Europe/Paris")
NOW = datetime.now(timezone.utc)
TARGET_DATE = os.getenv("MLB_DATE", datetime.now(PARIS).date().isoformat())
SEASON = int(os.getenv("MLB_SEASON", TARGET_DATE[:4]))
ODDS_KEY = os.getenv("ODDS_API_KEY", "").strip()
DISCORD_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
HISTORY_FILE = Path(os.getenv("HISTORY_FILE", "data/mlb_history_v8.jsonl"))
BANKROLL = float(os.getenv("BANKROLL", "10") or 10)
UNIT = float(os.getenv("UNIT", "0.5") or .5)
MAX_STAKE_UNITS = float(os.getenv("MAX_STAKE_UNITS", "3") or 3)
MIN_EV = float(os.getenv("MIN_EV", "0.03") or .03)
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.025") or .025)
MIN_QUALITY = float(os.getenv("MIN_QUALITY", "0.62") or .62)
MATCH_MAX_DELTA_HOURS = float(os.getenv("MATCH_MAX_DELTA_HOURS", "6") or 6)
RUN_MODEL_MIN_GAMES = int(os.getenv("RUN_MODEL_MIN_GAMES", "120") or 120)
CAL_MIN_GAMES = int(os.getenv("CAL_MIN_GAMES", "150") or 150)
SNAPSHOT_MIN_MINUTES = int(os.getenv("SNAPSHOT_MIN_MINUTES", "15") or 15)
BOOKMAKERS = os.getenv("ODDS_BOOKMAKERS", "winamax_fr,pinnacle,betfair_ex_eu,betclic_fr,unibet_fr,pmu_fr,netbet_fr")
REF_BOOKS = {x for x in BOOKMAKERS.split(",") if x and x != "winamax_fr"}
TIMEOUT = 25
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s | %(levelname)s | %(message)s")

PARK = {
    "Arizona Diamondbacks":1.04,"Athletics":1.05,"Oakland Athletics":1.05,"Atlanta Braves":1.01,"Baltimore Orioles":1.01,
    "Boston Red Sox":1.03,"Chicago White Sox":1.00,"Chicago Cubs":1.02,"Cincinnati Reds":1.05,"Cleveland Guardians":0.98,
    "Colorado Rockies":1.14,"Detroit Tigers":0.98,"Houston Astros":1.00,"Kansas City Royals":0.99,"Los Angeles Angels":1.01,
    "Los Angeles Dodgers":0.98,"Miami Marlins":0.96,"Milwaukee Brewers":1.00,"Minnesota Twins":0.99,"New York Mets":0.98,
    "New York Yankees":1.03,"Philadelphia Phillies":1.02,"Pittsburgh Pirates":0.97,"San Diego Padres":0.97,
    "San Francisco Giants":0.94,"Seattle Mariners":0.96,"St. Louis Cardinals":1.00,"Tampa Bay Rays":0.98,
    "Texas Rangers":1.02,"Toronto Blue Jays":1.01,"Washington Nationals":1.00
}
COORD = {
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
ROOF = {"Arizona Diamondbacks","Houston Astros","Miami Marlins","Milwaukee Brewers","Seattle Mariners","Texas Rangers","Toronto Blue Jays"}
DOME = {"Tampa Bay Rays"}
ALIASES = {"oaklandathletics":"athletics","athletics":"athletics"}
_CACHE = {}

def norm_name(s):
    x = "".join(c.lower() for c in str(s) if c.isalnum())
    return ALIASES.get(x, x)

def clamp(x, a=.001, b=.999): return max(a, min(b, x))
def num(x, d=0.0):
    try:
        y=float(x); return y if math.isfinite(y) else d
    except Exception:return d

def pct(x): return "N/A" if x is None else f"{100*x:.1f}%"
def parse_dt(s): return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
def local_time(iso):
    try:return parse_dt(iso).astimezone(PARIS).strftime("%d/%m/%Y %H:%M")
    except Exception:return str(iso)

def http_json(url, params=None, method="GET", payload=None, timeout=TIMEOUT, return_headers=False, retries=2):
    if params:
        qs=urllib.parse.urlencode(params,safe=",");url += ("&" if "?" in url else "?")+qs
    data=None;headers={"User-Agent":"MLB-Betting-Bot-V8/1.0","Accept":"application/json"}
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8");headers["Content-Type"]="application/json"
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
            time.sleep(attempt+1)
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
def player_stats(pid,group="pitching",stat_type="season"):
    if not pid:return {}
    key=("playerstats",pid,group,stat_type,SEASON)
    if key in _CACHE:return _CACHE[key]
    try:out=stat_split(mlb(f"v1/people/{pid}/stats",{"stats":stat_type,"group":group,"season":SEASON}))
    except Exception:out={}
    _CACHE[key]=out;return out
def person_info(pid):
    if not pid:return {}
    key=("person",pid)
    if key in _CACHE:return _CACHE[key]
    try:out=(mlb(f"v1/people/{pid}").get("people") or [{}])[0]
    except Exception:out={}
    _CACHE[key]=out;return out

def league_baselines():
    key=("league",SEASON)
    if key in _CACHE:return _CACHE[key]
    vals={"rpg":4.45,"era":4.35,"ops":.710,"obp":.320,"slg":.390,"whip":1.32}
    try:
        dh=mlb("v1/teams/stats",{"stats":"season","group":"hitting","season":SEASON,"sportIds":1});dp=mlb("v1/teams/stats",{"stats":"season","group":"pitching","season":SEASON,"sportIds":1})
        hs=(dh.get("stats") or [{}])[0].get("splits") or [];ps=(dp.get("stats") or [{}])[0].get("splits") or []
        if hs:
            vals["rpg"]=mean(num(x.get("stat",{}).get("runsPerGame"),4.45) for x in hs);vals["ops"]=mean(num(x.get("stat",{}).get("ops"),.710) for x in hs)
            vals["obp"]=mean(num(x.get("stat",{}).get("obp",x.get("stat",{}).get("onBasePercentage")),.320) for x in hs);vals["slg"]=mean(num(x.get("stat",{}).get("slg",x.get("stat",{}).get("sluggingPercentage")),.390) for x in hs)
        if ps:
            vals["era"]=mean(num(x.get("stat",{}).get("era"),4.35) for x in ps);vals["whip"]=mean(num(x.get("stat",{}).get("whip"),1.32) for x in ps)
    except Exception as e:logging.warning("Baselines MLB: %s",e)
    _CACHE[key]=vals;return vals

def expected_stats(team_id,group="hitting"):
    key=("expected",team_id,group,SEASON)
    if key in _CACHE:return _CACHE[key]
    try:out=stat_split(mlb(f"v1/teams/{team_id}/stats",{"stats":"expectedStatistics","group":group,"season":SEASON}))
    except Exception:out={}
    if not out:
        try:
            d=mlb("v1/stats",{"stats":"expectedStatistics","group":group,"season":SEASON,"teamId":team_id});splits=(d.get("stats") or [{}])[0].get("splits") or []
            team_rows=[x.get("stat",{}) for x in splits if x.get("team",{}).get("id")==team_id and not x.get("player")];out=team_rows[0] if len(team_rows)==1 else {}
        except Exception:out={}
    _CACHE[key]=out;return out
def metric_any(d,names,default=None):
    if not isinstance(d,dict):return default
    lower={str(k).lower():v for k,v in d.items()}
    for n in names:
        if n.lower() in lower:
            try:return float(lower[n.lower()])
            except Exception:pass
    for v in d.values():
        if isinstance(v,dict):
            z=metric_any(v,names,None)
            if z is not None:return z
    return default
def statcast_team(team_id):
    d=expected_stats(team_id,"hitting");xwoba=metric_any(d,["xwoba","expectedWeightedOnBaseAverage","expectedwoba"]);xslg=metric_any(d,["xslg","expectedSluggingPercentage","expectedslg"]);xba=metric_any(d,["xba","expectedBattingAverage","expectedavg"])
    return {"xwoba":xwoba,"xslg":xslg,"xba":xba,"available":any(x is not None for x in (xwoba,xslg,xba))}
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
    if not out:
        try:
            d=mlb("v1/stats",{"stats":"statSplits","group":"hitting","season":SEASON,"teamId":team_id,"sitCodes":sit});splits=(d.get("stats") or [{}])[0].get("splits") or []
            team_rows=[x.get("stat",{}) for x in splits if x.get("team",{}).get("id")==team_id and not x.get("player")];out=team_rows[0] if len(team_rows)==1 else {}
        except Exception:pass
    _CACHE[key]=out;return out

def anchor_date_from_game(g):return parse_dt(g["gameDate"]).astimezone(PARIS).date()
def recent_games(team_id,anchor_date,days=14):
    key=("recent",team_id,anchor_date.isoformat(),days)
    if key in _CACHE:return _CACHE[key]
    end=anchor_date-timedelta(days=1);start=end-timedelta(days=days-1)
    try:
        d=mlb("v1/schedule",{"sportId":1,"teamId":team_id,"startDate":start.isoformat(),"endDate":end.isoformat()});gs=[g for block in d.get("dates",[]) for g in block.get("games",[]) if g.get("status",{}).get("abstractGameState")=="Final"]
    except Exception:gs=[]
    _CACHE[key]=gs;return gs
def recent_context(team_id,anchor_date):
    gs=recent_games(team_id,anchor_date,14)[-10:];wins=rf=ra=0.0
    for g in gs:
        home=g.get("teams",{}).get("home",{});away=g.get("teams",{}).get("away",{});is_home=home.get("team",{}).get("id")==team_id;own=home if is_home else away;opp=away if is_home else home
        a=num(own.get("score"));b=num(opp.get("score"));rf+=a;ra+=b;wins+=int(a>b)
    n=len(gs);return {"games":n,"win_pct":wins/n if n else .5,"run_diff_pg":(rf-ra)/n if n else 0.0,"runs_pg":rf/n if n else league_baselines()["rpg"]}
def boxscore(game_pk):
    key=("box",game_pk)
    if key in _CACHE:return _CACHE[key]
    try:out=mlb(f"v1/game/{game_pk}/boxscore")
    except Exception:out={}
    _CACHE[key]=out;return out

def bullpen_profile(team_id,anchor_date):
    gs=recent_games(team_id,anchor_date,7)[-5:];team_pitch=season_stats(team_id,"pitching");prior_era=num(team_pitch.get("era"),league_baselines()["era"])
    if not gs:return {"load":.5,"era":prior_era,"whip":league_baselines()["whip"],"ip":0.0,"games":0,"quality":.45}
    weighted_pitches=outs=er=hits=walks=0.0;seen=0
    for g in gs:
        try:
            gd=parse_dt(g["gameDate"]).astimezone(PARIS).date();age=max(1,(anchor_date-gd).days)
            if age>5:continue
            b=boxscore(g["gamePk"]);side="home" if g["teams"]["home"]["team"]["id"]==team_id else "away";team=b.get("teams",{}).get(side,{});game_relief=0
            for p in team.get("players",{}).values():
                st=p.get("stats",{}).get("pitching",{})
                if not st or num(st.get("gamesStarted"),0)>=1:continue
                po=num(st.get("outs"),0)
                if po<=0:
                    ip=str(st.get("inningsPitched","0"));po=int(float(ip.split(".")[0]))*3+int(ip.split(".")[1][:1] or 0) if "." in ip else int(num(ip))*3
                outs+=po;er+=num(st.get("earnedRuns"));hits+=num(st.get("hits"));walks+=num(st.get("baseOnBalls"));pitches=num(st.get("pitchesThrown"));game_relief+=pitches
            weighted_pitches+=game_relief*{1:1.0,2:.65,3:.40,4:.25,5:.15}.get(age,.1);seen+=1
        except Exception:pass
    ip=outs/3.0;recent_era=9*er/ip if ip>0 else prior_era;recent_whip=(hits+walks)/ip if ip>0 else league_baselines()["whip"];w=ip/(ip+18.0)
    era=clamp(prior_era+w*(recent_era-prior_era),2.2,7.0);whip=clamp(league_baselines()["whip"]+w*(recent_whip-league_baselines()["whip"]),.85,1.9);load=clamp(weighted_pitches/180.0,0,1.5)
    return {"load":load,"era":era,"whip":whip,"ip":ip,"games":seen,"quality":min(1.0,.45+ip/30.0)}

def weather(team,iso):
    if team not in COORD:return {"text":"N/A","run_adj":0.0,"quality":0.0}
    try:
        game_dt=parse_dt(iso).astimezone(timezone.utc);today=datetime.now(timezone.utc).date();delta_days=(game_dt.date()-today).days
        if delta_days<0 or delta_days>3:return {"text":"hors fenêtre prévisionnelle","run_adj":0.0,"quality":0.0}
        lat,lon=COORD[team];d=http_json("https://api.open-meteo.com/v1/forecast",{"latitude":lat,"longitude":lon,"hourly":"temperature_2m,wind_speed_10m,relative_humidity_2m,precipitation_probability","forecast_days":4,"timezone":"UTC"})
        target=game_dt.replace(minute=0,second=0,microsecond=0,tzinfo=None);ts=[datetime.fromisoformat(x) for x in d["hourly"]["time"]];i=min(range(len(ts)),key=lambda j:abs(ts[j]-target))
        if abs((ts[i]-target).total_seconds())>5400:return {"text":"prévision horaire indisponible","run_adj":0.0,"quality":0.0}
        t=num(d["hourly"]["temperature_2m"][i]);w=num(d["hourly"]["wind_speed_10m"][i]);h=num(d["hourly"]["relative_humidity_2m"][i]);pr=num(d["hourly"]["precipitation_probability"][i]);raw=(t-20)*.010+max(0,w-15)*.004
        if team in DOME:factor=0.0;note="dôme"
        elif team in ROOF:factor=.20;note="toit rétractable: impact météo réduit"
        else:factor=1.0;note="extérieur"
        return {"text":f"{t:.0f}°C • vent {w:.0f} km/h • HR {h:.0f}% • pluie {pr:.0f}% • {note}","run_adj":raw*factor,"quality":1.0}
    except Exception:return {"text":"N/A","run_adj":0.0,"quality":0.0}

def ip_float(v):
    try:
        t=str(v or "0")
        if "." not in t:return float(t)
        a,b=t.split(".",1);return float(a)+int(b[:1] or 0)/3
    except Exception:return 0.0
def shrunk_pitcher(p):
    lg=league_baselines();ip=ip_float(p.get("inningsPitched")) if p else 0.0;w_rate=ip/(ip+35.0);w_kbb=ip/(ip+25.0);raw_era=num(p.get("era"),lg["era"]) if p else lg["era"];raw_whip=num(p.get("whip"),lg["whip"]) if p else lg["whip"];raw_k=num(p.get("strikeOutsPer9"),8.3) if p else 8.3;raw_bb=num(p.get("walksPer9"),3.2) if p else 3.2
    return {"ip":ip,"era":clamp(lg["era"]+w_rate*(raw_era-lg["era"]),2.1,6.8),"whip":clamp(lg["whip"]+w_rate*(raw_whip-lg["whip"]),.90,1.8),"k9":clamp(8.3+w_kbb*(raw_k-8.3),4.5,13.0),"bb9":clamp(3.2+w_kbb*(raw_bb-3.2),1.0,6.0),"raw_era":raw_era,"raw_whip":raw_whip,"weight":w_rate}
def pitcher_line(p,hand="?"):
    if not p:return f"main {hand} • données indisponibles"
    q=shrunk_pitcher(p)
    if q["ip"]<35:return f"main {hand} • ERA {q['raw_era']:.2f}→{q['era']:.2f} adj • WHIP {q['raw_whip']:.2f}→{q['whip']:.2f} • K/9 {q['k9']:.1f} • BB/9 {q['bb9']:.1f} • IP {q['ip']:.1f}"
    return f"main {hand} • ERA {q['era']:.2f} • WHIP {q['whip']:.2f} • K/9 {q['k9']:.1f} • BB/9 {q['bb9']:.1f} • IP {q['ip']:.1f}"

def lineup_context(game_pk,side):
    team=boxscore(game_pk).get("teams",{}).get(side,{});rows=[]
    for p in team.get("players",{}).values():
        bo=p.get("battingOrder")
        if bo is None:continue
        try:order=int(bo)
        except Exception:continue
        if order<=0:continue
        h=p.get("seasonStats",{}).get("hitting",{}) or p.get("stats",{}).get("hitting",{});ops=num(h.get("ops"),0) if h else 0;rows.append((order,p.get("person",{}).get("fullName","?"),ops if ops>.2 else None))
    rows.sort();top=rows[:9];vals=[x[2] for x in top if x[2] is not None]
    return {"confirmed":len(top)>=8,"count":len(top),"ops":mean(vals) if len(vals)>=5 else None,"names":[x[1] for x in top]}
def team_bundle(team_id,anchor_date):return season_stats(team_id,"hitting"),season_stats(team_id,"pitching"),recent_context(team_id,anchor_date),bullpen_profile(team_id,anchor_date),statcast_team(team_id)

def base_runs(own_h,opp_p,own_recent,park,wx,home_flag):
    lg=league_baselines();own_rpg=num(own_h.get("runsPerGame"),lg["rpg"]);opp_games=max(1.0,num(opp_p.get("gamesPlayed"),0));opp_ra=num(opp_p.get("runs"),0)/opp_games if num(opp_p.get("runs"),0)>0 else lg["rpg"]*num(opp_p.get("era"),lg["era"])/lg["era"];recent=own_recent["runs_pg"] if own_recent["games"]>=5 else own_rpg;base=mean([own_rpg,opp_ra,recent])*park*(1+wx["run_adj"]*.025)
    if home_flag:base+=.08
    return clamp(base,2.2,7.2)
def run_features(own_h,opp_p,own_recent,opp_recent,opp_sp,opp_bp,lineup,split,statcast,park,wx,home_flag):
    lg=league_baselines();own_ops=num(own_h.get("ops"),lg["ops"]);split_ops=num(split.get("ops"),own_ops) if split else own_ops;lineup_ops=lineup.get("ops") if lineup else None;xwoba=statcast.get("xwoba") if statcast else None
    return [(num(own_h.get("runsPerGame"),lg["rpg"])-lg["rpg"])/1.4,(own_ops-lg["ops"])/.09,(num(own_h.get("obp",own_h.get("onBasePercentage")),lg["obp"])-lg["obp"])/.045,(num(own_h.get("slg",own_h.get("sluggingPercentage")),lg["slg"])-lg["slg"])/.075,(num(opp_p.get("era"),lg["era"])-lg["era"])/1.3,(opp_sp["era"]-lg["era"])/1.6,(opp_sp["whip"]-lg["whip"])/.30,(opp_sp["bb9"]-3.2)/1.8-(opp_sp["k9"]-8.3)/2.8,(opp_bp["era"]-lg["era"])/1.6,(opp_bp["load"]-.5)/.6,(own_recent["run_diff_pg"]-opp_recent["run_diff_pg"])/2.5,((lineup_ops-own_ops)/.08) if lineup_ops is not None else 0.0,(split_ops-own_ops)/.08 if split else 0.0,((xwoba-.320)/.045) if xwoba is not None else 0.0,(park-1.0)/.08,wx["run_adj"]/.20,1.0 if home_flag else 0.0]

def game_context(g):
    home=g["teams"]["home"]["team"];away=g["teams"]["away"]["team"];anchor=anchor_date_from_game(g);hh,hp,hr,hbp,hsc=team_bundle(home["id"],anchor);ah,ap,ar,abp,asc=team_bundle(away["id"],anchor);hsp=g["teams"]["home"].get("probablePitcher") or {};asp=g["teams"]["away"].get("probablePitcher") or {};hs_raw=player_stats(hsp.get("id"),"pitching");as_raw=player_stats(asp.get("id"),"pitching");hs=shrunk_pitcher(hs_raw);ass=shrunk_pitcher(as_raw);hhand=person_info(hsp.get("id")).get("pitchHand",{}).get("code","?");ahand=person_info(asp.get("id")).get("pitchHand",{}).get("code","?");hsplit=split_hitting(home["id"],ahand);asplit=split_hitting(away["id"],hhand);hline=lineup_context(g["gamePk"],"home");aline=lineup_context(g["gamePk"],"away");wx=weather(home["name"],g["gameDate"]);park=PARK.get(home["name"],1.0);bh=base_runs(hh,ap,hr,park,wx,True);ba=base_runs(ah,hp,ar,park,wx,False);fh=run_features(hh,ap,hr,ar,ass,abp,hline,hsplit,hsc,park,wx,True);fa=run_features(ah,hp,ar,hr,hs,hbp,aline,asplit,asc,park,wx,False)
    data_flags=[bool(hh),bool(ah),bool(hp),bool(ap),bool(hs_raw),bool(as_raw),hbp["games"]>0,abp["games"]>0,wx["quality"]>0];advanced_flags=[hhand in ("L","R"),ahand in ("L","R"),bool(hsplit),bool(asplit),hline["confirmed"],aline["confirmed"],hsc["available"],asc["available"]];quality=.70*(sum(data_flags)/len(data_flags))+.30*(sum(advanced_flags)/len(advanced_flags))
    return {"home":home["name"],"away":away["name"],"home_id":home["id"],"away_id":away["id"],"game_date":g["gameDate"],"home_sp":hsp.get("fullName","Non annoncé"),"away_sp":asp.get("fullName","Non annoncé"),"home_sp_stats":hs_raw,"away_sp_stats":as_raw,"home_hand":hhand,"away_hand":ahand,"home_recent":hr,"away_recent":ar,"home_bp":hbp,"away_bp":abp,"home_lineup":hline,"away_lineup":aline,"home_split":hsplit,"away_split":asplit,"home_statcast":hsc,"away_statcast":asc,"park":park,"weather":wx,"quality":clamp(quality,0,1),"base_home":bh,"base_away":ba,"run_features_home":fh,"run_features_away":fa}

def fit_linear_residual(rows,epochs=420,lr=.012,l2=.006):
    d=len(rows[0][0]);means=[mean(r[0][j] for r in rows) for j in range(d)];std=[]
    for j in range(d):
        s=math.sqrt(mean((r[0][j]-means[j])**2 for r in rows));std.append(s if s>.08 else 1.0)
    w=[0.0]*d;b=0.0
    for ep in range(epochs):
        eta=lr*(1-ep/(epochs*1.35))
        for x,y in rows:
            z=[(x[j]-means[j])/std[j] for j in range(d)];pred=b+sum(a*c for a,c in zip(w,z));e=pred-y;b-=eta*e
            for j in range(d):w[j]-=eta*(e*z[j]+l2*w[j])
    return {"w":w,"b":b,"mean":means,"std":std}
def linear_predict(model,x):
    z=[(x[j]-model["mean"][j])/model["std"][j] for j in range(len(x))];return model["b"]+sum(a*c for a,c in zip(model["w"],z))
def rmse(vals):return math.sqrt(mean(x*x for x in vals)) if vals else 99.0
def latest_pregame_snapshot(r):
    snaps=[s for s in r.get("snapshots",[]) if num(s.get("seconds_to_game"),-1)>=0 and s.get("feature_version")==FEATURE_VERSION]
    return max(snaps,key=lambda s:s.get("analyzed_at","")) if snaps else None
def run_training_rows(hist):
    games=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s:continue
        try:games.append((r.get("game_date",""),s,float(r["home_score"]),float(r["away_score"])))
        except Exception:pass
    games.sort(key=lambda z:z[0]);return games
def run_model_state(hist):
    games=run_training_rows(hist);out={"active":False,"model":None,"n":len(games),"rmse_model":None,"rmse_base":None,"folds":0}
    if len(games)<RUN_MODEL_MIN_GAMES:return out
    base_err=[];model_err=[];folds=0
    for frac in (.60,.70,.80):
        cut=int(len(games)*frac);end=min(len(games),cut+max(20,int(len(games)*.10)))
        if cut<80 or end-cut<15:continue
        train=[]
        for _,s,hs,as_ in games[:cut]:train.append((s["run_features_home"],hs-num(s["base_home"])));train.append((s["run_features_away"],as_-num(s["base_away"])))
        m=fit_linear_residual(train)
        for _,s,hs,as_ in games[cut:end]:
            ph=num(s["base_home"])+clamp(linear_predict(m,s["run_features_home"]),-2.0,2.0);pa=num(s["base_away"])+clamp(linear_predict(m,s["run_features_away"]),-2.0,2.0);base_err += [num(s["base_home"])-hs,num(s["base_away"])-as_];model_err += [ph-hs,pa-as_]
        folds+=1
    if not folds:return out
    rb,rm=rmse(base_err),rmse(model_err);out.update({"rmse_base":rb,"rmse_model":rm,"folds":folds})
    if rm+.04<rb:
        allrows=[]
        for _,s,hs,as_ in games:allrows.append((s["run_features_home"],hs-num(s["base_home"])));allrows.append((s["run_features_away"],as_-num(s["base_away"])))
        out["model"]=fit_linear_residual(allrows);out["active"]=True
    return out
def project_runs(ctx,run_state):
    h,a=ctx["base_home"],ctx["base_away"]
    if run_state["active"] and run_state["model"]:h+=clamp(linear_predict(run_state["model"],ctx["run_features_home"]),-2.0,2.0);a+=clamp(linear_predict(run_state["model"],ctx["run_features_away"]),-2.0,2.0)
    return clamp(h,2.0,8.0),clamp(a,2.0,8.0)

def poisson(mu,max_runs=25):
    p=[math.exp(-mu)]
    for k in range(1,max_runs+1):p.append(p[-1]*mu/k)
    s=sum(p);return [x/s for x in p]
def ml_prob(hmu,amu):
    h=poisson(hmu);a=poisson(amu);win=tie=0.0
    for i,pi in enumerate(h):
        for j,pj in enumerate(a):
            z=pi*pj
            if i>j:win+=z
            elif i==j:tie+=z
    return clamp(win+.535*tie)
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
    s=w+p+l;return w/s,p/s,l/s

def odds_api():
    data,h=http_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",{"apiKey":ODDS_KEY,"bookmakers":BOOKMAKERS,"markets":"h2h,spreads,totals","oddsFormat":"decimal","dateFormat":"iso"},return_headers=True);logging.info("The Odds API | coût=%s | restant=%s | utilisé=%s",h.get("x-requests-last","?"),h.get("x-requests-remaining","?"),h.get("x-requests-used","?"));return data or []
def match_odds_events(games,events):
    groups={}
    for e in events:groups.setdefault((norm_name(e.get("away_team")),norm_name(e.get("home_team"))),[]).append(e)
    matches={};used=set()
    for g in sorted(games,key=lambda x:x.get("gameDate","")):
        away=g["teams"]["away"]["team"]["name"];home=g["teams"]["home"]["team"]["name"];candidates=[e for e in groups.get((norm_name(away),norm_name(home)),[]) if e.get("id") not in used]
        if not candidates:continue
        gt=parse_dt(g["gameDate"]);ranked=[]
        for e in candidates:
            try:delta=abs((parse_dt(e["commence_time"])-gt).total_seconds())
            except Exception:delta=99999999
            ranked.append((delta,e))
        delta,e=min(ranked,key=lambda z:z[0])
        if delta<=MATCH_MAX_DELTA_HOURS*3600:matches[str(g["gamePk"])]=(e,delta/60);used.add(e.get("id"))
        else:logging.warning("Odds rejetées (horaire %.1fh): %s @ %s",delta/3600,away,home)
    return matches
def market_rows(event,market):
    out=[]
    for b in event.get("bookmakers",[]):
        for m in b.get("markets",[]):
            if m.get("key")==market:out.append((b,m))
    return out
def winamax_outcomes(event,market):
    for b,m in market_rows(event,market):
        if b.get("key")=="winamax_fr":return b,m
    return None,None
def fair_book_probability(outcomes,target_name,target_point=None,market="h2h"):
    if market=="h2h":
        if len(outcomes)<2:return None
        probs={norm_name(o.get("name")):1/num(o.get("price"),999) for o in outcomes if num(o.get("price"))>1};s=sum(probs.values());k=norm_name(target_name);return probs.get(k)/s if k in probs and s else None
    if market=="totals":
        xs=[o for o in outcomes if abs(num(o.get("point"))-num(target_point))<1e-6]
        if len(xs)<2:return None
        probs={str(o.get("name")):1/num(o.get("price"),999) for o in xs if num(o.get("price"))>1};s=sum(probs.values());return probs.get(str(target_name))/s if str(target_name) in probs and s else None
    target=next((o for o in outcomes if norm_name(o.get("name"))==norm_name(target_name) and abs(num(o.get("point"))-num(target_point))<1e-6),None);other=next((o for o in outcomes if norm_name(o.get("name"))!=norm_name(target_name) and abs(num(o.get("point"))+num(target_point))<1e-6),None)
    if not target or not other:return None
    a=1/num(target.get("price"),999);b=1/num(other.get("price"),999);return a/(a+b) if a+b else None
def consensus(event,market,name,point=None):
    vals=[];books=[];ages=[]
    for b,m in market_rows(event,market):
        if b.get("key") not in REF_BOOKS:continue
        p=fair_book_probability(m.get("outcomes",[]),name,point,market)
        if p is None:continue
        vals.append(p);books.append(b.get("key"))
        try:ages.append(max(0,(NOW-parse_dt(m.get("last_update",b.get("last_update")))).total_seconds()/60))
        except Exception:pass
    if not vals:return {"p":None,"n":0,"disp":None,"books":[],"age_min":None}
    return {"p":median(vals),"n":len(vals),"disp":pstdev(vals) if len(vals)>1 else 0.0,"books":books,"age_min":median(ages) if ages else None}

def fit_platt(rows,epochs=500,lr=.025):
    a=0.0;b=1.0
    for ep in range(epochs):
        eta=lr*(1-ep/(epochs*1.4))
        for p,y in rows:
            p=clamp(p,.01,.99);x=math.log(p/(1-p));q=1/(1+math.exp(-max(-25,min(25,a+b*x))));e=q-y;a-=eta*e;b-=eta*(e*x+.002*(b-1))
    return a,b
def platt_predict(model,p):
    if not model:return p
    a,b=model;p=clamp(p,.01,.99);x=math.log(p/(1-p));return clamp(1/(1+math.exp(-max(-25,min(25,a+b*x)))))
def brier(ps,ys):return mean((p-y)**2 for p,y in zip(ps,ys)) if ps else None

def load_history():
    if not HISTORY_FILE.exists():return {}
    out={};bad=0
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:r=json.loads(line);out[str(r["game_pk"])]=r
        except Exception:bad+=1
    if bad:logging.warning("Historique: %d ligne(s) corrompue(s) ignorée(s)",bad)
    return out
def write_history(hist):
    HISTORY_FILE.parent.mkdir(parents=True,exist_ok=True);tmp=HISTORY_FILE.with_suffix(HISTORY_FILE.suffix+".tmp");rows=sorted(hist.values(),key=lambda r:(r.get("game_date",""),int(r.get("game_pk",0))));text="\n".join(json.dumps(r,ensure_ascii=False,separators=(",",":")) for r in rows)+("\n" if rows else "")
    for line in text.splitlines():json.loads(line)
    tmp.write_text(text,encoding="utf-8");tmp.replace(HISTORY_FILE)
def ensure_game_record(hist,g):
    k=str(g["gamePk"])
    if k not in hist or hist[k].get("schema_version")!=SCHEMA_VERSION:hist[k]={"schema_version":SCHEMA_VERSION,"game_pk":g["gamePk"],"game_date":g["gameDate"],"home":g["teams"]["home"]["team"]["name"],"away":g["teams"]["away"]["team"]["name"],"status":"PENDING","snapshots":[]}
    return hist[k]
def should_add_snapshot(record,snapshot):
    snaps=record.get("snapshots",[])
    if not snaps:return True
    last=snaps[-1]
    try:mins=abs((parse_dt(snapshot["analyzed_at"])-parse_dt(last["analyzed_at"])).total_seconds())/60
    except Exception:mins=999
    if mins>=SNAPSHOT_MIN_MINUTES:return True
    keys=("market_home","p_model","p_ensemble","home_mu","away_mu","directional_pick","verdict_type");return any(str(last.get(k))!=str(snapshot.get(k)) for k in keys)
def settle_history(hist):
    pending=[r for r in hist.values() if r.get("status","PENDING")=="PENDING"];dates=sorted({r.get("game_date","")[:10] for r in pending if r.get("game_date")});settled=0;changed=False
    for day in dates:
        try:games={str(g["gamePk"]):g for g in mlb_schedule(day,hydrate="")}
        except Exception:continue
        for r in [x for x in pending if x.get("game_date","")[:10]==day]:
            g=games.get(str(r["game_pk"]));state=g.get("status",{}).get("abstractGameState") if g else None;detailed=g.get("status",{}).get("detailedState","") if g else ""
            if not g:continue
            if state!="Final":
                if any(x in detailed.lower() for x in ("postpon","cancel")):r["status"]="POSTPONED";changed=True
                continue
            hs=num(g.get("teams",{}).get("home",{}).get("score"));as_=num(g.get("teams",{}).get("away",{}).get("score"));r.update({"status":"FINAL","home_score":int(hs),"away_score":int(as_),"home_win":1 if hs>as_ else 0,"settled_at":NOW.isoformat()})
            for s in r.get("snapshots",[]):
                for p in s.get("selected_picks",[]):
                    if p["market"]=="ML":v=(hs-as_) if norm_name(p["name"])==norm_name(r["home"]) else (as_-hs)
                    elif p["market"]=="RUNLINE":v=(hs+num(p["point"])-as_) if norm_name(p["name"])==norm_name(r["home"]) else (as_+num(p["point"])-hs)
                    else:v=(hs+as_-num(p["point"])) if p["name"].lower()=="over" else (num(p["point"])-hs-as_)
                    res="W" if v>1e-9 else "L" if v<-1e-9 else "P";p["result"]=res;stake=num(p.get("stake_eur"));price=num(p.get("price"));p["profit_eur"]=round(stake*(price-1),4) if res=="W" else -round(stake,4) if res=="L" else 0.0
            settled+=1;changed=True
    if changed:write_history(hist)
    return settled

def latest_pregame_snapshot(r):
    snaps=[s for s in r.get("snapshots",[]) if num(s.get("seconds_to_game"),-1)>=0 and s.get("feature_version")==FEATURE_VERSION];return max(snaps,key=lambda s:s.get("analyzed_at","")) if snaps else None
def run_training_rows(hist):
    games=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s:continue
        try:games.append((r.get("game_date",""),s,float(r["home_score"]),float(r["away_score"])))
        except Exception:pass
    games.sort(key=lambda z:z[0]);return games
def run_model_state(hist):
    games=run_training_rows(hist);out={"active":False,"model":None,"n":len(games),"rmse_model":None,"rmse_base":None,"folds":0}
    if len(games)<RUN_MODEL_MIN_GAMES:return out
    base_err=[];model_err=[];folds=0
    for frac in (.60,.70,.80):
        cut=int(len(games)*frac);end=min(len(games),cut+max(20,int(len(games)*.10)))
        if cut<80 or end-cut<15:continue
        train=[]
        for _,s,hs,as_ in games[:cut]:train.append((s["run_features_home"],hs-num(s["base_home"])));train.append((s["run_features_away"],as_-num(s["base_away"])))
        m=fit_linear_residual(train)
        for _,s,hs,as_ in games[cut:end]:
            ph=num(s["base_home"])+clamp(linear_predict(m,s["run_features_home"]),-2.0,2.0);pa=num(s["base_away"])+clamp(linear_predict(m,s["run_features_away"]),-2.0,2.0);base_err += [num(s["base_home"])-hs,num(s["base_away"])-as_];model_err += [ph-hs,pa-as_]
        folds+=1
    if not folds:return out
    rb,rm=rmse(base_err),rmse(model_err);out.update({"rmse_base":rb,"rmse_model":rm,"folds":folds})
    if rm+.04<rb:
        allrows=[]
        for _,s,hs,as_ in games:allrows.append((s["run_features_home"],hs-num(s["base_home"])));allrows.append((s["run_features_away"],as_-num(s["base_away"])))
        out["model"]=fit_linear_residual(allrows);out["active"]=True
    return out
def project_runs(ctx,run_state):
    h,a=ctx["base_home"],ctx["base_away"]
    if run_state["active"] and run_state["model"]:h+=clamp(linear_predict(run_state["model"],ctx["run_features_home"]),-2.0,2.0);a+=clamp(linear_predict(run_state["model"],ctx["run_features_away"]),-2.0,2.0)
    return clamp(h,2.0,8.0),clamp(a,2.0,8.0)

def calibration_state(hist):
    rows=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if s and s.get("p_model_raw") is not None:rows.append((r.get("game_date",""),num(s["p_model_raw"],.5),int(r.get("home_win",0))))
    rows.sort(key=lambda z:z[0]);n=len(rows);out={"active":False,"model":None,"n":n,"brier_raw":None,"brier_cal":None,"folds":0}
    if n<CAL_MIN_GAMES:return out
    raw=[];cal=[];ys=[];folds=0
    for frac in (.60,.70,.80):
        cut=int(n*frac);end=min(n,cut+max(20,int(n*.10)))
        if cut<100 or end-cut<15:continue
        m=fit_platt([(p,y) for _,p,y in rows[:cut]])
        for _,p,y in rows[cut:end]:raw.append(p);cal.append(platt_predict(m,p));ys.append(y)
        folds+=1
    if not folds:return out
    br=brier(raw,ys);bc=brier(cal,ys);out.update({"brier_raw":br,"brier_cal":bc,"folds":folds})
    if bc is not None and br is not None and bc+.001<br:out["active"]=True;out["model"]=fit_platt([(p,y) for _,p,y in rows])
    return out
def skill_state(hist):
    pm=[];pk=[];ys=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s or s.get("p_model") is None or s.get("market_home") is None:continue
        pm.append(num(s["p_model"],.5));pk.append(num(s["market_home"],.5));ys.append(int(r.get("home_win",0)))
    if len(ys)<50:return {"n":len(ys),"brier_model":None,"brier_market":None,"model_weight":.42}
    bm=brier(pm,ys);bk=brier(pk,ys);w=.62 if bm+.008<bk else .52 if bm<bk else .30 if bm>bk+.012 else .40;return {"n":len(ys),"brier_model":bm,"brier_market":bk,"model_weight":w}
def directional_empirical(hist,verdict_type,score):
    vals=[];lo=max(0,math.floor(score/2)*2);hi=min(10,lo+2)
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s or s.get("verdict_type")!=verdict_type:continue
        sc=num(s.get("direction_confidence"),-1)
        if lo<=sc<hi and s.get("directional_pick"):
            correct=(norm_name(s["directional_pick"])==norm_name(r["home"]) and r.get("home_win")==1) or (norm_name(s["directional_pick"])==norm_name(r["away"]) and r.get("home_win")==0);vals.append(1 if correct else 0)
    return (mean(vals),len(vals)) if vals else (None,0)
def market_verdict(ctx,p_model,p_market,market_meta,skill,hist):
    home,away=ctx["home"],ctx["away"];model_side=home if p_model>=.5 else away;model_strength=max(p_model,1-p_model);q=ctx["quality"];refs=market_meta.get("n",0);disp=market_meta.get("disp") or 0;market_quality=clamp((min(refs,4)/4)*(.95-min(.45,disp*8)),0,1)
    if p_market is None:
        score=clamp(3.0+3.5*q+3.0*min(1,(model_strength-.5)/.18),0,9.0);typ="MODEL_ONLY";side=model_side;text=f"🧠 **MODÈLE SEUL** — consensus marché insuffisant. Le modèle préfère **{side}** ({pct(model_strength)})."
    else:
        market_side=home if p_market>=.5 else away;market_strength=max(p_market,1-p_market);gap=abs(p_model-p_market)
        if model_side==market_side:
            typ="CONFIRMED";side=model_side;score=3.2+2.1*q+1.5*market_quality+1.8*min(1,(model_strength-.5)/.18)+1.2*min(1,(market_strength-.5)/.15);text=f"✅ **MARCHÉ CONFIRMÉ** — le marché penche vers **{market_side}** et le modèle indépendant confirme. Pick: **{side}**."
        elif q>=.72 and model_strength>=.55 and gap>=.065:
            typ="CONTRARIAN";side=model_side;skill_bonus=.7 if skill.get("brier_model") is not None and skill.get("brier_market") is not None and skill["brier_model"]<skill["brier_market"] else 0;score=2.8+2.2*q+1.2*market_quality+2.0*min(1,(model_strength-.5)/.18)+1.2*min(1,gap/.15)+skill_bonus;text=f"🔄 **MARCHÉ CONTESTÉ** — le marché favorise **{market_side}**, mais le modèle indépendant préfère **{model_side}**. Pick contrarian: **{side}**."
        else:
            typ="UNCERTAIN";side=home if (.55*p_model+.45*p_market)>=.5 else away;score=2.5+1.8*q+1.0*market_quality+.8*min(1,abs((.55*p_model+.45*p_market)-.5)/.10);text=f"⚠️ **DÉSACCORD NON RÉSOLU** — marché et modèle ne convergent pas assez. Léger avantage **{side}**, sans signal fort."
    score=clamp(score,0,9.7);emp,n=directional_empirical(hist,typ,score)
    if n>=20:score=.65*score+.35*clamp(2.0+(emp-.50)*18,1.5,9.5)
    return {"side":side,"type":typ,"confidence":score,"empirical":emp,"emp_n":n,"text":text}

def stake_for(pw,pp,pl,price):
    nonpush=pw+pl
    if nonpush<=0 or price<=1:return 0.0,0.0
    p=pw/nonpush;b=price-1;k=max(0,(p*price-1)/b);eur=min(BANKROLL*k*.25,UNIT*MAX_STAKE_UNITS);units=eur/UNIT if UNIT>0 else 0;units=math.floor(units*4+1e-9)/4
    if units<.25:return 0.0,0.0
    return units,round(units*UNIT,2)
def evaluate(ctx,kind,name,price,point,model_tuple,cons):
    pw,pp,pl=model_tuple;cond_model=pw/(pw+pl) if pw+pl else .5
    if cons["p"] is not None and kind!="ML":
        mq=clamp(min(cons["n"],4)/4,0,1);wm=.45+.20*mq;cond_final=(1-wm)*cond_model+wm*cons["p"];cond_final=clamp(cond_final,cons["p"]-.10,cons["p"]+.10);pw=(1-pp)*cond_final;pl=(1-pp)*(1-cond_final)
    be=1/price;cond=pw/(pw+pl) if pw+pl else 0;edge=cond-be;ev=pw*price+pp-1;fair=(1-pp)/pw if pw>0 else 99;market_quality=min(1,cons["n"]/4)*(1-min(.5,(cons["disp"] or 0)*8)) if cons["p"] is not None else 0;q=.72*ctx["quality"]+.28*market_quality;reasons=[]
    if cons["n"]<2:reasons.append(f"consensus insuffisant ({cons['n']} book)")
    if q<MIN_QUALITY:reasons.append(f"qualité {q*10:.1f}/10 < {MIN_QUALITY*10:.1f}")
    if edge<MIN_EDGE:reasons.append(f"edge {edge*100:+.1f} pts < {MIN_EDGE*100:.1f}")
    if ev<MIN_EV:reasons.append(f"EV {ev*100:+.1f}% < {MIN_EV*100:.1f}%")
    units,stake=stake_for(pw,pp,pl,price)
    if units<=0 and not reasons:reasons.append("Kelly prudent < 0.25u")
    return {"market":kind,"name":name,"point":point,"price":price,"p_win":pw,"p_push":pp,"p_loss":pl,"p_cond":cond,"fair":fair,"edge":edge,"ev":ev,"quality":q,"refs":cons["n"],"units":units,"stake_eur":stake,"selected":not reasons,"reason":"OK" if not reasons else " ; ".join(reasons)}

def analyze(g,event,match_delta,states,hist):
    run_state,cal_state,skill=states;ctx=game_context(g);home,away=ctx["home"],ctx["away"];hmu,amu=project_runs(ctx,run_state);raw=ml_prob(hmu,amu);p_model=platt_predict(cal_state["model"],raw) if cal_state["active"] else raw;con_home=consensus(event,"h2h",home);p_market=con_home["p"];p_ensemble=p_model if p_market is None else clamp(skill["model_weight"]*p_model+(1-skill["model_weight"])*p_market);verdict=market_verdict(ctx,p_model,p_market,con_home,skill,hist);evals=[]
    _,wm=winamax_outcomes(event,"h2h")
    if wm:
        for o in wm.get("outcomes",[]):
            name=o.get("name");price=num(o.get("price"))
            if price>1:
                p=p_ensemble if norm_name(name)==norm_name(home) else 1-p_ensemble;evals.append(evaluate(ctx,"ML",name,price,None,(p,0,1-p),consensus(event,"h2h",name)))
    _,wm=winamax_outcomes(event,"spreads")
    if wm:
        for o in wm.get("outcomes",[]):
            name=o.get("name");point=num(o.get("point"));price=num(o.get("price"))
            if price>1:evals.append(evaluate(ctx,"RUNLINE",name,price,point,line_probs(hmu,amu,"RUNLINE",name,point,home,away),consensus(event,"spreads",name,point)))
    _,wm=winamax_outcomes(event,"totals")
    if wm:
        for o in wm.get("outcomes",[]):
            name=o.get("name");point=num(o.get("point"));price=num(o.get("price"))
            if price>1:evals.append(evaluate(ctx,"TOTAL",name,price,point,line_probs(hmu,amu,"TOTAL",name,point,home,away),consensus(event,"totals",name,point)))
    picks=sorted([x for x in evals if x["selected"]],key=lambda z:z["ev"],reverse=True);seconds_to_game=(parse_dt(g["gameDate"])-NOW).total_seconds();snapshot={"feature_version":FEATURE_VERSION,"analyzed_at":NOW.isoformat(),"seconds_to_game":round(seconds_to_game),"odds_event_id":event.get("id"),"odds_commence":event.get("commence_time"),"match_delta_min":round(match_delta,1),"base_home":round(ctx["base_home"],4),"base_away":round(ctx["base_away"],4),"home_mu":round(hmu,4),"away_mu":round(amu,4),"run_features_home":[round(x,6) for x in ctx["run_features_home"]],"run_features_away":[round(x,6) for x in ctx["run_features_away"]],"run_model_active":run_state["active"],"p_model_raw":round(raw,6),"p_model":round(p_model,6),"market_home":round(p_market,6) if p_market is not None else None,"p_ensemble":round(p_ensemble,6),"market_refs":con_home["n"],"market_disp":con_home["disp"],"quality":round(ctx["quality"],4),"verdict_type":verdict["type"],"directional_pick":verdict["side"],"direction_confidence":round(verdict["confidence"],3),"home_lineup_count":ctx["home_lineup"]["count"],"away_lineup_count":ctx["away_lineup"]["count"],"home_hand":ctx["home_hand"],"away_hand":ctx["away_hand"],"home_statcast":ctx["home_statcast"],"away_statcast":ctx["away_statcast"],"selected_picks":[{k:v for k,v in x.items() if k not in ("selected","reason")} for x in picks]}
    rec=ensure_game_record(hist,g)
    if should_add_snapshot(rec,snapshot):rec.setdefault("snapshots",[]).append(snapshot)
    return ctx,hmu,amu,raw,p_model,con_home,p_ensemble,verdict,evals,picks,snapshot

def representative(evals,market):
    xs=[x for x in evals if x["market"]==market];return max(xs,key=lambda z:(z["selected"],z["ev"])) if xs else None

def discord_request(method="GET",payload=None):
    if not DISCORD_URL:return None,None
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8") if payload is not None else None;req=urllib.request.Request(DISCORD_URL,data=data,headers={"User-Agent":"MLB-Betting-Bot-V8","Accept":"application/json","Content-Type":"application/json"},method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as r:return r.status,r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace");logging.error("Discord HTTP %s | %s",e.code,body[:500]);return e.code,body
    except Exception as e:logging.error("Discord réseau: %s",e);return None,str(e)
def discord_test():
    if not DISCORD_URL:logging.warning("Discord désactivé: secret absent");return False
    s,_=discord_request("GET");logging.info("Discord webhook %s","OK" if s==200 else f"ERREUR {s}");return s==200
def send_embed(title,fields,color=3447003):
    if not DISCORD_URL:return False
    fs=[{"name":n[:256],"value":v[:1024],"inline":False} for n,v in fields if v];payload={"username":"MLB Betting Bot","allowed_mentions":{"parse":[]},"embeds":[{"title":title[:256],"color":color,"fields":fs,"footer":{"text":f"MLB V{VERSION} • modèle + marché • aucune garantie de gain"}}]}
    for attempt in range(3):
        s,b=discord_request("POST",payload)
        if s in (200,204):time.sleep(.30);return True
        if s==429:
            try:w=max(.5,num(json.loads(b).get("retry_after"),1.5))
            except Exception:w=1.5
            time.sleep(w);continue
        if s in (401,403,404):return False
        time.sleep(1+attempt)
    return False
def eval_text(x):
    if not x:return "Cote non fournie par **Winamax via The Odds API** pour ce marché."
    point=f" {x['point']:+g}" if x["point"] is not None and x["market"]=="RUNLINE" else f" {x['point']:g}" if x["point"] is not None else "";head=f"**{x['market']} — {x['name']}{point} @ {x['price']:.2f}**";stats=f"Prob {pct(x['p_cond'])} • Fair {x['fair']:.2f} • Edge {x['edge']*100:+.1f} pts • EV {x['ev']*100:+.1f}% • refs {x['refs']} • qualité {x['quality']*10:.1f}/10"
    if x["selected"]:return head+"\n"+stats+f"\n✅ Prix jouable • **{x['units']:.2f}u = {x['stake_eur']:.2f} €**"
    return head+"\n"+stats+"\n🟡 Prix non retenu • "+x["reason"]
def fmt_statcast(x):
    if not x.get("available"):return "N/A"
    parts=[]
    if x.get("xwoba") is not None:parts.append(f"xwOBA {x['xwoba']:.3f}")
    if x.get("xslg") is not None:parts.append(f"xSLG {x['xslg']:.3f}")
    if x.get("xba") is not None:parts.append(f"xBA {x['xba']:.3f}")
    return " • ".join(parts) or "N/A"
def send_game(g,ctx,hmu,amu,raw,p_model,con,p_ensemble,verdict,evals,picks,states,snap):
    run_state,cal_state,skill=states;probs=(f"Modèle indépendant **{ctx['home']} {pct(p_model)}** • {ctx['away']} {pct(1-p_model)}\nMarché **{pct(con['p'])} {ctx['home']}** ({con['n']} books) • ensemble final {pct(p_ensemble)}\nProjection score: **{ctx['home']} {hmu:.2f} – {amu:.2f} {ctx['away']}** • total {hmu+amu:.2f}\nMatching odds: Δ {snap['match_delta_min']:.0f} min • ML runs {'ACTIF' if run_state['active'] else 'inactif'} n={run_state['n']} • calibration {'ACTIVE' if cal_state['active'] else 'inactive'} n={cal_state['n']}")
    emp=f" • historique similaire {verdict['empirical']*100:.1f}% ({verdict['emp_n']})" if verdict.get("empirical") is not None else "";direction=verdict["text"]+f"\nConfiance directionnelle: **{verdict['confidence']:.1f}/10**{emp}";starters=(f"{ctx['away']}: **{ctx['away_sp']}** • {pitcher_line(ctx['away_sp_stats'],ctx['away_hand'])}\n{ctx['home']}: **{ctx['home_sp']}** • {pitcher_line(ctx['home_sp_stats'],ctx['home_hand'])}");advanced=(f"Lineups H/A: {ctx['home_lineup']['count']}/9 – {ctx['away_lineup']['count']}/9 • splits vs main opposée: {'OK' if ctx['home_split'] else 'N/A'}/{'OK' if ctx['away_split'] else 'N/A'}\nStatcast {ctx['home']}: {fmt_statcast(ctx['home_statcast'])}\nStatcast {ctx['away']}: {fmt_statcast(ctx['away_statcast'])}\nBullpen ERA H/A: {ctx['home_bp']['era']:.2f}/{ctx['away_bp']['era']:.2f} • fatigue {ctx['home_bp']['load']:.2f}/{ctx['away_bp']['load']:.2f}");context=(f"Park factor {ctx['park']:.3f} • météo: {ctx['weather']['text']}\nForme 10: {ctx['home']} {ctx['home_recent']['win_pct']*100:.0f}% (RD {ctx['home_recent']['run_diff_pg']:+.2f}/g) • {ctx['away']} {ctx['away_recent']['win_pct']*100:.0f}% (RD {ctx['away_recent']['run_diff_pg']:+.2f}/g)\nQualité données: **{ctx['quality']*10:.1f}/10**");markets="\n\n".join(eval_text(representative(evals,m)) for m in ("ML","RUNLINE","TOTAL"));verdict_text="\n".join(f"• **{x['market']} {x['name']} {x['point'] if x['point'] is not None else ''} @ {x['price']:.2f}** • {x['units']:.2f}u" for x in picks[:3]) if picks else f"Pick directionnel: **{verdict['side']}**. Le prix Winamax est évalué séparément et aucun marché ne passe actuellement tous les filtres de mise."
    return send_embed(f"⚾ MLB V{VERSION} • {ctx['away']} @ {ctx['home']}",[("🕒 Match",local_time(g["gameDate"])+" (Paris)"),("🎯 Probabilités",probs),("🧭 Lecture du marché",direction),("🧑 Starters",starters),("🧪 Lineup / splits / Statcast / bullpen",advanced),("🔬 Contexte",context),("💰 Winamax — prix",markets),("✅ Verdict",verdict_text)],5763719 if picks else 16766720 if verdict["type"] in ("CONFIRMED","CONTRARIAN") else 9807270)

def performance(hist):
    rows=[];bets=[]
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        s=latest_pregame_snapshot(r)
        if not s:continue
        y=int(r.get("home_win",0));pm=num(s.get("p_model"),.5);pe=num(s.get("p_ensemble"),.5);pk=s.get("market_home");pick=s.get("directional_pick");correct=None
        if pick:correct=(norm_name(pick)==norm_name(r["home"]) and y==1) or (norm_name(pick)==norm_name(r["away"]) and y==0)
        rows.append((s,y,pm,pe,num(pk,.5) if pk is not None else None,correct));bets += [p for p in s.get("selected_picks",[]) if p.get("result") in ("W","L","P")]
    out={"games":len(rows),"brier_model":None,"brier_ensemble":None,"brier_market":None,"direction_acc":None,"direction_n":0,"profit":0.0,"roi":None,"bets":len(bets),"by_type":{},"by_conf":{}}
    if rows:
        ys=[r[1] for r in rows];out["brier_model"]=brier([r[2] for r in rows],ys);out["brier_ensemble"]=brier([r[3] for r in rows],ys);mk=[r for r in rows if r[4] is not None]
        if mk:out["brier_market"]=brier([r[4] for r in mk],[r[1] for r in mk])
        cs=[r[5] for r in rows if r[5] is not None];out["direction_n"]=len(cs);out["direction_acc"]=mean(cs) if cs else None
        for s,_,_,_,_,c in rows:
            if c is None:continue
            typ=s.get("verdict_type","?");out["by_type"].setdefault(typ,[]).append(1 if c else 0);sc=num(s.get("direction_confidence"));label="0-4" if sc<4 else "4-6" if sc<6 else "6-8" if sc<8 else "8-10";out["by_conf"].setdefault(label,[]).append(1 if c else 0)
        out["by_type"]={k:(len(v),mean(v)) for k,v in out["by_type"].items()};out["by_conf"]={k:(len(v),mean(v)) for k,v in out["by_conf"].items()}
    profit=sum(num(p.get("profit_eur")) for p in bets);stake=sum(num(p.get("stake_eur")) for p in bets if p.get("result")!="P");out["profit"]=profit;out["roi"]=profit/stake if stake else None;return out

def top_messages(game_results):
    dirs=sorted(game_results,key=lambda x:x["verdict"]["confidence"],reverse=True)[:3];body="\n\n".join(f"**#{i+1} {x['ctx']['away']} @ {x['ctx']['home']}**\n{x['verdict']['type']} • **{x['verdict']['side']}** • confiance **{x['verdict']['confidence']:.1f}/10** • modèle {pct(x['p_model'] if norm_name(x['verdict']['side'])==norm_name(x['ctx']['home']) else 1-x['p_model'])}" for i,x in enumerate(dirs)) or "Aucun match analysé.";send_embed("🏆 TOP 3 LECTURES MONEYLINE",[("Direction",body)],16766720)
    for market,title in (("RUNLINE","⚾ TOP 3 RUN LINE"),("TOTAL","📈 TOP 3 TOTAUX")):
        xs=[]
        for r in game_results:
            for p in r["picks"]:
                if p["market"]==market:q=dict(p);q["home"]=r["ctx"]["home"];q["away"]=r["ctx"]["away"];xs.append(q)
        xs=sorted(xs,key=lambda z:(z["ev"],z["quality"]),reverse=True)[:3];txt="\n\n".join(f"**#{i+1} {x['away']} @ {x['home']}**\n{x['name']} {x['point']} @ **{x['price']:.2f}** • Prob {pct(x['p_cond'])} • EV {x['ev']*100:+.1f}% • **{x['units']:.2f}u**" for i,x in enumerate(xs)) if xs else "Aucun prix Winamax qualifié aujourd'hui.";send_embed(title,[("Sélection V8",txt)],16766720)

def main():
    logging.info("="*64);logging.info("MLB BETTING BOT V%s | %s",VERSION,TARGET_DATE);logging.info("="*64)
    if not ODDS_KEY:raise SystemExit("ODDS_API_KEY absente")
    discord_ok=discord_test();hist=load_history();settled=settle_history(hist);logging.info("Historique V8 | %d matchs | %d réglés maintenant",len(hist),settled);run_state=run_model_state(hist);cal_state=calibration_state(hist);skill=skill_state(hist);states=(run_state,cal_state,skill)
    logging.info("Run ML | n=%d actif=%s | RMSE modèle=%s base=%s folds=%d",run_state["n"],run_state["active"],f"{run_state['rmse_model']:.3f}" if run_state["rmse_model"] is not None else "-",f"{run_state['rmse_base']:.3f}" if run_state["rmse_base"] is not None else "-",run_state["folds"]);logging.info("Calibration | n=%d active=%s | Brier raw=%s cal=%s",cal_state["n"],cal_state["active"],f"{cal_state['brier_raw']:.4f}" if cal_state["brier_raw"] is not None else "-",f"{cal_state['brier_cal']:.4f}" if cal_state["brier_cal"] is not None else "-");logging.info("Skill | n=%d | Brier modèle=%s marché=%s | poids modèle=%.2f",skill["n"],f"{skill['brier_model']:.4f}" if skill["brier_model"] is not None else "-",f"{skill['brier_market']:.4f}" if skill["brier_market"] is not None else "-",skill["model_weight"])
    games=mlb_schedule(TARGET_DATE);events=odds_api();matches=match_odds_events(games,events);logging.info("Matchs MLB=%d | événements odds=%d | appariés=%d",len(games),len(events),len(matches));results=[];analyzed=0
    for g in games:
        if parse_dt(g["gameDate"])<=NOW:logging.info("Skip déjà commencé: %s @ %s",g["teams"]["away"]["team"]["name"],g["teams"]["home"]["team"]["name"]);continue
        pair=matches.get(str(g["gamePk"]))
        if not pair:logging.warning("Odds non appariées: %s @ %s",g["teams"]["away"]["team"]["name"],g["teams"]["home"]["team"]["name"]);continue
        event,delta=pair
        try:
            ctx,hmu,amu,raw,p_model,con,p_ensemble,verdict,evals,picks,snap=analyze(g,event,delta,states,hist);analyzed+=1;results.append({"ctx":ctx,"p_model":p_model,"verdict":verdict,"picks":picks})
            if discord_ok:send_game(g,ctx,hmu,amu,raw,p_model,con,p_ensemble,verdict,evals,picks,states,snap)
            logging.info("%s @ %s | modèle=%s marché=%s ensemble=%s | %s %s %.1f/10 | bets=%d",ctx["away"],ctx["home"],pct(p_model),pct(con["p"]),pct(p_ensemble),verdict["type"],verdict["side"],verdict["confidence"],len(picks))
        except Exception as e:logging.exception("Analyse %s @ %s: %s",g["teams"]["away"]["team"]["name"],g["teams"]["home"]["team"]["name"],e)
    write_history(hist)
    if discord_ok:top_messages(results)
    perf=performance(hist);logging.info("V%s terminé | %d matchs futurs analysés | %d snapshots totaux",VERSION,analyzed,sum(len(r.get("snapshots",[])) for r in hist.values()));logging.info("Performance | games=%d | direction=%s (%d) | Brier modèle=%s ensemble=%s marché=%s | bets=%d profit=%.2f€ ROI=%s",perf["games"],pct(perf["direction_acc"]) if perf["direction_acc"] is not None else "-",perf["direction_n"],f"{perf['brier_model']:.4f}" if perf["brier_model"] is not None else "-",f"{perf['brier_ensemble']:.4f}" if perf["brier_ensemble"] is not None else "-",f"{perf['brier_market']:.4f}" if perf["brier_market"] is not None else "-",perf["bets"],perf["profit"],pct(perf["roi"]) if perf["roi"] is not None else "-")
    if perf["by_type"]:logging.info("Verdicts: %s"," | ".join(f"{k} n={n} acc={a*100:.1f}%" for k,(n,a) in perf["by_type"].items()))
    if perf["by_conf"]:logging.info("Confiance: %s"," | ".join(f"{k} n={n} acc={a*100:.1f}%" for k,(n,a) in perf["by_conf"].items()))

if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception:logging.exception("ERREUR FATALE");raise
