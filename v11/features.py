from __future__ import annotations
import math
from datetime import date, timedelta

def _num(x, d=0.0):
    try:
        y = float(x); return y if math.isfinite(y) else d
    except Exception: return d

OPS_KEYS = {"ops", "weighted_ops", "season_ops", "prior_ops", "onbaseplusslugging"}

def _collect_ops_values(obj, out, depth=0):
    if depth > 6 or obj is None: return
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower().replace("_", "")
            if lk in OPS_KEYS or str(k).lower() in OPS_KEYS:
                x = _num(v, -1)
                if .30 <= x <= 1.50: out.append(x)
            elif isinstance(v, (dict, list, tuple)): _collect_ops_values(v, out, depth+1)
    elif isinstance(obj, (list, tuple)):
        for v in obj: _collect_ops_values(v, out, depth+1)

def lineup_ops(ctx, side, regular_ops, allow_player_fallback=False):
    lineup = ctx.get(f"{side}_lineup") or {}; count = int(_num(lineup.get("count"), 0)); direct = lineup.get("weighted_ops")
    if direct is not None and .30 <= _num(direct, -1) <= 1.50 and count >= 5: return _num(direct), True, count, "weighted_ops"
    if allow_player_fallback:
        values = []; _collect_ops_values(lineup, values)
        if len(values) >= 5:
            values = sorted(values); trimmed = values[1:-1] if len(values) >= 7 else values
            return sum(trimmed)/len(trimmed), True, max(count, len(values)), "player_ops_fallback"
    return float(regular_ops), False, count, "team_ops_fallback"

def live_ml_features(core, result, allow_player_fallback=False):
    """Production defaults preserve the historically validated V11.3 lineup contract."""
    ctx = result.get("ctx") or {}; lg_ops = _num(core.league_baselines().get("ops"), .710)
    hreg = _num((core.season_stats(ctx.get("home_id"), "hitting") or {}).get("ops"), lg_ops); areg = _num((core.season_stats(ctx.get("away_id"), "hitting") or {}).get("ops"), lg_ops)
    hlu, hok, hc, hsrc = lineup_ops(ctx, "home", hreg, allow_player_fallback); alu, aok, ac, asrc = lineup_ops(ctx, "away", areg, allow_player_fallback); lineup_ok = bool(hok and aok)
    if lineup_ok:
        relative = ((hlu-hreg) - (alu-areg)) / .08; regular_overlap = (hreg-areg) / .08; lineup_abs = (hlu-alu) / .08
    else: relative = regular_overlap = lineup_abs = 0.0
    base = max(.001, min(.999, _num(result.get("p_model"), .5))); strength = min(abs(math.log(base/(1-base))), 2.5) / 2.5
    return {"lineup_relative": relative, "regular_overlap": regular_overlap, "lineup_abs": lineup_abs, "lineup_cov_diff": 0.0, "lineup_x_uncertainty": relative*(1-strength), "lineup_available": 1.0 if lineup_ok else 0.0, "home_lineup_ops": hlu, "away_lineup_ops": alu, "home_regular_ops": hreg, "away_regular_ops": areg, "home_lineup_count": hc, "away_lineup_count": ac, "lineup_both_available": lineup_ok, "home_lineup_source": hsrc, "away_lineup_source": asrc}

def snapshot_features(core, result):
    ctx = result.get("ctx") or {}; con = result.get("con") or {}; hmu, amu = _num(result.get("hmu")), _num(result.get("amu")); market_total = None
    totals = [r for r in core.v1011_iter_options(result) if str(r.get("market") or "").upper() == "TOTAL"]
    if totals:
        pts = [_num(r.get("point"), -1) for r in totals if r.get("point") is not None]; pts = [x for x in pts if x > 0]; market_total = sum(pts)/len(pts) if pts else None
    return {"projected_home_runs": round(hmu,4), "projected_away_runs": round(amu,4), "projected_run_diff_home": round(hmu-amu,4), "projected_total": round(hmu+amu,4), "projected_total_residual": round((hmu+amu)-(market_total if market_total is not None else hmu+amu),4), "market_home_probability": round(_num(con.get("p"), .5),6) if con.get("p") is not None else None, "market_reference_books": int(_num(con.get("n"),0)), "quality": round(_num(result.get("quality")),4), "phase": result.get("phase"), "home_team_id": ctx.get("home_id"), "away_team_id": ctx.get("away_id"), "starter_home": ctx.get("home_sp"), "starter_away": ctx.get("away_sp"), "venue_id": ((result.get("game") or {}).get("venue") or {}).get("id")}

def point_in_time_snapshot(core, result, analyzed_at):
    ctx = result.get("ctx") or {}; market_snapshot = None
    try: market_snapshot = core.serialize_market(result.get("event") or {})
    except Exception: pass
    weather = result.get("weather") or (ctx.get("weather") if isinstance(ctx, dict) else None)
    return {"analyzed_at": analyzed_at, "phase": result.get("phase"), "game_date": (result.get("game") or {}).get("gameDate"), "home_lineup": ctx.get("home_lineup"), "away_lineup": ctx.get("away_lineup"), "home_starter": ctx.get("home_sp"), "away_starter": ctx.get("away_sp"), "weather": weather, "market_snapshot": market_snapshot, "operational_features": result.get("v11_operational_features")}

def _haversine_km(a,b):
    if not a or not b:return None
    lat1,lon1,lat2,lon2=map(math.radians,(a[0],a[1],b[0],b[1])); dlat=lat2-lat1; dlon=lon2-lon1; h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371.0*2*math.asin(min(1.0,math.sqrt(h)))

def build_previous_game_index(core,target_date,results):
    try: target=date.fromisoformat(str(target_date))
    except Exception:return {}
    wanted={str((r.get("ctx") or {}).get(k)) for r in results for k in ("home_id","away_id") if (r.get("ctx") or {}).get(k)}; found={}
    for back in range(1,5):
        day=(target-timedelta(days=back)).isoformat()
        try: games=core.mlb_schedule(day,hydrate="linescore")
        except Exception: continue
        for g in games:
            teams=g.get("teams") or {}; home_name=((teams.get("home") or {}).get("team") or {}).get("name"); venue=(g.get("venue") or {}).get("id"); innings=int(_num((g.get("linescore") or {}).get("currentInning"),9))
            for side in ("home","away"):
                tid=str(((teams.get(side) or {}).get("team") or {}).get("id") or "")
                if tid in wanted and tid not in found: found[tid]={"days_back":back,"game_pk":g.get("gamePk"),"venue_id":venue,"venue_home_team":home_name,"extra_innings":innings>9,"doubleheader":str(g.get("doubleHeader") or "N")!="N"}
        if wanted.issubset(found):break
    return found

def _starter_feature(core,game,side):
    try: pid=((game.get("teams") or {}).get(side) or {}).get("probablePitcher",{}).get("id")
    except Exception: pid=None
    stats=core.player_stats(pid,"pitching") if pid else {}
    return {"id":pid,"era":_num(stats.get("era"),None) if stats.get("era") is not None else None,"whip":_num(stats.get("whip"),None) if stats.get("whip") is not None else None,"strikeouts_per9":_num(stats.get("strikeoutsPer9Inn"),None) if stats.get("strikeoutsPer9Inn") is not None else None,"walks_per9":_num(stats.get("walksPer9Inn"),None) if stats.get("walksPer9Inn") is not None else None,"home_runs_per9":_num(stats.get("homeRunsPer9"),None) if stats.get("homeRunsPer9") is not None else None,"innings":_num(stats.get("inningsPitched"),None) if stats.get("inningsPitched") is not None else None}

def _recent_bullpen_usage(core,prev,team_id):
    if not prev or not prev.get("game_pk"):return None
    try: box=core.mlb(f"v1/game/{prev['game_pk']}/boxscore")
    except Exception:return None
    teams=box.get("teams") or {}; team=None
    for side in ("home","away"):
        t=teams.get(side) or {}
        if str((t.get("team") or {}).get("id") or "")==str(team_id):team=t;break
    if not team:return None
    pitchers=list(team.get("pitchers") or []); relievers=pitchers[1:] if len(pitchers)>1 else [] ; players=team.get("players") or {}; usage=[]
    for pid in relievers:
        p=players.get(f"ID{pid}") or {}; st=((p.get("stats") or {}).get("pitching") or {}); pitches=int(_num(st.get("pitchesThrown"),0)); season=core.player_stats(pid,"pitching") if pid else {}; era=_num(season.get("era"),99)
        usage.append({"id":pid,"name":((p.get("person") or {}).get("fullName")),"pitches":pitches,"season_era":era if era<50 else None})
    usage.sort(key=lambda x:(x["pitches"],-(x["season_era"] if x["season_era"] is not None else 99)),reverse=True)
    return {"relievers_used":len(usage),"total_relief_pitches":sum(x["pitches"] for x in usage),"heavy_usage_count":sum(x["pitches"]>=20 for x in usage),"top_usage":usage[:4]}

def operational_features(core,result,previous_index):
    ctx=result.get("ctx") or {}; game=result.get("game") or {}; current_home=ctx.get("home"); current_coord=(getattr(core,"COORD",{}) or {}).get(current_home); out={"enhanced_lineup_shadow":live_ml_features(core,result,allow_player_fallback=True),"starter_home":_starter_feature(core,game,"home"),"starter_away":_starter_feature(core,game,"away"),"current_doubleheader":str(game.get("doubleHeader") or "N")!="N"}
    for side in ("home","away"):
        tid=str(ctx.get(f"{side}_id") or ""); prev=previous_index.get(tid); prefix=f"{side}_"
        if not prev:
            out.update({prefix+"rest_days":None,prefix+"travel_km":None,prefix+"timezone_shift_hours_approx":None,prefix+"previous_extra_innings":None,prefix+"previous_doubleheader":None,prefix+"bullpen_usage_previous_game":None}); continue
        prev_coord=(getattr(core,"COORD",{}) or {}).get(prev.get("venue_home_team")); distance=_haversine_km(prev_coord,current_coord); shift=None
        if prev_coord and current_coord: shift=round((current_coord[1]-prev_coord[1])/15.0,2)
        out.update({prefix+"rest_days":max(0,int(prev.get("days_back",1))-1),prefix+"travel_km":round(distance,1) if distance is not None else None,prefix+"timezone_shift_hours_approx":shift,prefix+"previous_extra_innings":bool(prev.get("extra_innings")),prefix+"previous_doubleheader":bool(prev.get("doubleheader")),prefix+"bullpen_usage_previous_game":_recent_bullpen_usage(core,prev,tid)})
    result["v11_operational_features"]=out; return out
