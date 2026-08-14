from __future__ import annotations
import math

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

def lineup_ops(ctx, side, regular_ops):
    lineup = ctx.get(f"{side}_lineup") or {}; count = int(_num(lineup.get("count"), 0)); direct = lineup.get("weighted_ops")
    if direct is not None and .30 <= _num(direct, -1) <= 1.50 and count >= 5: return _num(direct), True, count, "weighted_ops"
    values = []; _collect_ops_values(lineup, values)
    if len(values) >= 5:
        values = sorted(values); trimmed = values[1:-1] if len(values) >= 7 else values
        return sum(trimmed)/len(trimmed), True, max(count, len(values)), "player_ops_fallback"
    return float(regular_ops), False, count, "team_ops_fallback"

def live_ml_features(core, result):
    ctx = result.get("ctx") or {}; lg_ops = _num(core.league_baselines().get("ops"), .710)
    hreg = _num((core.season_stats(ctx.get("home_id"), "hitting") or {}).get("ops"), lg_ops); areg = _num((core.season_stats(ctx.get("away_id"), "hitting") or {}).get("ops"), lg_ops)
    hlu, hok, hc, hsrc = lineup_ops(ctx, "home", hreg); alu, aok, ac, asrc = lineup_ops(ctx, "away", areg); lineup_ok = bool(hok and aok)
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
    return {"analyzed_at": analyzed_at, "phase": result.get("phase"), "game_date": (result.get("game") or {}).get("gameDate"), "home_lineup": ctx.get("home_lineup"), "away_lineup": ctx.get("away_lineup"), "home_starter": ctx.get("home_sp"), "away_starter": ctx.get("away_sp"), "weather": weather, "market_snapshot": market_snapshot}
