#!/usr/bin/env python3
"""
V11.1.5 historical walk-forward backtest.

Purpose
-------
Re-evaluate the V11.1 baseball shadow features over the existing 2026 V10
replay without contaminating the live point-in-time journal.

No-lookahead contract
---------------------
* The V10 probability/run means come from data/mlb_backtest_2026.jsonl.
* V11.1 rolling baseball features are rebuilt from games on PRIOR Eastern
  calendar dates only.
* All games on the same Eastern date are predicted before any game from that
  date is ingested. This is conservative for doubleheaders and guarantees that
  a same-day final cannot leak into another pregame prediction.
* The PROJECTED lineup uses prior batting orders only.
* POSTED_RETRO may use the actual historical batting order for the current
  game, but never current-game batting stats. It is reported separately because
  the exact historical lineup publication timestamp is not archived.
* Historical sharp prices are NOT reconstructed and profitability is NOT
  claimed.
* Weather only changes run means, not ML probability. Archive weather is
  fetched in bulk by home park when an audited field azimuth is available.

This is research only. It never changes official picks or production weights.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import bot as core
import v11_baseball_shadow_v112 as weather_ref

VERSION = "11.1.5-walkforward-2026-v1"
DEFAULT_REPLAY = Path("data/mlb_backtest_2026.jsonl")
DEFAULT_OUT = Path("data/v11_walkforward_2026.jsonl")
DEFAULT_REPORT = Path("data/v11_walkforward_2026_report.json")
EASTERN = ZoneInfo("America/New_York")
ORDER_W = (1.08, 1.10, 1.10, 1.08, 1.03, .98, .94, .90, .88)
W_BP, W_SP, W_LU, W_MU = .16, .14, .12, .10
MIN_LINEUP_STATS_COVERAGE = .55
FIELD_AZIMUTH = dict(getattr(weather_ref, "FIELD_AZIMUTH", {}) or {})


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def num(x, default=0.0):
    return core.num(x, default)


def parse_dt(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def eastern_day(value):
    return parse_dt(value).astimezone(EASTERN).date()


def logit(p):
    p = clamp(num(p, .5), .001, .999)
    return math.log(p / (1 - p))


def adjust_p(p, delta):
    z = logit(p) + clamp(num(delta, 0), -.6, .6)
    return clamp(1 / (1 + math.exp(-z)), .001, .999)


def innings_outs(value):
    s = str(value or "0")
    if "." not in s:
        try:
            return int(round(float(s) * 3))
        except Exception:
            return 0
    whole, frac = s.split(".", 1)
    try:
        return max(0, int(whole) * 3 + int((frac or "0")[0]))
    except Exception:
        return 0


def outs_ip(outs):
    return max(0, int(outs)) / 3.0


PITCH_KEYS = ("earnedRuns", "homeRuns", "baseOnBalls", "hitBatsmen", "strikeOuts", "saves", "holds", "gamesStarted", "gamesPlayed")
HIT_KEYS = ("plateAppearances", "atBats", "hits", "doubles", "triples", "homeRuns", "baseOnBalls", "intentionalWalks", "hitByPitch", "sacFlies")


def empty_pitch():
    d = {k: 0.0 for k in PITCH_KEYS}; d["outs"] = 0; return d


def empty_hit():
    return {k: 0.0 for k in HIT_KEYS}


def add_pitch(dst, st, started=False):
    if not isinstance(st, dict): return
    dst["outs"] += innings_outs(st.get("inningsPitched"))
    for k in ("earnedRuns", "homeRuns", "baseOnBalls", "hitBatsmen", "strikeOuts", "saves", "holds"):
        dst[k] += num(st.get(k), 0)
    dst["gamesPlayed"] += 1
    if started: dst["gamesStarted"] += 1


def add_hit(dst, st):
    if not isinstance(st, dict): return
    for k in HIT_KEYS: dst[k] += num(st.get(k), 0)


def fip(agg):
    if not agg: return None
    ip = outs_ip(agg.get("outs", 0))
    if ip < 1: return None
    return (13*num(agg.get("homeRuns"),0)+3*(num(agg.get("baseOnBalls"),0)+num(agg.get("hitBatsmen"),0))-2*num(agg.get("strikeOuts"),0))/ip+3.20


def pitch_quality(agg):
    metric = fip(agg)
    if metric is None:
        ip = outs_ip((agg or {}).get("outs", 0)); metric = 9*num((agg or {}).get("earnedRuns"),0)/ip if ip >= 1 else 4.25
    return clamp((4.25-metric)/1.5, -1.0, 1.0)


def hitter_ops(agg):
    if not agg: return .720, 0.0
    pa, ab, h = num(agg.get("plateAppearances"),0), num(agg.get("atBats"),0), num(agg.get("hits"),0)
    doubles, triples, hr = num(agg.get("doubles"),0), num(agg.get("triples"),0), num(agg.get("homeRuns"),0)
    bb, hbp, sf = num(agg.get("baseOnBalls"),0), num(agg.get("hitByPitch"),0), num(agg.get("sacFlies"),0)
    if pa <= 0: pa = ab + bb + hbp + sf
    den = ab + bb + hbp + sf
    obp = (h + bb + hbp) / den if den > 0 else 0.0
    singles = max(0.0, h-doubles-triples-hr); tb = singles+2*doubles+3*triples+4*hr
    slg = tb/ab if ab > 0 else 0.0; raw = obp + slg
    if not .2 <= raw <= 1.5: raw = .720
    w = pa/(pa+80.0)
    return .720 + w*(raw-.720), pa


def availability(days):
    d1,d2,d3=(num(days.get(i),0) for i in (1,2,3)); load=.018*min(d1,40)+.007*min(d2,40)+.003*min(d3,40)
    if d1>0 and d2>0: load += .18
    if d1>=30: load += .35
    elif d1>=20: load += .18
    if d1+d2>=55: load += .15
    return clamp(1-load,.05,1.0)


class TeamState:
    def __init__(self):
        self.hitters=defaultdict(empty_hit); self.pitchers=defaultdict(empty_pitch); self.pitcher_history=defaultdict(list)
        self.lineups=deque(maxlen=7); self.reliever_usage=defaultdict(dict); self.names={}


class WalkState:
    def __init__(self): self.teams=defaultdict(TeamState); self.meta={}
    def bat_side(self,pid):
        pid=int(pid or 0)
        if not pid: return ""
        if pid in self.meta: return self.meta[pid]
        code=""
        try: code=str(((core.person_info(pid) or {}).get("batSide") or {}).get("code") or "").upper()
        except Exception: pass
        self.meta[pid]=code; return code


def current_order(team_box):
    ids=[]
    for x in team_box.get("battingOrder") or []:
        try: ids.append(int(x))
        except Exception: pass
    if len(ids)>=7: return ids[:9]
    ordered=[]
    for entry in (team_box.get("players") or {}).values():
        pid=(entry.get("person") or {}).get("id"); order=int(num(entry.get("battingOrder"),0))
        if pid and order>0: ordered.append((order,int(pid)))
    return [pid for _,pid in sorted(ordered)[:9]]


def team_entry(team_box,pid): return (team_box.get("players") or {}).get(f"ID{int(pid)}",{})


def projected_ids(ts):
    counts=Counter(); order_sum=defaultdict(float)
    for lineup in ts.lineups:
        for pos,pid in enumerate(lineup,1): counts[pid]+=1; order_sum[pid]+=pos
    return [pid for _,_,pid in sorted((-apps,order_sum[pid]/apps,int(pid)) for pid,apps in counts.items())[:9]]


def regular_ids(ts):
    rows=[]
    for pid,st in ts.hitters.items():
        _,pa=hitter_ops(st)
        if pa>0: rows.append((-pa,int(pid)))
    return [pid for _,pid in sorted(rows)[:9]]


def lineup_feature(state,team_name,ids,status,confidence):
    ts=state.teams[team_name]; ids=[int(x) for x in ids if int(x or 0)>0][:9]
    if not ids: return {"available":False,"status":status,"confidence":confidence,"score":0.0,"lineup_ops":None,"regular_ops":None,"stats_coverage":0.0,"real_ops_hitters":0,"hitters":[]}
    hitters=[]; real=0
    for pos,pid in enumerate(ids,1):
        ops,pa=hitter_ops(ts.hitters.get(pid)); real += pa>0
        hitters.append({"id":pid,"order":pos,"ops":round(ops,4),"pa":round(pa,1),"bat_side":state.bat_side(pid),"name":ts.names.get(pid,str(pid))})
    coverage=real/len(hitters); denom=sum(ORDER_W[h["order"]-1] for h in hitters)
    lineup_ops=sum(h["ops"]*ORDER_W[h["order"]-1] for h in hitters)/denom if denom else .720
    reg_vals=[hitter_ops(ts.hitters.get(pid))[0] for pid in regular_ids(ts)]; regular_ops=mean(reg_vals) if reg_vals else .720
    quality_ok=len(hitters)>=7 and coverage>=MIN_LINEUP_STATS_COVERAGE
    score=clamp((lineup_ops-regular_ops)/.08,-1.25,1.25)*confidence if quality_ok else 0.0
    return {"available":bool(quality_ok),"status":status,"confidence":confidence,"score":round(score,4),"lineup_ops":round(lineup_ops,4),"regular_ops":round(regular_ops,4),"stats_coverage":round(coverage,4),"real_ops_hitters":real,"hitters":hitters}


def matchup_feature(lineup,starter_hand):
    hand=str(starter_hand or "").upper()
    if hand not in ("L","R") or not lineup.get("available"):
        return {"available":False,"score":0.0,"starter_hand":hand or None,"advantage_hitters":0,"lineup_quality_gate":bool(lineup.get("available"))}
    vals=[]; advantage=0
    for hitter in lineup.get("hitters") or []:
        bat=str(hitter.get("bat_side") or "").upper()
        if bat=="S": platoon=1.0; advantage+=1
        elif bat in ("L","R") and bat!=hand: platoon=.65; advantage+=1
        elif bat in ("L","R"): platoon=-.35
        else: platoon=0.0
        quality=clamp((num(hitter.get("ops"),.720)-.720)/.15,-.8,1.2); wt=ORDER_W[int(hitter.get("order") or 1)-1]
        vals.append((platoon*(.75+.25*max(quality,-.5)),wt))
    score=(sum(v*w for v,w in vals)/sum(w for _,w in vals))*num(lineup.get("confidence"),0) if vals else 0
    return {"available":bool(vals),"score":round(score,4),"starter_hand":hand,"advantage_hitters":advantage,"lineup_quality_gate":True}


def bullpen_feature(state,team_name,current_day,starter_id):
    ts=state.teams[team_name]; rows=[]
    for pid,agg in ts.pitchers.items():
        if int(pid)==int(starter_id or -1): continue
        hist=ts.pitcher_history.get(pid) or []; relief=[x for x in hist if not x["started"]]
        if not relief or (current_day-max(x["day"] for x in relief)).days>14: continue
        starts=int(num(agg.get("gamesStarted"),0)); games=int(num(agg.get("gamesPlayed"),0)); apps=len(relief); ip=outs_ip(agg.get("outs",0)); saves=num(agg.get("saves"),0); holds=num(agg.get("holds"),0)
        if ip<3.0 and apps<=1: continue
        if starts>=4 and saves+holds<=0 and starts/max(games,1)>=.30: continue
        usage={age:num(ts.reliever_usage.get(pid,{}).get(current_day-timedelta(days=age)),0) for age in (1,2,3)}
        av=availability(usage); q=pitch_quality(agg); lev=1+min(saves,25)/25+min(holds,30)/60+.3*max(q,0)+.04*min(apps,5); loss=(1-av)*(1+.5*max(q,0))
        rows.append((pid,q,av,lev,loss,usage))
    if not rows: return {"available":False,"score":0.0,"fatigue":None,"reliever_count":0}
    den=sum(x[3] for x in rows); avg=sum(x[4]*x[3] for x in rows)/den; fatigue=sum((1-x[2])*x[3] for x in rows)/den
    detail=[]
    for pid,q,av,lev,loss,usage in sorted(rows,key=lambda x:(x[2],-x[1]))[:6]:
        detail.append({"id":int(pid),"name":ts.names.get(pid,str(pid)),"quality":round(q,3),"availability":round(av,3),"d1":round(num(usage.get(1),0),1),"d2":round(num(usage.get(2),0),1),"d3":round(num(usage.get(3),0),1)})
    return {"available":len(rows)>=4,"score":round(-clamp(avg/.65,0,1.25),4),"fatigue":round(fatigue,4),"reliever_count":len(rows),"high_leverage_unavailable":sum(q>.2 and av<.4 for _,q,av,*_ in rows),"relievers":detail}


def aggregate_start_rows(rows):
    agg=empty_pitch()
    for x in rows:
        st=x["stats"]; agg["outs"]+=int(st.get("outs",0))
        for k in ("earnedRuns","homeRuns","baseOnBalls","hitBatsmen","strikeOuts"): agg[k]+=num(st.get(k),0)
    return agg


def starter_feature(state,team_name,pid):
    if not pid: return {"available":False,"score":0.0,"starts":0}
    ts=state.teams[team_name]; starts=[x for x in ts.pitcher_history.get(int(pid),[]) if x["started"]]; recent=starts[-5:]; season=ts.pitchers.get(int(pid))
    if len(recent)<2 or not season or outs_ip(season.get("outs",0))<1: return {"available":False,"score":0.0,"starts":len(recent)}
    agg=aggregate_start_rows(recent); rip=outs_ip(agg.get("outs",0)); recent_metric=fip(agg) or 9*num(agg.get("earnedRuns"),0)/max(rip,1)
    sip=outs_ip(season.get("outs",0)); season_metric=fip(season) or 9*num(season.get("earnedRuns"),0)/max(sip,1); w=rip/(rip+20); shrunk=w*recent_metric+(1-w)*season_metric
    form=clamp((season_metric-shrunk)/1.25,-1.25,1.25); recent_depth=rip/len(recent); season_depth=sip/max(1,num(season.get("gamesStarted"),len(recent))) if sip else 5.2
    score=clamp(.8*form+.2*clamp((recent_depth-season_depth)/1.5,-.75,.75),-1.25,1.25)
    return {"available":True,"score":round(score,4),"starts":len(recent),"recent_metric":round(recent_metric,3),"season_metric":round(season_metric,3),"shrunk_metric":round(shrunk,3),"recent_weight":round(w,3)}


def fetch_boxscore(pk):
    try: return core.mlb(f"v1/game/{int(pk)}/boxscore") or {}
    except Exception as exc: return {"_error":str(exc)}


def fetch_boxscores(rows,workers):
    out={}
    with ThreadPoolExecutor(max_workers=max(1,workers)) as pool:
        fs={pool.submit(fetch_boxscore,r["game_pk"]):r["game_pk"] for r in rows}
        for fut in as_completed(fs):
            pk=fs[fut]
            try: out[pk]=fut.result()
            except Exception as exc: out[pk]={"_error":str(exc)}
    return out


def ingest_team(state,team_name,team_box,day,starter_id):
    ts=state.teams[team_name]; order=current_order(team_box)
    if len(order)>=7: ts.lineups.append(order[:9])
    for entry in (team_box.get("players") or {}).values():
        pid=(entry.get("person") or {}).get("id")
        if not pid: continue
        pid=int(pid); name=str((entry.get("person") or {}).get("fullName") or "")
        if name: ts.names[pid]=name
        stats=entry.get("stats") or {}; hst=stats.get("batting") or stats.get("hitting") or {}
        if hst and (num(hst.get("plateAppearances"),0)>0 or num(hst.get("atBats"),0)>0 or num(hst.get("baseOnBalls"),0)>0): add_hit(ts.hitters[pid],hst)
    pitchers=[]
    for x in team_box.get("pitchers") or []:
        try: pitchers.append(int(x))
        except Exception: pass
    if not starter_id and pitchers: starter_id=pitchers[0]
    for pid in pitchers:
        pst=(team_entry(team_box,pid).get("stats") or {}).get("pitching") or {}
        if not pst: continue
        started=int(pid)==int(starter_id or -1); add_pitch(ts.pitchers[pid],pst,started=started); game_agg=empty_pitch(); add_pitch(game_agg,pst,started=started)
        ts.pitcher_history[pid].append({"day":day,"started":started,"pitches":num(pst.get("pitchesThrown"),0),"stats":game_agg})
        if not started: ts.reliever_usage[pid][day]=ts.reliever_usage[pid].get(day,0.0)+num(pst.get("pitchesThrown"),0)


def ingest_game(state,row,box):
    teams=box.get("teams") or {}; day=eastern_day(row["game_date"]); starters=row.get("starters") or {}
    ingest_team(state,row["home"],teams.get("home") or {},day,starters.get("home_id")); ingest_team(state,row["away"],teams.get("away") or {},day,starters.get("away_id"))


def replay_rows(path,start_date=None,end_date=None,max_games=0):
    rows=[]
    with Path(path).open("r",encoding="utf-8") as fh:
        for line in fh:
            try: r=json.loads(line)
            except Exception: continue
            if not r.get("game_pk") or not r.get("game_date") or not isinstance(r.get("v10"),dict): continue
            day=eastern_day(r["game_date"])
            if start_date and day<start_date: continue
            if end_date and day>end_date: continue
            rows.append(r)
    rows.sort(key=lambda r:(parse_dt(r["game_date"]),int(r["game_pk"])))
    return rows[:max_games] if max_games>0 else rows


def weather_bulk(home_teams,start_date,end_date):
    data={}
    for team in sorted(set(home_teams)):
        if team in getattr(core,"DOME",set()): data[team]={"indoor":True,"hourly":{}}; continue
        if team not in FIELD_AZIMUTH or team not in getattr(core,"COORD",{}): continue
        lat,lon=core.COORD[team]
        try:
            obj=core.http_json("https://archive-api.open-meteo.com/v1/archive",{"latitude":lat,"longitude":lon,"start_date":start_date.isoformat(),"end_date":end_date.isoformat(),"hourly":"temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m","timezone":"UTC"},timeout=45,retries=2) or {}
            hourly=obj.get("hourly") or {}; times=hourly.get("time") or []; table={}
            for i,t in enumerate(times):
                def at(key):
                    arr=hourly.get(key) or []
                    return num(arr[i],None) if i<len(arr) else None
                table[str(t)]={"temp_c":at("temperature_2m"),"humidity":at("relative_humidity_2m"),"wind_kmh":at("wind_speed_10m"),"wind_from":at("wind_direction_10m")}
            data[team]={"indoor":False,"hourly":table}
        except Exception as exc: data[team]={"error":str(exc),"hourly":{}}
    return data


def weather_feature(row,weather):
    home=row["home"]
    if home in getattr(core,"DOME",set()): return {"available":True,"directional":True,"indoor":True,"run_delta":0.0,"source":"dome"}
    az=FIELD_AZIMUTH.get(home); entry=weather.get(home) or {}
    if az is None or not entry.get("hourly"): return {"available":False,"directional":False,"run_delta":0.0,"source":"orientation-or-archive-unavailable"}
    dt=parse_dt(row["game_date"]); dt += timedelta(hours=1) if dt.minute>=30 else timedelta(0); key=dt.replace(minute=0,second=0,microsecond=0,tzinfo=None).isoformat(timespec="minutes")
    vals=entry["hourly"].get(key)
    if not vals: return {"available":False,"directional":False,"run_delta":0.0,"source":"archive-hour-unavailable"}
    speed_mph=num(vals.get("wind_kmh"),0)/1.609344; wind_from=num(vals.get("wind_from"),0)%360; wind_to=(wind_from+180)%360; diff=math.radians((wind_to-az+180)%360-180); component=speed_mph*math.cos(diff)
    roof_factor=.35 if home in getattr(core,"ROOF",set()) else 1.0; delta=clamp(.025*component,-.55,.55)*roof_factor
    return {"available":True,"directional":True,"indoor":False,"run_delta":round(delta,4),"wind_mph":round(speed_mph,2),"wind_from_deg":round(wind_from,1),"field_azimuth_deg":round(az,2),"out_component":round(component,2),"direction":"OUT" if component>2.5 else ("IN" if component<-2.5 else "CROSS"),"roof_factor":roof_factor,"source":"Open-Meteo-archive+audited-azimuth"}


def build_prediction(state,row,box,weather,include_posted):
    base=num((row.get("v10") or {}).get("p_home"),None)
    if base is None: return None
    starters=row.get("starters") or {}; home_sp,away_sp=starters.get("home_id"),starters.get("away_id"); day=eastern_day(row["game_date"])
    home_bp=bullpen_feature(state,row["home"],day,home_sp); away_bp=bullpen_feature(state,row["away"],day,away_sp); home_sr=starter_feature(state,row["home"],home_sp); away_sr=starter_feature(state,row["away"],away_sp)
    home_proj=lineup_feature(state,row["home"],projected_ids(state.teams[row["home"]]),"PROJECTED_HISTORY",.45); away_proj=lineup_feature(state,row["away"],projected_ids(state.teams[row["away"]]),"PROJECTED_HISTORY",.45)
    home_mu=matchup_feature(home_proj,starters.get("away_hand")); away_mu=matchup_feature(away_proj,starters.get("home_hand"))
    d_bp=W_BP*(num(home_bp.get("score"))-num(away_bp.get("score"))); d_sp=W_SP*(num(home_sr.get("score"))-num(away_sr.get("score"))); d_lu=W_LU*(num(home_proj.get("score"))-num(away_proj.get("score"))); d_mu=W_MU*(num(home_mu.get("score"))-num(away_mu.get("score"))); d_full=clamp(d_bp+d_sp+d_lu+d_mu,-.45,.45)
    w=weather_feature(row,weather) if weather is not None else {"available":False,"directional":False,"run_delta":0.0,"source":"disabled"}; wind_half=num(w.get("run_delta"),0)/2
    hrd=clamp(wind_half+.18*num(home_proj.get("score"))+.12*num(home_mu.get("score"))-.18*num(away_sr.get("score"))-.16*num(away_bp.get("score")),-.75,.75); ard=clamp(wind_half+.18*num(away_proj.get("score"))+.12*num(away_mu.get("score"))-.18*num(home_sr.get("score"))-.16*num(home_bp.get("score")),-.75,.75)
    base_hr=num((row.get("v10") or {}).get("home_mu"),None); base_ar=num((row.get("v10") or {}).get("away_mu"),None)
    out={"version":VERSION,"game_pk":int(row["game_pk"]),"game_date":row["game_date"],"eastern_day":day.isoformat(),"home":row["home"],"away":row["away"],"y":int(row.get("y")) if row.get("y") in (0,1) else (1 if num(row.get("home_score"))>num(row.get("away_score")) else 0),"home_score":row.get("home_score"),"away_score":row.get("away_score"),"base_p_home":round(base,6),"p_bullpen":round(adjust_p(base,d_bp),6),"p_starter":round(adjust_p(base,d_sp),6),"p_lineup_projected":round(adjust_p(base,d_lu),6),"p_matchup_projected":round(adjust_p(base,d_mu),6),"p_full_projected":round(adjust_p(base,d_full),6),"adjustments":{"bullpen":round(d_bp,6),"starter":round(d_sp,6),"lineup_projected":round(d_lu,6),"matchup_projected":round(d_mu,6),"full_projected":round(d_full,6)},"features":{"home_bullpen":home_bp,"away_bullpen":away_bp,"home_starter":home_sr,"away_starter":away_sr,"home_lineup_projected":home_proj,"away_lineup_projected":away_proj,"home_matchup_projected":home_mu,"away_matchup_projected":away_mu,"weather":w},"coverage":{"bullpen_both":bool(home_bp.get("available") and away_bp.get("available")),"starter_both":bool(home_sr.get("available") and away_sr.get("available")),"lineup_projected_both":bool(home_proj.get("available") and away_proj.get("available")),"matchup_projected_both":bool(home_mu.get("available") and away_mu.get("available")),"weather_directional":bool(w.get("directional"))},"base_home_runs":base_hr,"base_away_runs":base_ar,"shadow_home_runs_projected":round(clamp(base_hr+hrd,.5,12),4) if base_hr is not None else None,"shadow_away_runs_projected":round(clamp(base_ar+ard,.5,12),4) if base_ar is not None else None,"official_effect":False,"no_lookahead":True}
    out["coverage"]["full_projected"]=all(out["coverage"][k] for k in ("bullpen_both","starter_both","lineup_projected_both","matchup_projected_both"))
    if include_posted:
        teams=box.get("teams") or {}; hp=lineup_feature(state,row["home"],current_order(teams.get("home") or {}),"POSTED_RETRO",.95); ap=lineup_feature(state,row["away"],current_order(teams.get("away") or {}),"POSTED_RETRO",.95); hm=matchup_feature(hp,starters.get("away_hand")); am=matchup_feature(ap,starters.get("home_hand")); dplu=W_LU*(num(hp.get("score"))-num(ap.get("score"))); dpmu=W_MU*(num(hm.get("score"))-num(am.get("score"))); dpfull=clamp(d_bp+d_sp+dplu+dpmu,-.45,.45)
        out.update({"p_lineup_posted_retro":round(adjust_p(base,dplu),6),"p_matchup_posted_retro":round(adjust_p(base,dpmu),6),"p_full_posted_retro":round(adjust_p(base,dpfull),6),"posted_retro_caveat":"actual historical batting order; exact publication timestamp not archived; never treated as EARLY"}); out["coverage"].update({"lineup_posted_retro_both":bool(hp.get("available") and ap.get("available")),"matchup_posted_retro_both":bool(hm.get("available") and am.get("available"))}); out["coverage"]["full_posted_retro"]=all((out["coverage"]["bullpen_both"],out["coverage"]["starter_both"],out["coverage"]["lineup_posted_retro_both"],out["coverage"]["matchup_posted_retro_both"])); out["features"].update({"home_lineup_posted_retro":hp,"away_lineup_posted_retro":ap,"home_matchup_posted_retro":hm,"away_matchup_posted_retro":am})
    return out


PROB_FIELDS=("base_p_home","p_bullpen","p_starter","p_lineup_projected","p_matchup_projected","p_full_projected","p_lineup_posted_retro","p_matchup_posted_retro","p_full_posted_retro")


def score_rows(rows,field):
    xs=[(num(r.get(field),None),r.get("y")) for r in rows]; xs=[(p,y) for p,y in xs if p is not None and y in (0,1)]
    if not xs: return {"n":0,"accuracy":None,"brier":None,"logloss":None}
    return {"n":len(xs),"accuracy":mean((p>=.5)==bool(y) for p,y in xs),"brier":mean((p-y)**2 for p,y in xs),"logloss":mean(-(y*math.log(clamp(p,.001,.999))+(1-y)*math.log(clamp(1-p,.001,.999))) for p,y in xs)}


def coverage(rows):
    keys=sorted({k for r in rows for k in (r.get("coverage") or {}).keys()}); return {k:mean(1.0 if (r.get("coverage") or {}).get(k) else 0.0 for r in rows) if rows else None for k in keys}


def paired_gain(rows,candidate):
    usable=[r for r in rows if r.get("base_p_home") is not None and r.get(candidate) is not None and r.get("y") in (0,1)]
    if not usable: return {"paired_n":0,"brier_gain":None,"paired_gain_probability":None}
    bl=[(num(r["base_p_home"])-r["y"])**2 for r in usable]; nl=[(num(r[candidate])-r["y"])**2 for r in usable]; gain=mean(bl)-mean(nl)
    try: prob=core.bootstrap_gain_prob(bl,nl,reps=1000)
    except Exception:
        random.seed(115); n=len(bl); prob=sum(mean(bl[i]-nl[i] for i in [random.randrange(n) for _ in range(n)])>0 for _ in range(1000))/1000
    return {"paired_n":len(usable),"brier_gain":gain,"paired_gain_probability":prob}


def run_mae(rows,hf,af):
    vals=[]
    for r in rows:
        hp,ap,hs,as_=num(r.get(hf),None),num(r.get(af),None),num(r.get("home_score"),None),num(r.get("away_score"),None)
        if None not in (hp,ap,hs,as_): vals.extend([abs(hp-hs),abs(ap-as_)])
    return mean(vals) if vals else None


def metrics_bundle(rows):
    out={"n":len(rows),"coverage":coverage(rows),"models":{}}
    for field in PROB_FIELDS:
        if any(r.get(field) is not None for r in rows): out["models"][field]=score_rows(rows,field); out["models"][field].update({} if field=="base_p_home" else paired_gain(rows,field))
    b=run_mae(rows,"base_home_runs","base_away_runs"); s=run_mae(rows,"shadow_home_runs_projected","shadow_away_runs_projected"); out["runs"]={"base_mae_per_team":b,"shadow_projected_mae_per_team":s,"mae_gain":b-s if b is not None and s is not None else None}; return out


def write_jsonl(path,rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    tmp.replace(path)


def self_test():
    assert innings_outs("5.2")==17
    p,pa=hitter_ops({"plateAppearances":400,"atBats":330,"hits":110,"doubles":25,"triples":2,"homeRuns":30,"baseOnBalls":60,"hitByPitch":5,"sacFlies":5}); assert pa==400 and p>.80
    assert adjust_p(.5,.2)>.5 and availability({1:30,2:20,3:0})<.25
    st=WalkState(); ts=st.teams["A"]
    for pid in range(1,10):
        ts.hitters[pid].update({"plateAppearances":100,"atBats":80,"hits":25,"doubles":5,"homeRuns":3,"baseOnBalls":15}); ts.lineups.append(list(range(1,10))); st.meta[pid]="L" if pid%2 else "R"
    lu=lineup_feature(st,"A",projected_ids(ts),"PROJECTED_HISTORY",.45); assert lu["available"] and lu["stats_coverage"]==1.0; assert matchup_feature(lu,"R")["available"]; rejected=dict(lu); rejected["available"]=False; assert matchup_feature(rejected,"R")["score"]==0.0
    print("SELF-TEST V11.1.5 WALK-FORWARD OK")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--replay",default=str(DEFAULT_REPLAY)); ap.add_argument("--output",default=str(DEFAULT_OUT)); ap.add_argument("--report",default=str(DEFAULT_REPORT)); ap.add_argument("--start-date",default="2026-03-25"); ap.add_argument("--end-date",default="2026-08-13"); ap.add_argument("--max-games",type=int,default=0); ap.add_argument("--workers",type=int,default=6); ap.add_argument("--include-posted",action="store_true"); ap.add_argument("--include-weather",action="store_true"); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test: self_test(); return
    start=date.fromisoformat(args.start_date) if args.start_date else None; end=date.fromisoformat(args.end_date) if args.end_date else None; rows=replay_rows(args.replay,start,end,args.max_games)
    if not rows: raise SystemExit("No replay rows matched the requested range.")
    weather=weather_bulk([r["home"] for r in rows],min(eastern_day(r["game_date"]) for r in rows),max(eastern_day(r["game_date"]) for r in rows)) if args.include_weather else None
    state=WalkState(); results=[]; failures=[]; by_day=defaultdict(list)
    for r in rows: by_day[eastern_day(r["game_date"])].append(r)
    for idx,day in enumerate(sorted(by_day),1):
        day_rows=sorted(by_day[day],key=lambda r:(parse_dt(r["game_date"]),int(r["game_pk"]))); boxes=fetch_boxscores(day_rows,args.workers)
        for r in day_rows:
            box=boxes.get(r["game_pk"]) or {}
            if box.get("_error") or not box.get("teams"): failures.append({"game_pk":r["game_pk"],"error":box.get("_error","missing teams")}); continue
            pred=build_prediction(state,r,box,weather,args.include_posted)
            if pred: results.append(pred)
        for r in day_rows:
            box=boxes.get(r["game_pk"]) or {}
            if box.get("teams"): ingest_game(state,r,box)
        if idx%10==0 or idx==len(by_day): print(f"[walkforward] day {idx}/{len(by_day)} | predictions={len(results)} | fetch_failures={len(failures)}")
    if not results: raise SystemExit("No usable historical predictions were produced.")
    write_jsonl(args.output,results); split=max(1,int(len(results)*.75)); train,holdout=results[:split],results[split:]; monthly={}
    for r in results: monthly.setdefault(str(r["eastern_day"])[:7],[]).append(r)
    report={"version":VERSION,"created_at":datetime.now(timezone.utc).isoformat(),"official_effect":False,"source":{"baseline":str(args.replay),"baseline_probability":"row.v10.p_home","baseline_run_means":"row.v10.home_mu/away_mu","v11_features":"strict rolling reconstruction from prior Eastern calendar dates only"},"date_range":{"start":min(r["eastern_day"] for r in results),"end":max(r["eastern_day"] for r in results)},"samples":{"requested_replay_rows":len(rows),"usable_predictions":len(results),"fetch_failures":len(failures),"train_n":len(train),"holdout_n":len(holdout)},"weights":{"bullpen":W_BP,"starter_recent":W_SP,"lineup":W_LU,"matchup":W_MU},"methodology":{"same_day_policy":"predict all games on an Eastern date before ingesting any result/boxscore from that date","projected_lineup":"prior 7 batting orders + rolling prior-game hitter production","posted_retro":bool(args.include_posted),"posted_retro_caveat":"actual historical batting order is an optional retrospective LATE scenario; exact publication timestamp is not archived","player_bat_side":"static biographical attribute only; outcomes/stats remain strictly prior-game","historical_weather":bool(args.include_weather),"weather_ml_effect":False,"historical_sharp_prices":False,"roi_claims":False},"all":metrics_bundle(results),"train_75pct":metrics_bundle(train),"holdout_25pct":metrics_bundle(holdout),"monthly":{k:metrics_bundle(v) for k,v in sorted(monthly.items())},"fetch_failure_sample":failures[:25],"promotion_policy":{"history_can_support_candidate":True,"history_alone_can_activate_production":False,"live_point_in_time_confirmation_still_required":True},"caveats":["The existing V10 replay is reused as the baseline; its original report documents frozen-input spot-check limitations.","V11.1 feature reconstruction itself is chronological and never ingests the current Eastern-date boxscore before predicting that date.","POSTED_RETRO is not an EARLY simulation because historical lineup publication timestamps are unavailable.","No historical sharp-price or profitability claim is made without archived point-in-time bookmaker prices."]}
    Path(args.report).parent.mkdir(parents=True,exist_ok=True); Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"version":VERSION,"usable_predictions":len(results),"fetch_failures":len(failures),"all_base_brier":report["all"]["models"].get("base_p_home",{}).get("brier"),"all_full_projected_brier":report["all"]["models"].get("p_full_projected",{}).get("brier"),"holdout_full_projected_gain":report["holdout_25pct"]["models"].get("p_full_projected",{}).get("brier_gain"),"full_projected_coverage":report["all"]["coverage"].get("full_projected")},indent=2))


if __name__=="__main__": main()
