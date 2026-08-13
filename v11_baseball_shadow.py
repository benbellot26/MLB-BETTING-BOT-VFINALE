#!/usr/bin/env python3
"""V11.1.1 point-in-time baseball shadow research.

This module never changes official bets. It collects five baseball context blocks
and grades each correction against the independent production probability.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import bot as core
import v11_benchmark_report as bench

SHADOW_VERSION = "11.1.1-baseball-shadow-v2"
SHADOW_OUT = Path(os.getenv("V11_BASEBALL_SHADOW_FILE", "data/v11_baseball_shadow.jsonl"))
SHADOW_REPORT = Path(os.getenv("V11_BASEBALL_SHADOW_REPORT", "data/v11_baseball_shadow_report.json"))
W_BP = float(os.getenv("V11_BASEBALL_W_BULLPEN", "0.16") or .16)
W_SP = float(os.getenv("V11_BASEBALL_W_STARTER", "0.14") or .14)
W_LU = float(os.getenv("V11_BASEBALL_W_LINEUP", "0.12") or .12)
W_MU = float(os.getenv("V11_BASEBALL_W_MATCHUP", "0.10") or .10)
MIN_FINAL = max(40, int(os.getenv("V11_BASEBALL_MIN_FINAL", "80") or 80))
MIN_HOLDOUT = max(20, int(os.getenv("V11_BASEBALL_MIN_HOLDOUT", "30") or 30))
MIN_GAIN = max(0.0, float(os.getenv("V11_BASEBALL_MIN_BRIER_GAIN", "0.0015") or .0015))
MIN_GAIN_PROB = core.clamp(float(os.getenv("V11_BASEBALL_MIN_GAIN_PROB", "0.85") or .85), .5, 1.0)
MIN_COVERAGE = core.clamp(float(os.getenv("V11_BASEBALL_MIN_FULL_COVERAGE", "0.55") or .55), .25, 1.0)
ORDER_W = (1.08, 1.10, 1.10, 1.08, 1.03, .98, .94, .90, .88)


def _schedule(start, end=None):
    try:
        d = core.mlb("v1/schedule", {
            "sportId": 1,
            "startDate": str(start),
            "endDate": str(end or start),
            "hydrate": "probablePitcher,venue,team",
        })
        return [g for block in d.get("dates", []) for g in block.get("games", [])]
    except Exception:
        return []


def _feed(pk):
    try:
        return core.feed_live(int(pk), True)
    except Exception:
        try:
            return core.mlb(f"v1.1/game/{int(pk)}/feed/live")
        except Exception:
            return {}


def _team_id(game, side):
    return int((((game.get("teams") or {}).get(side) or {}).get("team") or {}).get("id") or 0)


def _team_name(game, side):
    return str(((((game.get("teams") or {}).get(side) or {}).get("team") or {}).get("name")) or "")


def _entry(box, pid):
    return (box.get("players") or {}).get(f"ID{int(pid)}", {})


def _person(feed, pid):
    if not pid:
        return {}
    p = (feed.get("gameData", {}).get("players") or {}).get(f"ID{int(pid)}", {})
    if p:
        return p
    try:
        return core.person_info(int(pid)) or {}
    except Exception:
        return {}


def _pstat(entry, season=True):
    return ((entry.get("seasonStats") if season else entry.get("stats")) or {}).get("pitching") or {}


def _bstat(entry):
    return (entry.get("seasonStats") or {}).get("batting") or {}


def _innings(value):
    s = str(value or "0")
    if "." not in s:
        return core.num(s, 0)
    whole, frac = s.split(".", 1)
    outs = int(frac[:1] or 0)
    return core.num(whole, 0) + outs / 3 if outs in (0, 1, 2) else core.num(s, 0)


def _fip(st):
    ip = _innings(st.get("inningsPitched"))
    if ip < 1:
        return None
    return (
        13 * core.num(st.get("homeRuns"))
        + 3 * (core.num(st.get("baseOnBalls")) + core.num(st.get("hitBatsmen", st.get("hitByPitch"))))
        - 2 * core.num(st.get("strikeOuts"))
    ) / ip + 3.20


def _pitch_quality(st):
    metric = _fip(st)
    if metric is None:
        metric = core.num(st.get("era", st.get("earnedRunAverage")), 4.25)
    return core.clamp((4.25 - metric) / 1.5, -1.0, 1.0)


def _availability(days):
    d1, d2, d3 = (core.num(days.get(i), 0) for i in (1, 2, 3))
    load = .018 * min(d1, 40) + .007 * min(d2, 40) + .003 * min(d3, 40)
    if d1 > 0 and d2 > 0:
        load += .18
    if d1 >= 30:
        load += .35
    elif d1 >= 20:
        load += .18
    if d1 + d2 >= 55:
        load += .15
    return core.clamp(1 - load, .05, 1.0)


def _ops(st):
    raw = core.num(st.get("ops"), .720)
    pa = core.num(st.get("plateAppearances"), 0)
    if not .2 <= raw <= 1.5:
        raw = core.num(st.get("onBasePercentage"), .320) + core.num(st.get("sluggingPercentage"), .400)
    w = pa / (pa + 80)
    return .720 + w * (raw - .720), pa


def _recent_context(team_ids, target):
    """Build bullpen and projected-lineup context from already completed games."""
    ctx = defaultdict(lambda: {
        "relievers": {},
        "hitters": {},
        "lineup_games": 0,
    })
    start = target - timedelta(days=7)
    end = target - timedelta(days=1)
    for game in _schedule(start.isoformat(), end.isoformat()):
        if str(game.get("status", {}).get("abstractGameState") or "").lower() != "final":
            continue
        try:
            age = (target - date.fromisoformat(str(game.get("officialDate")))).days
        except Exception:
            continue
        sides = [(side, _team_id(game, side)) for side in ("home", "away") if _team_id(game, side) in team_ids]
        if not sides:
            continue
        feed = _feed(game.get("gamePk"))
        boxes = feed.get("liveData", {}).get("boxscore", {}).get("teams") or {}
        for side, tid in sides:
            box = boxes.get(side) or {}
            pitchers = [int(x) for x in box.get("pitchers") or []]
            starter = pitchers[0] if pitchers else None
            for pid in pitchers:
                if pid == starter:
                    continue
                entry = _entry(box, pid)
                gst = _pstat(entry, False)
                pitches = core.num(gst.get("pitchesThrown"), 0)
                season = _pstat(entry, True)
                person = (entry.get("person") or {}) or _person(feed, pid)
                row = ctx[tid]["relievers"].setdefault(pid, {
                    "days": defaultdict(float), "season": {}, "name": person.get("fullName") or str(pid), "seen": 0,
                })
                if 1 <= age <= 3 and pitches > 0:
                    row["days"][age] += pitches
                if season:
                    row["season"] = season
                row["seen"] += 1
            order = [int(x) for x in box.get("battingOrder") or [] if str(x).isdigit()][:9]
            if len(order) >= 7:
                ctx[tid]["lineup_games"] += 1
            for pos, pid in enumerate(order, 1):
                entry = _entry(box, pid)
                person = (entry.get("person") or {}) or _person(feed, pid)
                bat = str((_person(feed, pid).get("batSide") or {}).get("code") or "").upper()
                row = ctx[tid]["hitters"].setdefault(pid, {
                    "appearances": 0, "order_sum": 0.0, "season": {}, "name": person.get("fullName") or str(pid), "bat_side": bat,
                })
                row["appearances"] += 1
                row["order_sum"] += pos
                if _bstat(entry):
                    row["season"] = _bstat(entry)
                if bat:
                    row["bat_side"] = bat
    return ctx


def _bullpen(team_ctx, starter):
    rows = []
    for pid, info in (team_ctx.get("relievers") or {}).items():
        if int(pid) == int(starter or -1):
            continue
        st = info.get("season") or {}
        q = _pitch_quality(st)
        days = info.get("days") or {}
        av = _availability(days)
        saves = core.num(st.get("saves"), 0)
        holds = core.num(st.get("holds"), 0)
        lev = 1 + min(saves, 25) / 25 + min(holds, 30) / 60 + .3 * max(q, 0) + .04 * min(core.num(info.get("seen"), 0), 5)
        loss = (1 - av) * (1 + .5 * max(q, 0))
        rows.append((pid, q, av, lev, loss, days, info.get("name") or str(pid)))
    if not rows:
        return {"available": False, "score": 0.0, "fatigue": None, "relievers": [], "source": "recent-final-games"}
    den = sum(x[3] for x in rows)
    avg = sum(x[4] * x[3] for x in rows) / den
    fatigue = sum((1 - x[2]) * x[3] for x in rows) / den
    detail = []
    for pid, q, av, lev, loss, days, name in sorted(rows, key=lambda x: (x[2], -x[1]))[:8]:
        detail.append({
            "id": int(pid), "name": name, "quality": round(q, 3), "availability": round(av, 3),
            "d1": core.num(days.get(1), 0), "d2": core.num(days.get(2), 0), "d3": core.num(days.get(3), 0),
        })
    return {
        "available": len(rows) >= 4,
        "score": round(-core.clamp(avg / .65, 0, 1.25), 4),
        "fatigue": round(fatigue, 4),
        "high_leverage_unavailable": sum(q > .2 and av < .4 for _, q, av, *_ in rows),
        "reliever_count": len(rows),
        "relievers": detail,
        "source": "recent-final-games",
    }


def _aggregate_pitch(stats):
    t = defaultdict(float)
    outs = 0
    for st in stats:
        outs += round(_innings(st.get("inningsPitched")) * 3)
        for k in ("earnedRuns", "homeRuns", "baseOnBalls", "hitBatsmen", "strikeOuts"):
            t[k] += core.num(st.get(k), 0)
    t["inningsPitched"] = outs / 3
    return dict(t)


def _starter_recent(pid, season):
    if not pid:
        return {"available": False, "score": 0.0, "starts": 0}
    try:
        splits = core.mlb(f"v1/people/{int(pid)}/stats", {"stats": "gameLog", "group": "pitching", "season": core.SEASON}).get("stats") or []
        logs = splits[0].get("splits") or [] if splits else []
    except Exception:
        logs = []
    recent = []
    for x in sorted(logs, key=lambda z: str(z.get("date") or ""), reverse=True):
        st = x.get("stat") or {}
        if _innings(st.get("inningsPitched")) > 0:
            recent.append(st)
        if len(recent) >= 5:
            break
    if not season:
        try:
            season = core.player_stats(int(pid), "pitching") or {}
        except Exception:
            season = {}
    if len(recent) < 2 or not season:
        return {"available": False, "score": 0.0, "starts": len(recent)}
    agg = _aggregate_pitch(recent)
    rip = core.num(agg.get("inningsPitched"), 0)
    recent_metric = _fip(agg) or 9 * core.num(agg.get("earnedRuns"), 0) / max(rip, 1)
    season_metric = _fip(season) or core.num(season.get("era", season.get("earnedRunAverage")), 4.25)
    w = rip / (rip + 20)
    shrunk = w * recent_metric + (1 - w) * season_metric
    form = core.clamp((season_metric - shrunk) / 1.25, -1.25, 1.25)
    recent_depth = rip / len(recent)
    sip = _innings(season.get("inningsPitched"))
    season_depth = sip / max(1, core.num(season.get("gamesStarted"), len(recent))) if sip else 5.2
    score = core.clamp(.8 * form + .2 * core.clamp((recent_depth - season_depth) / 1.5, -.75, .75), -1.25, 1.25)
    return {
        "available": True, "score": round(score, 4), "starts": len(recent),
        "recent_metric": round(recent_metric, 3), "season_metric": round(season_metric, 3),
        "shrunk_metric": round(shrunk, 3), "recent_weight": round(w, 3),
    }


def _probable(game, feed, side):
    x = (feed.get("gameData", {}).get("probablePitchers") or {}).get(side) or {}
    if x.get("id"):
        return int(x["id"])
    x = ((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {}
    return int(x["id"]) if x.get("id") else None


def _current_order(box):
    ids = [int(x) for x in box.get("battingOrder") or [] if str(x).isdigit()]
    if len(ids) >= 4:
        return ids[:9]
    ordered = []
    for entry in (box.get("players") or {}).values():
        order = int(core.num(entry.get("battingOrder"), 0))
        pid = (entry.get("person") or {}).get("id")
        if order > 0 and pid:
            ordered.append((order, int(pid)))
    return [pid for _, pid in sorted(ordered)[:9]]


def _projected_ids(team_ctx):
    rows = []
    for pid, info in (team_ctx.get("hitters") or {}).items():
        apps = core.num(info.get("appearances"), 0)
        if apps <= 0:
            continue
        avg_order = core.num(info.get("order_sum"), 0) / apps
        rows.append((-apps, avg_order, int(pid)))
    return [pid for _, _, pid in sorted(rows)[:9]]


def _lineup(box, feed, team_ctx):
    current = _current_order(box)
    projected = _projected_ids(team_ctx)
    if len(current) >= 9:
        ids, status, confidence = current[:9], "OFFICIAL_FEED", 1.0
    elif len(current) >= 4:
        ids = current + [x for x in projected if x not in current]
        ids, status, confidence = ids[:9], "PARTIAL", .65
    elif len(projected) >= 7:
        ids, status, confidence = projected[:9], "PROJECTED_RECENT", .45
    else:
        ids, status, confidence = current[:9], "UNAVAILABLE", 0.0
    regular = []
    for pid, info in (team_ctx.get("hitters") or {}).items():
        st = info.get("season") or {}
        op, pa = _ops(st)
        if pa > 0:
            regular.append((core.num(info.get("appearances"), 0), op, int(pid), info.get("name") or str(pid)))
    regular = sorted(regular, reverse=True)[:9]
    baseline = sum(x[1] for x in regular) / len(regular) if regular else .720
    hitters = []
    num = den = 0.0
    for i, pid in enumerate(ids[:9]):
        entry = _entry(box, pid)
        ctxh = (team_ctx.get("hitters") or {}).get(pid, {})
        st = _bstat(entry) or ctxh.get("season") or {}
        op, _ = _ops(st)
        person = (entry.get("person") or {}) or _person(feed, pid)
        bat = str((_person(feed, pid).get("batSide") or {}).get("code") or ctxh.get("bat_side") or "").upper()
        wt = ORDER_W[i]
        num += wt * op
        den += wt
        hitters.append({
            "id": pid, "order": i + 1, "ops": round(op, 4),
            "name": person.get("fullName") or ctxh.get("name") or str(pid), "bat_side": bat or None,
        })
    lineup_ops = num / den if den else None
    score = core.clamp(((lineup_ops - baseline) / .08) if lineup_ops is not None else 0, -1.25, 1.25) * confidence
    idset = set(ids)
    missing = sorted([x for x in regular if x[2] not in idset], key=lambda x: (x[1], x[0]), reverse=True)[:4]
    return {
        "available": len(ids) >= 7,
        "official": status == "OFFICIAL_FEED",
        "status": status,
        "confidence": confidence,
        "score": round(score, 4),
        "lineup_ops": round(lineup_ops, 4) if lineup_ops is not None else None,
        "regular_ops": round(baseline, 4),
        "hitters": hitters,
        "missing": [{"name": x[3], "ops": round(x[1], 4)} for x in missing],
        "recent_lineup_games": int(core.num(team_ctx.get("lineup_games"), 0)),
    }


def _starter_hand(feed, pid):
    if not pid:
        return None
    return str((_person(feed, pid).get("pitchHand") or {}).get("code") or "").upper() or None


def _matchup(lineup, feed, starter):
    hand = _starter_hand(feed, starter)
    if hand not in ("L", "R") or not lineup.get("hitters"):
        return {"available": False, "score": 0.0, "starter_hand": hand}
    vals = []
    advantage = 0
    for hitter in lineup["hitters"]:
        bat = str(hitter.get("bat_side") or "").upper()
        if bat == "S":
            platoon, advantage = 1.0, advantage + 1
        elif bat in ("L", "R") and bat != hand:
            platoon, advantage = .65, advantage + 1
        elif bat in ("L", "R"):
            platoon = -.35
        else:
            platoon = 0.0
        quality = core.clamp((core.num(hitter.get("ops"), .720) - .720) / .15, -.8, 1.2)
        wt = ORDER_W[int(hitter.get("order") or 1) - 1]
        vals.append((platoon * (.75 + .25 * max(quality, -.5)), wt))
    score = (sum(v * w for v, w in vals) / sum(w for _, w in vals)) * core.num(lineup.get("confidence"), 0) if vals else 0
    return {
        "available": bool(vals) and bool(lineup.get("available")),
        "score": round(core.clamp(score, -1, 1), 4),
        "starter_hand": hand,
        "advantage_hitters": advantage,
    }


def _parse_feed_wind(feed):
    weather = feed.get("gameData", {}).get("weather") or {}
    text = str(weather.get("wind") or "").strip()
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*mph", text, re.I)
    speed = core.num(m.group(1), 0) if m else 0.0
    low = text.lower()
    if "out to" in low or "out toward" in low:
        component, label = speed, "OUT"
    elif "in from" in low or "in toward" in low:
        component, label = -speed, "IN"
    elif "left to right" in low or "right to left" in low or "cross" in low:
        component, label = 0.0, "CROSS"
    else:
        return None
    return {"speed": speed, "component": component, "label": label, "source": "MLB-feed", "raw": text}


def _weather(home, game_time, feed):
    cond = str((feed.get("gameData", {}).get("weather") or {}).get("condition") or "").lower()
    if home in getattr(core, "DOME", set()) or any(x in cond for x in ("dome", "indoor", "roof closed")):
        return {"available": True, "directional": True, "indoor": True, "run_delta": 0.0, "direction": "INDOOR", "source": "MLB-feed"}
    feed_wind = _parse_feed_wind(feed)
    try:
        base_weather = core.weather(home, game_time) or {}
    except Exception:
        base_weather = {}
    if not feed_wind:
        return {
            "available": bool(core.num(base_weather.get("quality"), 0) > 0),
            "directional": False,
            "indoor": False,
            "run_delta": 0.0,
            "direction": "UNKNOWN",
            "source": "Open-Meteo-no-field-direction",
            "base_text": base_weather.get("text"),
        }
    component = core.num(feed_wind.get("component"), 0)
    delta = core.clamp(.025 * component, -.55, .55)
    if home in getattr(core, "ROOF", set()) and "roof open" not in cond:
        delta *= .35
    return {
        "available": True,
        "directional": True,
        "indoor": False,
        "run_delta": round(delta, 4),
        "wind_mph": round(core.num(feed_wind.get("speed"), 0), 1),
        "out_component": round(component, 2),
        "direction": feed_wind.get("label"),
        "source": feed_wind.get("source"),
        "raw": feed_wind.get("raw"),
        "base_text": base_weather.get("text"),
    }


def _base_runs(snapshot):
    if not snapshot:
        return None, None
    home_keys = ("home_mu", "base_home", "lambda_home", "mu_home", "pred_home_runs", "home_runs_model", "runs_home", "home_run_mean")
    away_keys = ("away_mu", "base_away", "lambda_away", "mu_away", "pred_away_runs", "away_runs_model", "runs_away", "away_run_mean")
    blocks = [snapshot] + [snapshot[k] for k in ("run_model", "runs", "run_projection", "score_projection") if isinstance(snapshot.get(k), dict)]
    for block in blocks:
        h = next((core.num(block[k], -1) for k in home_keys if block.get(k) is not None), None)
        a = next((core.num(block[k], -1) for k in away_keys if block.get(k) is not None), None)
        if h is not None and a is not None and .5 <= h <= 12 and .5 <= a <= 12:
            return h, a
    return None, None


def _adjust_p(p, delta):
    p = core.clamp(core.num(p, .5), .001, .999)
    z = math.log(p / (1 - p)) + core.clamp(delta, -.6, .6)
    return core.clamp(1 / (1 + math.exp(-z)), .001, .999)


def _analyze_game(game, history, recent):
    pk = int(game.get("gamePk"))
    home, away = _team_name(game, "home"), _team_name(game, "away")
    rec = history.get(str(pk), history.get(pk, {}))
    snap = bench._latest_snapshot(rec) if rec else None
    base = bench._snapshot_model_home(snap, home) if snap else None
    base_h, base_a = _base_runs(snap)
    feed = _feed(pk)
    boxes = feed.get("liveData", {}).get("boxscore", {}).get("teams") or {}
    home_box, away_box = boxes.get("home") or {}, boxes.get("away") or {}
    home_id, away_id = _team_id(game, "home"), _team_id(game, "away")
    home_sp, away_sp = _probable(game, feed, "home"), _probable(game, feed, "away")

    home_bp = _bullpen(recent.get(home_id, {}), home_sp)
    away_bp = _bullpen(recent.get(away_id, {}), away_sp)
    home_sr = _starter_recent(home_sp, _pstat(_entry(home_box, home_sp), True) if home_sp else {})
    away_sr = _starter_recent(away_sp, _pstat(_entry(away_box, away_sp), True) if away_sp else {})
    home_lu = _lineup(home_box, feed, recent.get(home_id, {}))
    away_lu = _lineup(away_box, feed, recent.get(away_id, {}))
    home_mu = _matchup(home_lu, feed, away_sp)
    away_mu = _matchup(away_lu, feed, home_sp)
    weather = _weather(home, game.get("gameDate"), feed)

    d_bp = W_BP * (core.num(home_bp.get("score"), 0) - core.num(away_bp.get("score"), 0))
    d_sp = W_SP * (core.num(home_sr.get("score"), 0) - core.num(away_sr.get("score"), 0))
    d_lu = W_LU * (core.num(home_lu.get("score"), 0) - core.num(away_lu.get("score"), 0))
    d_mu = W_MU * (core.num(home_mu.get("score"), 0) - core.num(away_mu.get("score"), 0))
    full = core.clamp(d_bp + d_sp + d_lu + d_mu, -.45, .45)

    wind_half = core.num(weather.get("run_delta"), 0) / 2
    home_run_delta = core.clamp(wind_half + .18 * core.num(home_lu.get("score"), 0) + .12 * core.num(home_mu.get("score"), 0) - .18 * core.num(away_sr.get("score"), 0) - .16 * core.num(away_bp.get("score"), 0), -.75, .75)
    away_run_delta = core.clamp(wind_half + .18 * core.num(away_lu.get("score"), 0) + .12 * core.num(away_mu.get("score"), 0) - .18 * core.num(home_sr.get("score"), 0) - .16 * core.num(home_bp.get("score"), 0), -.75, .75)

    coverage = {
        "bullpen_both": bool(home_bp.get("available") and away_bp.get("available")),
        "starter_both": bool(home_sr.get("available") and away_sr.get("available")),
        "lineup_both": bool(home_lu.get("available") and away_lu.get("available")),
        "lineup_official_both": bool(home_lu.get("official") and away_lu.get("official")),
        "matchup_both": bool(home_mu.get("available") and away_mu.get("available")),
        "weather_directional": bool(weather.get("directional")),
        "run_means": bool(base_h is not None and base_a is not None),
    }
    coverage["full"] = all(coverage[k] for k in ("bullpen_both", "starter_both", "lineup_both", "matchup_both", "weather_directional"))

    row = {
        "shadow_version": SHADOW_VERSION,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "game_pk": pk,
        "game_date": game.get("officialDate"),
        "game_time": game.get("gameDate"),
        "home": home, "away": away,
        "phase": (snap or {}).get("phase"),
        "seconds_to_game": (snap or {}).get("seconds_to_game"),
        "base_p_home": round(base, 6) if base is not None else None,
        "base_home_runs": base_h, "base_away_runs": base_a,
        "shadow_home_run_delta": round(home_run_delta, 4), "shadow_away_run_delta": round(away_run_delta, 4),
        "shadow_home_runs": round(core.clamp(base_h + home_run_delta, .5, 12), 4) if base_h is not None else None,
        "shadow_away_runs": round(core.clamp(base_a + away_run_delta, .5, 12), 4) if base_a is not None else None,
        "adjustments": {"bullpen": round(d_bp, 6), "starter_recent": round(d_sp, 6), "lineup": round(d_lu, 6), "matchup": round(d_mu, 6), "full": round(full, 6)},
        "features": {
            "home_bullpen": home_bp, "away_bullpen": away_bp,
            "home_starter_recent": home_sr, "away_starter_recent": away_sr,
            "home_lineup": home_lu, "away_lineup": away_lu,
            "home_matchup": home_mu, "away_matchup": away_mu,
            "weather": weather,
        },
        "coverage": coverage,
        "official_effect": False,
    }
    if base is not None:
        row.update({
            "shadow_p_bullpen": round(_adjust_p(base, d_bp), 6),
            "shadow_p_starter": round(_adjust_p(base, d_sp), 6),
            "shadow_p_lineup": round(_adjust_p(base, d_lu), 6),
            "shadow_p_matchup": round(_adjust_p(base, d_mu), 6),
            "shadow_p_full": round(_adjust_p(base, full), 6),
        })
    return row


def _read_rows():
    if not SHADOW_OUT.exists():
        return []
    rows = []
    for line in SHADOW_OUT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def _actual_scores(rec):
    for hk, ak in (("home_score", "away_score"), ("score_home", "score_away")):
        if rec.get(hk) is not None and rec.get(ak) is not None:
            return core.num(rec.get(hk)), core.num(rec.get(ak))
    return None, None


def _final_rows(rows, hist):
    best = {}
    for row in rows:
        if row.get("shadow_version") != SHADOW_VERSION:
            continue
        rec = hist.get(str(row.get("game_pk")), hist.get(row.get("game_pk"), {}))
        y = rec.get("home_win")
        if rec.get("status") != "FINAL" or y not in (0, 1) or core.num(row.get("seconds_to_game"), -1) < 0:
            continue
        rank = (-core.num(row.get("seconds_to_game"), 1e12), str(row.get("analyzed_at") or ""))
        old = best.get(str(row.get("game_pk")))
        if old is None or rank > old[0]:
            z = dict(row)
            z["y"] = int(y)
            z["actual_home_runs"], z["actual_away_runs"] = _actual_scores(rec)
            best[str(row.get("game_pk"))] = (rank, z)
    return sorted([x[1] for x in best.values()], key=lambda r: (str(r.get("game_date")), str(r.get("game_pk"))))


def _brier(rows, field):
    xs = [(core.num(r.get(field), .5), r["y"]) for r in rows if r.get(field) is not None]
    return sum((p - y) ** 2 for p, y in xs) / len(xs) if xs else None


def _logloss(rows, field):
    xs = [(core.clamp(core.num(r.get(field), .5), .001, .999), r["y"]) for r in rows if r.get(field) is not None]
    return sum(-(y * math.log(p) + (1 - y) * math.log(1 - p)) for p, y in xs) / len(xs) if xs else None


def _metrics(rows):
    out = {"n": len(rows)}
    fields = ("base_p_home", "shadow_p_bullpen", "shadow_p_starter", "shadow_p_lineup", "shadow_p_matchup", "shadow_p_full")
    for field in fields:
        out["brier_" + field] = _brier(rows, field)
        out["logloss_" + field] = _logloss(rows, field)
    usable = [r for r in rows if r.get("base_p_home") is not None and r.get("shadow_p_full") is not None]
    if usable:
        base_losses = [(core.num(r["base_p_home"], .5) - r["y"]) ** 2 for r in usable]
        new_losses = [(core.num(r["shadow_p_full"], .5) - r["y"]) ** 2 for r in usable]
        out["brier_gain_full"] = sum(base_losses) / len(base_losses) - sum(new_losses) / len(new_losses)
        out["paired_gain_probability"] = core.bootstrap_gain_prob(base_losses, new_losses, reps=1000)
    else:
        out["brier_gain_full"] = None
        out["paired_gain_probability"] = None
    run_rows = [r for r in rows if None not in (r.get("actual_home_runs"), r.get("actual_away_runs"), r.get("base_home_runs"), r.get("base_away_runs"), r.get("shadow_home_runs"), r.get("shadow_away_runs"))]
    if run_rows:
        base_err, shadow_err = [], []
        for r in run_rows:
            base_err += [abs(core.num(r["base_home_runs"]) - core.num(r["actual_home_runs"])), abs(core.num(r["base_away_runs"]) - core.num(r["actual_away_runs"]))]
            shadow_err += [abs(core.num(r["shadow_home_runs"]) - core.num(r["actual_home_runs"])), abs(core.num(r["shadow_away_runs"]) - core.num(r["actual_away_runs"]))]
        out.update({
            "run_n_games": len(run_rows),
            "run_mae_base_per_team": sum(base_err) / len(base_err),
            "run_mae_shadow_per_team": sum(shadow_err) / len(shadow_err),
            "run_mae_gain": sum(base_err) / len(base_err) - sum(shadow_err) / len(shadow_err),
        })
    else:
        out.update({"run_n_games": 0, "run_mae_base_per_team": None, "run_mae_shadow_per_team": None, "run_mae_gain": None})
    return out


def _coverage(rows):
    keys = ("bullpen_both", "starter_both", "lineup_both", "lineup_official_both", "matchup_both", "weather_directional", "run_means", "full")
    out = {}
    for key in keys:
        vals = [bool((r.get("coverage") or {}).get(key)) for r in rows]
        out[key] = sum(vals) / len(vals) if vals else None
    return out


def main():
    hist = core.load_history()
    raw = os.getenv("MLB_DATE", "").strip()
    try:
        target = date.fromisoformat(raw) if raw else core.NOW.date()
    except Exception:
        target = core.NOW.date()
    games = _schedule(target.isoformat())
    preview = [g for g in games if str(g.get("status", {}).get("abstractGameState") or "").lower() == "preview"]
    team_ids = {_team_id(g, side) for g in preview for side in ("home", "away") if _team_id(g, side)}
    recent = _recent_context(team_ids, target)

    current = []
    for game in preview:
        try:
            current.append(_analyze_game(game, hist, recent))
        except Exception as exc:
            print(f"[V11.1.1 SHADOW] game {game.get('gamePk')} skipped: {exc}", file=sys.stderr)
    if current:
        SHADOW_OUT.parent.mkdir(parents=True, exist_ok=True)
        with SHADOW_OUT.open("a", encoding="utf-8") as fh:
            for row in current:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    finals = _final_rows(_read_rows(), hist)
    cut = int(len(finals) * .75)
    holdout = finals[cut:]
    all_metrics, hold_metrics = _metrics(finals), _metrics(holdout)
    hold_cov = _coverage(holdout)
    gain = hold_metrics.get("brier_gain_full")
    candidate = bool(
        len(finals) >= MIN_FINAL
        and len(holdout) >= MIN_HOLDOUT
        and gain is not None and gain >= MIN_GAIN
        and core.num(hold_metrics.get("paired_gain_probability"), 0) >= MIN_GAIN_PROB
        and hold_metrics.get("logloss_shadow_p_full") is not None
        and hold_metrics.get("logloss_base_p_home") is not None
        and hold_metrics["logloss_shadow_p_full"] <= hold_metrics["logloss_base_p_home"]
        and core.num(hold_cov.get("full"), 0) >= MIN_COVERAGE
    )
    report = {
        "shadow_version": SHADOW_VERSION,
        "official_effect": False,
        "method": "point-in-time baseball feature shadow v2; bullpen from prior final games; projected/official lineups; feed-direction wind; corrected run means; ablation metrics",
        "weights": {"bullpen": W_BP, "starter_recent": W_SP, "lineup": W_LU, "matchup": W_MU},
        "samples": {"final_games": len(finals), "train_n": cut, "holdout_n": len(holdout)},
        "coverage": _coverage(finals),
        "holdout_coverage": hold_cov,
        "matched_all": all_metrics,
        "holdout": hold_metrics,
        "future_activation_gate": {
            "candidate_only": candidate,
            "auto_activation": False,
            "min_final": MIN_FINAL,
            "min_holdout": MIN_HOLDOUT,
            "min_brier_gain": MIN_GAIN,
            "min_gain_probability": MIN_GAIN_PROB,
            "min_full_coverage": MIN_COVERAGE,
        },
        "current_run": {
            "date": target.isoformat(),
            "preview_games": len(preview),
            "rows_written": len(current),
            "base_probability_coverage": sum(r.get("base_p_home") is not None for r in current) / len(current) if current else None,
            "feature_coverage": _coverage(current),
        },
    }
    SHADOW_REPORT.parent.mkdir(parents=True, exist_ok=True)
    SHADOW_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def self_test():
    assert _availability({}) == 1.0
    assert _availability({1: 32, 2: 12}) < .25
    assert abs(_innings("5.2") - (5 + 2 / 3)) < 1e-6
    assert _adjust_p(.5, .2) > .54
    assert _base_runs({"home_mu": 4.6, "away_mu": 3.9}) == (4.6, 3.9)
    assert _parse_feed_wind({"gameData": {"weather": {"wind": "12 mph, Out To CF"}}})["component"] == 12
    assert _parse_feed_wind({"gameData": {"weather": {"wind": "10 mph, In From CF"}}})["component"] == -10
    print("SELF-TEST V11.1.1 BASEBALL SHADOW OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
