#!/usr/bin/env python3
"""Point-in-time validation for V11 sharp benchmark + V11.1 baseball shadow.

Default mode preserves the V11 sharp benchmark. `--baseball-shadow` collects
five baseball feature blocks and grades them in shadow only; official picks are
never modified by this file.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import bot as core
import bot_v11 as v11

OUT = Path("data/v11_benchmark_report.json")
SHADOW_OUT = Path(os.getenv("V11_BASEBALL_SHADOW_FILE", "data/v11_baseball_shadow.jsonl"))
SHADOW_REPORT = Path(os.getenv("V11_BASEBALL_SHADOW_REPORT", "data/v11_baseball_shadow_report.json"))
SHADOW_VERSION = "11.1.0-baseball-shadow-v1"
WEIGHT_GRID = tuple(i / 20 for i in range(5, 17))

# Fixed conservative shadow weights. They are not production parameters.
W_BP = float(os.getenv("V11_BASEBALL_W_BULLPEN", "0.16") or .16)
W_SP = float(os.getenv("V11_BASEBALL_W_STARTER", "0.14") or .14)
W_LU = float(os.getenv("V11_BASEBALL_W_LINEUP", "0.12") or .12)
W_MU = float(os.getenv("V11_BASEBALL_W_MATCHUP", "0.10") or .10)
SHADOW_MIN_FINAL = max(40, int(os.getenv("V11_BASEBALL_MIN_FINAL", "80") or 80))
SHADOW_MIN_HOLDOUT = max(20, int(os.getenv("V11_BASEBALL_MIN_HOLDOUT", "30") or 30))
SHADOW_MIN_GAIN = max(0.0, float(os.getenv("V11_BASEBALL_MIN_BRIER_GAIN", "0.0015") or .0015))
SHADOW_MIN_GAIN_PROB = core.clamp(float(os.getenv("V11_BASEBALL_MIN_GAIN_PROB", "0.85") or .85), .5, 1.0)
SHADOW_MIN_COVERAGE = core.clamp(float(os.getenv("V11_BASEBALL_MIN_FULL_COVERAGE", "0.55") or .55), .25, 1.0)
HTTP_TIMEOUT = max(4.0, float(os.getenv("V11_SHADOW_HTTP_TIMEOUT", "10") or 10))
ORDER_W = (1.08, 1.10, 1.10, 1.08, 1.03, .98, .94, .90, .88)
MLB_API = "https://statsapi.mlb.com/api"
METEO_API = "https://api.open-meteo.com/v1/forecast"
_HTTP_CACHE = {}


def _brier(rows, field):
    xs = [(core.num(r.get(field), .5), core.num(r.get("y"), 0)) for r in rows if r.get(field) is not None]
    return sum((p-y) ** 2 for p, y in xs) / len(xs) if xs else None


def _logloss(rows, field):
    xs = [(core.clamp(core.num(r.get(field), .5), .001, .999), core.num(r.get("y"), 0)) for r in rows if r.get(field) is not None]
    return sum(-(y * math.log(p) + (1-y) * math.log(1-p)) for p, y in xs) / len(xs) if xs else None


def _snapshot_rows(snapshot, key):
    out = []
    for b in snapshot.get("market_snapshot") or []:
        book = {"key": b.get("book"), "last_update": b.get("last_update")}
        for m in b.get("markets") or []:
            if m.get("key") == key:
                out.append((book, m))
    return out


def _snapshot_model_home(snapshot, home):
    """Return independent effective ML probability for the home team."""
    for rec in snapshot.get("open_market_options") or []:
        if rec.get("market") != "ML" or core.norm_name(rec.get("name")) != core.norm_name(home):
            continue
        for key in ("p_effective_independent", "p_effective", "p_model"):
            if rec.get(key) is not None:
                return core.clamp(core.num(rec.get(key), .5), .001, .999)
    rec = (snapshot.get("model_recommendations") or {}).get("ML") or {}
    if rec:
        value = None
        for key in ("p_effective_independent", "p_effective", "p_model"):
            if rec.get(key) is not None:
                value = core.clamp(core.num(rec.get(key), .5), .001, .999)
                break
        if value is not None:
            return value if core.norm_name(rec.get("name")) == core.norm_name(home) else 1-value
    return core.clamp(core.num(snapshot.get("p_model"), .5), .001, .999) if snapshot.get("p_model") is not None else None


def historical_sharp(snapshot, name, market="h2h", point=None):
    try:
        asof = core.parse_dt(snapshot.get("analyzed_at"))
    except Exception:
        return None, []
    comps = []
    for book, mk in _snapshot_rows(snapshot, market):
        key = str(book.get("key") or "")
        if key not in set(v11.sharp_books()):
            continue
        p = core.fair_book_probability(mk.get("outcomes") or [], name, point, market)
        if p is None:
            continue
        try:
            stamp = mk.get("last_update", book.get("last_update"))
            age = max(0.0, (asof - core.parse_dt(stamp)).total_seconds() / 60.0) if stamp else 10.0
        except Exception:
            age = 10.0
        if age > v11.MAX_MARKET_AGE_MIN:
            continue
        comps.append({"book": key, "p": core.clamp(p, .001, .999), "age_min": age})
    if not comps:
        return None, []
    med = median([x["p"] for x in comps])
    for c in comps:
        freshness = v11._freshness_weight(c["age_min"])
        robust = 1.0 / (1.0 + (abs(c["p"] - med) / v11.ROBUST_SCALE) ** 2)
        c["weight"] = freshness * robust
    den = sum(x["weight"] for x in comps)
    p = sum(x["p"] * x["weight"] for x in comps) / den if den > 0 else None
    return (core.clamp(p, .001, .999) if p is not None else None), comps


def _latest_snapshot(record):
    xs = [s for s in record.get("snapshots") or [] if core.num(s.get("seconds_to_game"), -1) >= 0 and s.get("market_snapshot")]
    if not xs:
        return None
    return min(xs, key=lambda s: (core.num(s.get("seconds_to_game"), 10**12), -core.parse_dt(s.get("analyzed_at")).timestamp()))


def collect(hist):
    rows = []
    book_rows = {b: [] for b in v11.sharp_books()}
    for rec in hist.values():
        if rec.get("status") != "FINAL" or rec.get("home_win") not in (0, 1):
            continue
        snap = _latest_snapshot(rec)
        if not snap:
            continue
        home = rec.get("home")
        sharp, comps = historical_sharp(snap, home, "h2h")
        row = {
            "date": rec.get("game_date") or snap.get("analyzed_at") or "",
            "game_pk": rec.get("game_pk"), "y": int(rec.get("home_win")),
            "model": _snapshot_model_home(snap, home),
            "legacy_market": core.num(snap.get("market_home"), .5) if snap.get("market_home") is not None and snap.get("benchmark_version") != v11.BENCHMARK_VERSION else None,
            "sharp": sharp, "sharp_refs": len(comps),
        }
        rows.append(row)
        for book, p in {x["book"]: x["p"] for x in comps}.items():
            book_rows.setdefault(book, []).append({"y": row["y"], "p": p})
    rows.sort(key=lambda r: (str(r.get("date")), str(r.get("game_pk"))))
    return rows, book_rows


def select_blend_weight(train):
    candidates = []
    for w in WEIGHT_GRID:
        vals = [(core.clamp(w*r["model"] + (1-w)*r["sharp"], .001, .999)-r["y"])**2 for r in train]
        if vals:
            candidates.append((sum(vals)/len(vals), abs(w-.5), w))
    return min(candidates)[2] if candidates else None


def add_blend(rows, weight):
    out = []
    for r in rows:
        z = dict(r)
        z["blend"] = core.clamp(weight*r["model"] + (1-weight)*r["sharp"], .001, .999) if weight is not None else None
        out.append(z)
    return out


def metric_block(rows):
    return {
        "n": len(rows),
        "brier_model": _brier(rows, "model"), "brier_legacy_market": _brier(rows, "legacy_market"),
        "brier_sharp": _brier(rows, "sharp"), "brier_blend": _brier(rows, "blend"),
        "logloss_model": _logloss(rows, "model"), "logloss_legacy_market": _logloss(rows, "legacy_market"),
        "logloss_sharp": _logloss(rows, "sharp"), "logloss_blend": _logloss(rows, "blend"),
    }


def blend_gain_probability(rows):
    if not rows or any(r.get("blend") is None for r in rows):
        return None
    base_losses = [(core.num(r["model"], .5)-r["y"])**2 for r in rows]
    blend_losses = [(core.num(r["blend"], .5)-r["y"])**2 for r in rows]
    return core.bootstrap_gain_prob(base_losses, blend_losses, reps=1000)


def benchmark_main():
    hist = core.load_history()
    all_rows, books = collect(hist)
    usable = [r for r in all_rows if r.get("model") is not None and r.get("sharp") is not None]
    cut = int(len(usable) * .75); train = usable[:cut]; holdout = usable[cut:]
    weight = select_blend_weight(train) if len(train) >= 40 and len(holdout) >= 20 else None
    matched_blend = add_blend(usable, weight); holdout_blend = add_blend(holdout, weight)
    holdout_multi = sum(core.num(r.get("sharp_refs"), 0) >= 2 for r in holdout)
    report = {
        "version": v11.V11_VERSION, "benchmark_version": v11.BENCHMARK_VERSION,
        "method": "point-in-time persisted snapshots; independent effective model; matched comparisons; chronological holdout; bootstrap paired-loss evidence; no reconstructed historical odds",
        "sharp_books": list(v11.sharp_books()),
        "coverage": {
            "final_games_with_pregame_market_snapshot": len(all_rows), "matched_model_and_sharp": len(usable),
            "matched_pct": (len(usable)/len(all_rows)) if all_rows else None,
            "one_sharp_ref": sum(r.get("sharp_refs") == 1 for r in usable),
            "two_or_more_sharp_refs": sum(core.num(r.get("sharp_refs"),0)>=2 for r in usable),
            "holdout_two_or_more_sharp_refs": holdout_multi,
            "holdout_multiref_pct": (holdout_multi/len(holdout)) if holdout else None,
        },
        "matched_all": metric_block(matched_blend), "holdout": metric_block(holdout_blend),
        "holdout_blend_gain_probability": blend_gain_probability(holdout_blend),
        "blend_model_weight_selected_on_train": weight, "train_n": len(train), "holdout_n": len(holdout), "books": {},
    }
    for book, xs in books.items():
        if not xs: continue
        br = sum((core.num(x["p"],.5)-x["y"])**2 for x in xs)/len(xs)
        ll = sum(-(x["y"]*math.log(core.clamp(core.num(x["p"],.5),.001,.999))+(1-x["y"])*math.log(1-core.clamp(core.num(x["p"],.5),.001,.999))) for x in xs)/len(xs)
        report["books"][book] = {"n": len(xs), "brier": br, "logloss": ll}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


# ---------------- V11.1 BASEBALL SHADOW ----------------

def _http(url):
    if url in _HTTP_CACHE:
        return _HTTP_CACHE[url]
    req = urllib.request.Request(url, headers={"User-Agent":"MLB-BETTING-BOT-V11.1-shadow", "Accept":"application/json"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                _HTTP_CACHE[url] = json.loads(resp.read().decode("utf-8")); return _HTTP_CACHE[url]
        except Exception:
            if attempt == 0: time.sleep(.3)
    _HTTP_CACHE[url] = None
    return None


def _mlb(path, **params):
    q = urllib.parse.urlencode({k:v for k,v in params.items() if v is not None})
    return _http(MLB_API + path + (("?"+q) if q else "")) or {}


def _schedule(start, end=None):
    d = _mlb("/v1/schedule", sportId=1, startDate=str(start), endDate=str(end or start), hydrate="probablePitcher,venue,team")
    return [g for block in d.get("dates") or [] for g in block.get("games") or []]


def _feed(pk): return _mlb(f"/v1.1/game/{int(pk)}/feed/live")

def _venue(vid):
    xs = _mlb(f"/v1/venues/{int(vid)}").get("venues") or []
    return xs[0] if xs else {}


def _pitcher_stats(pid, kind):
    xs = _mlb(f"/v1/people/{int(pid)}/stats", stats=kind, group="pitching", season=core.NOW.year).get("stats") or []
    return xs[0].get("splits") or [] if xs else []


def _innings(x):
    s = str(x or "0")
    if "." not in s: return core.num(s,0)
    w,f = s.split(".",1); o = int(f[:1] or 0)
    return core.num(w,0)+o/3 if o in (0,1,2) else core.num(s,0)


def _entry(box,pid): return (box.get("players") or {}).get(f"ID{int(pid)}", {})

def _person(g,pid): return (g.get("gameData",{}).get("players") or {}).get(f"ID{int(pid)}", {})

def _pstat(e, season=True): return ((e.get("seasonStats") if season else e.get("stats")) or {}).get("pitching") or {}

def _bstat(e): return (e.get("seasonStats") or {}).get("batting") or {}

def _team_id(game,side): return int((((game.get("teams") or {}).get(side) or {}).get("team") or {}).get("id") or 0)

def _team_name(game,side): return str(((((game.get("teams") or {}).get(side) or {}).get("team") or {}).get("name")) or "")


def _probable(game,g,side):
    x=(g.get("gameData",{}).get("probablePitchers") or {}).get(side) or {}
    if x.get("id"): return int(x["id"])
    x=((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {}
    return int(x["id"]) if x.get("id") else None


def _fip(st):
    ip=_innings(st.get("inningsPitched"))
    if ip<1:return None
    return (13*core.num(st.get("homeRuns"))+3*(core.num(st.get("baseOnBalls"))+core.num(st.get("hitBatsmen",st.get("hitByPitch"))))-2*core.num(st.get("strikeOuts")))/ip+3.20


def _quality(st):
    m=_fip(st)
    if m is None:m=core.num(st.get("era",st.get("earnedRunAverage")),4.25)
    return core.clamp((4.25-m)/1.5,-1,1)


def _availability(days):
    d1,d2,d3=(core.num(days.get(i),0) for i in (1,2,3))
    load=.018*min(d1,40)+.007*min(d2,40)+.003*min(d3,40)
    if d1>0 and d2>0: load+=.18
    if d1>=30: load+=.35
    elif d1>=20: load+=.18
    if d1+d2>=55: load+=.15
    return core.clamp(1-load,.05,1)


def _recent_usage(team_ids,target):
    out=defaultdict(lambda:defaultdict(lambda:defaultdict(float)))
    for game in _schedule((target-timedelta(days=3)).isoformat(),(target-timedelta(days=1)).isoformat()):
        if str(game.get("status",{}).get("abstractGameState") or "").lower()!="final": continue
        try: days=(target-date.fromisoformat(str(game.get("officialDate")))).days
        except Exception: continue
        sides=[(s,_team_id(game,s)) for s in ("home","away") if _team_id(game,s) in team_ids]
        if not sides: continue
        g=_feed(game.get("gamePk")); boxes=g.get("liveData",{}).get("boxscore",{}).get("teams") or {}
        for side,tid in sides:
            box=boxes.get(side) or {}
            for pid in box.get("pitchers") or []:
                pitches=core.num(_pstat(_entry(box,pid),False).get("pitchesThrown"),0)
                if pitches>0: out[tid][int(pid)][days]+=pitches
    return out


def _bullpen(box,g,starter,usage):
    rows=[]
    for e in (box.get("players") or {}).values():
        pid=(e.get("person") or {}).get("id")
        if not pid or int(pid)==int(starter or -1): continue
        gp=_person(g,pid); pos=(e.get("position") or {}).get("abbreviation") or (gp.get("primaryPosition") or {}).get("abbreviation")
        if str(pos).upper()!="P": continue
        st=_pstat(e,True)
        if _innings(st.get("inningsPitched"))<=0: continue
        q=_quality(st); ds=usage.get(int(pid),{}); av=_availability(ds)
        lev=1+min(core.num(st.get("saves"),0),25)/25+min(core.num(st.get("holds"),0),30)/60+.3*max(q,0)
        loss=(1-av)*(1+.5*max(q,0)); rows.append((pid,q,av,lev,loss,ds,(e.get("person") or {}).get("fullName") or gp.get("fullName")))
    if not rows:return {"available":False,"score":0.0,"fatigue":None,"relievers":[]}
    den=sum(x[3] for x in rows); avg=sum(x[4]*x[3] for x in rows)/den; fat=sum((1-x[2])*x[3] for x in rows)/den
    detail=[]
    for pid,q,av,lev,loss,ds,name in sorted(rows,key=lambda x:(x[2],-x[1]))[:8]:
        detail.append({"id":int(pid),"name":name,"quality":round(q,3),"availability":round(av,3),"d1":core.num(ds.get(1),0),"d2":core.num(ds.get(2),0),"d3":core.num(ds.get(3),0)})
    return {"available":len(rows)>=4,"score":round(-core.clamp(avg/.65,0,1.25),4),"fatigue":round(fat,4),"high_leverage_unavailable":sum(q>.2 and av<.4 for _,q,av,*_ in rows),"reliever_count":len(rows),"relievers":detail}


def _aggregate_pitch(stats):
    t=defaultdict(float); outs=0
    for st in stats:
        outs+=round(_innings(st.get("inningsPitched"))*3)
        for k in ("earnedRuns","homeRuns","baseOnBalls","hitBatsmen","strikeOuts"): t[k]+=core.num(st.get(k),0)
    t["inningsPitched"]=outs/3; return dict(t)


def _starter_recent(pid, season):
    if not pid:return {"available":False,"score":0.0,"starts":0}
    recent=[]
    for x in sorted(_pitcher_stats(pid,"gameLog"),key=lambda z:str(z.get("date") or ""),reverse=True):
        st=x.get("stat") or {}
        if _innings(st.get("inningsPitched"))>0: recent.append(st)
        if len(recent)>=5: break
    if not season:
        xs=_pitcher_stats(pid,"season"); season=(xs[0].get("stat") or {}) if xs else {}
    if len(recent)<2 or not season:return {"available":False,"score":0.0,"starts":len(recent)}
    agg=_aggregate_pitch(recent); rip=core.num(agg.get("inningsPitched"),0); rm=_fip(agg) or 9*core.num(agg.get("earnedRuns"),0)/max(rip,1); sm=_fip(season) or core.num(season.get("era",season.get("earnedRunAverage")),4.25)
    w=rip/(rip+20); shr=w*rm+(1-w)*sm; form=core.clamp((sm-shr)/1.25,-1.25,1.25)
    ravg=rip/len(recent); sip=_innings(season.get("inningsPitched")); savg=sip/max(1,core.num(season.get("gamesStarted"),len(recent))) if sip else 5.2
    score=core.clamp(.8*form+.2*core.clamp((ravg-savg)/1.5,-.75,.75),-1.25,1.25)
    return {"available":True,"score":round(score,4),"starts":len(recent),"recent_metric":round(rm,3),"season_metric":round(sm,3),"shrunk_metric":round(shr,3),"recent_weight":round(w,3)}


def _ops(st):
    ops=core.num(st.get("ops"),.720); pa=core.num(st.get("plateAppearances"),0)
    if not .2<=ops<=1.5: ops=core.num(st.get("onBasePercentage"),.320)+core.num(st.get("sluggingPercentage"),.400)
    w=pa/(pa+80); return .720+w*(ops-.720),pa


def _order(box):
    ids=[int(x) for x in box.get("battingOrder") or [] if str(x).isdigit()]
    if len(ids)>=4:return ids[:9]
    xs=[]
    for e in (box.get("players") or {}).values():
        o=int(core.num(e.get("battingOrder"),0)); pid=(e.get("person") or {}).get("id")
        if o>0 and pid: xs.append((o,int(pid)))
    return [p for _,p in sorted(xs)[:9]]


def _lineup(box,g):
    ids=_order(box); status="OFFICIAL_FEED" if len(ids)>=9 else ("PARTIAL" if len(ids)>=4 else "PROJECTED"); conf=1.0 if status=="OFFICIAL_FEED" else (.55 if status=="PARTIAL" else 0)
    roster=[]
    for e in (box.get("players") or {}).values():
        pid=(e.get("person") or {}).get("id"); gp=_person(g,pid) if pid else {}; pos=(e.get("position") or {}).get("abbreviation") or (gp.get("primaryPosition") or {}).get("abbreviation")
        if str(pos).upper()=="P":continue
        op,pa=_ops(_bstat(e))
        if pa>0: roster.append((pa,op,int(pid),(e.get("person") or {}).get("fullName") or gp.get("fullName")))
    regular=sorted(roster,reverse=True)[:9]; base=sum(x[1] for x in regular)/len(regular) if regular else .720
    hitters=[]; n=d=0.0
    for i,pid in enumerate(ids[:9]):
        e=_entry(box,pid); op,pa=_ops(_bstat(e)); wt=ORDER_W[i]; n+=wt*op; d+=wt; hitters.append({"id":pid,"order":i+1,"ops":round(op,4),"name":(e.get("person") or {}).get("fullName") or _person(g,pid).get("fullName")})
    lop=n/d if d else None; score=core.clamp(((lop-base)/.08) if lop is not None else 0,-1.25,1.25)*conf
    missing=sorted([x for x in regular if x[2] not in set(ids)],key=lambda x:(x[1],x[0]),reverse=True)[:4]
    return {"available":status!="PROJECTED","status":status,"confidence":conf,"score":round(score,4),"lineup_ops":round(lop,4) if lop is not None else None,"regular_ops":round(base,4),"hitters":hitters,"missing":[{"name":x[3],"ops":round(x[1],4)} for x in missing]}


def _matchup(lu,g,starter):
    if not starter or not lu.get("hitters"):return {"available":False,"score":0.0,"starter_hand":None}
    hand=str((_person(g,starter).get("pitchHand") or {}).get("code") or "").upper()
    if hand not in ("L","R"):return {"available":False,"score":0.0,"starter_hand":hand or None}
    vals=[];adv=0
    for h in lu["hitters"]:
        bat=str((_person(g,h["id"]).get("batSide") or {}).get("code") or "").upper()
        if bat=="S":pl=1;adv+=1
        elif bat in ("L","R") and bat!=hand:pl=.65;adv+=1
        elif bat in ("L","R"):pl=-.35
        else:pl=0
        q=core.clamp((core.num(h.get("ops"),.720)-.720)/.15,-.8,1.2); wt=ORDER_W[h["order"]-1]; vals.append((pl*(.75+.25*max(q,-.5)),wt))
    s=(sum(v*w for v,w in vals)/sum(w for _,w in vals))*core.num(lu.get("confidence"),0) if vals else 0
    return {"available":bool(vals) and lu.get("available"),"score":round(core.clamp(s,-1,1),4),"starter_hand":hand,"advantage_hitters":adv}


def _wind_component(speed, wind_from, azimuth):
    if wind_from is None or azimuth is None:return None
    wind_to=(core.num(wind_from,0)+180)%360; diff=math.radians((wind_to-core.num(azimuth,0)+180)%360-180)
    return core.num(speed,0)*math.cos(diff)


def _weather(v,gdt,g):
    field=v.get("fieldInfo") or {}; loc=v.get("location") or {}; coords=loc.get("defaultCoordinates") or {}; roof=str(field.get("roofType") or "").lower(); cond=str(g.get("gameData",{}).get("weather",{}).get("condition") or "").lower()
    indoor=any(x in roof for x in ("dome","fixed")) or any(x in cond for x in ("dome","indoor","roof closed"))
    if indoor:return {"available":True,"directional":True,"indoor":True,"run_delta":0.0}
    lat,lon=coords.get("latitude"),coords.get("longitude"); az=loc.get("azimuthAngle",field.get("azimuthAngle"))
    if lat is None or lon is None:return {"available":False,"directional":False,"run_delta":0.0}
    q=urllib.parse.urlencode({"latitude":lat,"longitude":lon,"hourly":"temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m","timezone":"UTC","wind_speed_unit":"mph","temperature_unit":"fahrenheit","forecast_days":2}); h=(_http(METEO_API+"?"+q) or {}).get("hourly") or {}; times=h.get("time") or []
    if not times:return {"available":False,"directional":False,"run_delta":0.0}
    best=None
    for i,t in enumerate(times):
        try: dt=core.parse_dt(t+"+00:00"); dist=abs((dt-gdt.astimezone(timezone.utc)).total_seconds())
        except Exception:continue
        if best is None or dist<best[0]:best=(dist,i)
    if best is None:return {"available":False,"directional":False,"run_delta":0.0}
    i=best[1]
    def at(k,d=None): a=h.get(k) or []; return a[i] if i<len(a) else d
    temp=core.num(at("temperature_2m"),70); hum=core.num(at("relative_humidity_2m"),50); speed=core.num(at("wind_speed_10m"),0); wf=at("wind_direction_10m"); comp=_wind_component(speed,wf,az)
    if comp is None: delta=0; directional=False; label="UNKNOWN"
    else:
        mult=1+core.clamp((temp-70)/50,-.2,.3)+core.clamp((hum-50)/300,-.1,.1); delta=core.clamp(.025*comp*mult,-.55,.55); directional=True; label="OUT" if comp>2.5 else ("IN" if comp<-2.5 else "CROSS")
    return {"available":True,"directional":directional,"indoor":False,"run_delta":round(delta,4),"temp_f":round(temp,1),"humidity":round(hum,1),"wind_mph":round(speed,1),"wind_from":round(core.num(wf,0),1) if wf is not None else None,"azimuth":round(core.num(az,0),1) if az is not None else None,"out_component":round(comp,2) if comp is not None else None,"direction":label}


def _base_runs(snap):
    hs=("lambda_home","mu_home","pred_home_runs","home_runs_model","runs_home","home_run_mean"); aws=("lambda_away","mu_away","pred_away_runs","away_runs_model","runs_away","away_run_mean")
    for c in [snap]+[snap[k] for k in ("run_model","runs","run_projection","score_projection") if isinstance(snap.get(k),dict)]:
        h=next((core.num(c[k],-1) for k in hs if c.get(k) is not None),None); a=next((core.num(c[k],-1) for k in aws if c.get(k) is not None),None)
        if h is not None and a is not None and .5<=h<=12 and .5<=a<=12:return h,a
    return None,None


def _adjust_p(p,delta):
    p=core.clamp(core.num(p,.5),.001,.999); z=math.log(p/(1-p))+core.clamp(delta,-.6,.6)
    return core.clamp(1/(1+math.exp(-z)),.001,.999)


def _analyze_shadow_game(game,hist,usage):
    pk=int(game.get("gamePk")); home=_team_name(game,"home"); away=_team_name(game,"away"); rec=hist.get(str(pk),hist.get(pk,{})); snap=_latest_snapshot(rec) if rec else None
    base=_snapshot_model_home(snap,home) if snap else None; bh,ba=_base_runs(snap or {}); g=_feed(pk); boxes=g.get("liveData",{}).get("boxscore",{}).get("teams") or {}; hb=boxes.get("home") or {}; ab=boxes.get("away") or {}; hsp=_probable(game,g,"home"); asp=_probable(game,g,"away")
    hbp=_bullpen(hb,g,hsp,usage.get(_team_id(game,"home"),{})); abp=_bullpen(ab,g,asp,usage.get(_team_id(game,"away"),{})); hsr=_starter_recent(hsp,_pstat(_entry(hb,hsp),True) if hsp else {}); asr=_starter_recent(asp,_pstat(_entry(ab,asp),True) if asp else {}); hlu=_lineup(hb,g); alu=_lineup(ab,g); hmu=_matchup(hlu,g,asp); amu=_matchup(alu,g,hsp)
    try:gdt=core.parse_dt(game.get("gameDate"))
    except Exception:gdt=core.NOW
    vid=(game.get("venue") or {}).get("id"); wea=_weather(_venue(vid),gdt,g) if vid else {"available":False,"directional":False,"run_delta":0.0}
    db=W_BP*(core.num(hbp.get("score"),0)-core.num(abp.get("score"),0)); ds=W_SP*(core.num(hsr.get("score"),0)-core.num(asr.get("score"),0)); dl=W_LU*(core.num(hlu.get("score"),0)-core.num(alu.get("score"),0)); dm=W_MU*(core.num(hmu.get("score"),0)-core.num(amu.get("score"),0)); full=core.clamp(db+ds+dl+dm,-.45,.45)
    wh=core.num(wea.get("run_delta"),0)/2; hd=core.clamp(wh+.18*core.num(hlu.get("score"),0)+.12*core.num(hmu.get("score"),0)-.18*core.num(asr.get("score"),0)-.16*core.num(abp.get("score"),0),-.75,.75); ad=core.clamp(wh+.18*core.num(alu.get("score"),0)+.12*core.num(amu.get("score"),0)-.18*core.num(hsr.get("score"),0)-.16*core.num(hbp.get("score"),0),-.75,.75)
    cov={"bullpen_both":bool(hbp.get("available") and abp.get("available")),"starter_both":bool(hsr.get("available") and asr.get("available")),"lineup_both":bool(hlu.get("available") and alu.get("available")),"matchup_both":bool(hmu.get("available") and amu.get("available")),"weather_directional":bool(wea.get("directional"))}; cov["full"]=all(cov.values())
    row={"shadow_version":SHADOW_VERSION,"analyzed_at":datetime.now(timezone.utc).isoformat(),"run_id":os.getenv("GITHUB_RUN_ID"),"game_pk":pk,"game_date":game.get("officialDate"),"game_time":game.get("gameDate"),"home":home,"away":away,"phase":(snap or {}).get("phase"),"seconds_to_game":(snap or {}).get("seconds_to_game"),"base_p_home":round(base,6) if base is not None else None,"base_home_runs":bh,"base_away_runs":ba,"shadow_home_run_delta":round(hd,4),"shadow_away_run_delta":round(ad,4),"shadow_home_runs":round(core.clamp(bh+hd,.5,12),4) if bh is not None else None,"shadow_away_runs":round(core.clamp(ba+ad,.5,12),4) if ba is not None else None,"adjustments":{"bullpen":round(db,6),"starter_recent":round(ds,6),"lineup":round(dl,6),"matchup":round(dm,6),"full":round(full,6)},"features":{"home_bullpen":hbp,"away_bullpen":abp,"home_starter_recent":hsr,"away_starter_recent":asr,"home_lineup":hlu,"away_lineup":alu,"home_matchup":hmu,"away_matchup":amu,"weather":wea},"coverage":cov,"official_effect":False}
    if base is not None:
        row.update({"shadow_p_bullpen":round(_adjust_p(base,db),6),"shadow_p_starter":round(_adjust_p(base,ds),6),"shadow_p_lineup":round(_adjust_p(base,dl),6),"shadow_p_matchup":round(_adjust_p(base,dm),6),"shadow_p_full":round(_adjust_p(base,full),6)})
    return row


def _read_shadow():
    if not SHADOW_OUT.exists():return []
    rows=[]
    for line in SHADOW_OUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:rows.append(json.loads(line))
            except Exception:pass
    return rows


def _actual_scores(rec):
    for hk,ak in (("home_score","away_score"),("score_home","score_away")):
        if rec.get(hk) is not None and rec.get(ak) is not None:return core.num(rec.get(hk)),core.num(rec.get(ak))
    return None,None


def _shadow_final_rows(rows,hist):
    best={}
    for r in rows:
        if r.get("shadow_version")!=SHADOW_VERSION:continue
        rec=hist.get(str(r.get("game_pk")),hist.get(r.get("game_pk"),{})); y=rec.get("home_win")
        if rec.get("status")!="FINAL" or y not in (0,1) or core.num(r.get("seconds_to_game"),-1)<0:continue
        rank=(-core.num(r.get("seconds_to_game"),1e12),str(r.get("analyzed_at") or "")); old=best.get(str(r.get("game_pk")))
        if old is None or rank>old[0]:
            z=dict(r);z["y"]=int(y);z["actual_home_runs"],z["actual_away_runs"]=_actual_scores(rec);best[str(r.get("game_pk"))]=(rank,z)
    return sorted([x[1] for x in best.values()],key=lambda r:(str(r.get("game_date")),str(r.get("game_pk"))))


def _shadow_metrics(rows):
    out={"n":len(rows)}
    fields=("base_p_home","shadow_p_bullpen","shadow_p_starter","shadow_p_lineup","shadow_p_matchup","shadow_p_full")
    for f in fields:out["brier_"+f]=_brier(rows,f);out["logloss_"+f]=_logloss(rows,f)
    use=[r for r in rows if r.get("base_p_home") is not None and r.get("shadow_p_full") is not None]
    if use:
        bl=[(core.num(r["base_p_home"],.5)-r["y"])**2 for r in use];nl=[(core.num(r["shadow_p_full"],.5)-r["y"])**2 for r in use];out["brier_gain_full"]=sum(bl)/len(bl)-sum(nl)/len(nl);out["paired_gain_probability"]=core.bootstrap_gain_prob(bl,nl,reps=1000)
    else:out["brier_gain_full"]=None;out["paired_gain_probability"]=None
    rr=[r for r in rows if None not in (r.get("actual_home_runs"),r.get("actual_away_runs"),r.get("base_home_runs"),r.get("base_away_runs"),r.get("shadow_home_runs"),r.get("shadow_away_runs"))]
    if rr:
        b=[];s=[]
        for r in rr:b += [abs(core.num(r["base_home_runs"])-core.num(r["actual_home_runs"])),abs(core.num(r["base_away_runs"])-core.num(r["actual_away_runs"]))];s += [abs(core.num(r["shadow_home_runs"])-core.num(r["actual_home_runs"])),abs(core.num(r["shadow_away_runs"])-core.num(r["actual_away_runs"]))]
        out.update({"run_n_games":len(rr),"run_mae_base_per_team":sum(b)/len(b),"run_mae_shadow_per_team":sum(s)/len(s),"run_mae_gain":sum(b)/len(b)-sum(s)/len(s)})
    else:out.update({"run_n_games":0,"run_mae_base_per_team":None,"run_mae_shadow_per_team":None,"run_mae_gain":None})
    return out


def baseball_shadow_main():
    hist=core.load_history(); raw=os.getenv("MLB_DATE","").strip()
    try:target=date.fromisoformat(raw) if raw else core.NOW.date()
    except Exception:target=core.NOW.date()
    games=_schedule(target.isoformat()); preview=[g for g in games if str(g.get("status",{}).get("abstractGameState") or "").lower()=="preview"]; tids={_team_id(g,s) for g in preview for s in ("home","away") if _team_id(g,s)}
    try:usage=_recent_usage(tids,target)
    except Exception:usage={}
    current=[]
    for game in preview:
        try:current.append(_analyze_shadow_game(game,hist,usage))
        except Exception as exc:print(f"[V11.1 SHADOW] game {game.get('gamePk')} skipped: {exc}",file=sys.stderr)
    if current:
        SHADOW_OUT.parent.mkdir(parents=True,exist_ok=True)
        with SHADOW_OUT.open("a",encoding="utf-8") as fh:
            for r in current:fh.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    finals=_shadow_final_rows(_read_shadow(),hist);cut=int(len(finals)*.75);hold=finals[cut:];allm=_shadow_metrics(finals);holdm=_shadow_metrics(hold);coverage={}
    for k in ("bullpen_both","starter_both","lineup_both","matchup_both","weather_directional","full"):
        xs=[bool((r.get("coverage") or {}).get(k)) for r in finals];coverage[k]=sum(xs)/len(xs) if xs else None
    hc=sum(bool((r.get("coverage") or {}).get("full")) for r in hold)/len(hold) if hold else None;gain=holdm.get("brier_gain_full")
    candidate=bool(len(finals)>=SHADOW_MIN_FINAL and len(hold)>=SHADOW_MIN_HOLDOUT and gain is not None and gain>=SHADOW_MIN_GAIN and core.num(holdm.get("paired_gain_probability"),0)>=SHADOW_MIN_GAIN_PROB and holdm.get("logloss_shadow_p_full") is not None and holdm.get("logloss_base_p_home") is not None and holdm["logloss_shadow_p_full"]<=holdm["logloss_base_p_home"] and core.num(hc,0)>=SHADOW_MIN_COVERAGE)
    report={"shadow_version":SHADOW_VERSION,"official_effect":False,"method":"point-in-time baseball feature shadow; closest pregame observation; fixed conservative weights; ablation metrics","weights":{"bullpen":W_BP,"starter_recent":W_SP,"lineup":W_LU,"matchup":W_MU},"samples":{"final_games":len(finals),"train_n":cut,"holdout_n":len(hold)},"coverage":coverage,"holdout_full_coverage":hc,"matched_all":allm,"holdout":holdm,"future_activation_gate":{"candidate_only":candidate,"auto_activation":False,"min_final":SHADOW_MIN_FINAL,"min_holdout":SHADOW_MIN_HOLDOUT,"min_brier_gain":SHADOW_MIN_GAIN,"min_gain_probability":SHADOW_MIN_GAIN_PROB,"min_full_coverage":SHADOW_MIN_COVERAGE},"current_run":{"date":target.isoformat(),"preview_games":len(preview),"rows_written":len(current),"base_probability_coverage":sum(r.get("base_p_home") is not None for r in current)/len(current) if current else None,"full_feature_coverage":sum(bool((r.get("coverage") or {}).get("full")) for r in current)/len(current) if current else None}}
    SHADOW_REPORT.parent.mkdir(parents=True,exist_ok=True);SHADOW_REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


def shadow_self_test():
    assert _availability({})==1.0 and _availability({1:32,2:12})<.25
    assert _wind_component(10,180,0)>9.9 and _wind_component(10,0,0)<-9.9
    assert abs(_innings("5.2")-(5+2/3))<1e-6
    assert _adjust_p(.5,.2)>.54
    print("SELF-TEST V11.1 BASEBALL SHADOW OK")


if __name__ == "__main__":
    if "--baseball-shadow" in sys.argv:
        baseball_shadow_main()
    elif "--shadow-self-test" in sys.argv:
        shadow_self_test()
    else:
        benchmark_main()
