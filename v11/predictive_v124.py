from __future__ import annotations

import csv
import io
import json
import math
import os
from datetime import date, timedelta, timezone

from . import core, context, pro_model
from . import engine_v12 as engine

VERSION = "12.4-predictive-core-shadow-v1"
SCHEMA = "v12-4-predictive-shadow-v1"

MODULES = (
    ("platoon", "Platoon / handedness"),
    ("statcast", "Statcast expected metrics"),
    ("bullpen_player", "Bullpen player-level"),
    ("lineup_player", "Lineup player-level"),
    ("starter_ip", "Starter expected innings"),
    ("weather_park", "Weather x park"),
    ("uncertainty", "Uncertainty decomposition"),
    ("ensemble", "Model ensemble"),
)

_ORDER_WEIGHTS = (1.08, 1.07, 1.10, 1.12, 1.06, 1.00, .95, .91, .88)
_PERSON_CACHE = {}
_SPLIT_CACHE = {}
_SAVANT_CACHE = {}

# Parks where outside weather should not be assumed to affect the ball unless
# an explicit roof-open signal is supplied. This deliberately fails neutral.
_RETRACTABLE_OR_COVERED = {
    "Arizona Diamondbacks", "Houston Astros", "Miami Marlins",
    "Milwaukee Brewers", "Seattle Mariners", "Texas Rangers", "Toronto Blue Jays",
}


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _clip(p):
    return max(.001, min(.999, _num(p, .5)))


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _flag(name, default="1"):
    return str(os.getenv(name, default)).strip().lower() not in {"0", "false", "no", "off"}


def enabled():
    return _flag("V124_ENABLE_SHADOW", "1")


def flags():
    return {
        "platoon": _flag("V124_PLATOON", "1"),
        "statcast": _flag("V124_STATCAST", "1"),
        "bullpen_player": _flag("V124_BULLPEN_PLAYER", "1"),
        "lineup_player": _flag("V124_LINEUP_PLAYER", "1"),
        "starter_ip": _flag("V124_STARTER_IP", "1"),
        "weather_park": _flag("V124_WEATHER_PARK", "1"),
        "uncertainty": _flag("V124_UNCERTAINTY", "1"),
        "ensemble": _flag("V124_ENSEMBLE", "1"),
    }


def _ratio(x, baseline, lo=.78, hi=1.25):
    return max(lo, min(hi, _num(x, baseline)/max(1e-9, _num(baseline, 1.0))))


def _factor(x, lo=.94, hi=1.06):
    return max(lo, min(hi, _num(x, 1.0)))


def _first_stat(payload):
    try:
        stats = payload.get("stats") or []
        splits = (stats[0] if stats else {}).get("splits") or []
        return (splits[0] if splits else {}).get("stat") or {}
    except Exception:
        return {}


def _person(pid):
    if not pid:
        return {}
    key = str(pid)
    if key in _PERSON_CACHE:
        return _PERSON_CACHE[key]
    try:
        data = core.mlb(f"v1/people/{pid}") or {}
        people = data.get("people") or []
        p = people[0] if people else {}
        out = {
            "id": pid,
            "name": p.get("fullName"),
            "bat_side": ((p.get("batSide") or {}).get("code") or "").upper() or None,
            "pitch_hand": ((p.get("pitchHand") or {}).get("code") or "").upper() or None,
        }
    except Exception:
        out = {"id": pid, "bat_side": None, "pitch_hand": None}
    _PERSON_CACHE[key] = out
    return out


def _split_stats(pid, group, sit_code):
    if not pid or not sit_code:
        return {}
    key = (str(pid), str(group), str(sit_code), core.SEASON)
    if key in _SPLIT_CACHE:
        return _SPLIT_CACHE[key]
    try:
        payload = core.mlb(
            f"v1/people/{pid}/stats",
            {"stats": "season", "group": group, "season": core.SEASON, "sitCodes": sit_code},
        ) or {}
        out = _first_stat(payload)
    except Exception:
        out = {}
    _SPLIT_CACHE[key] = out
    return out


def _plate_appearances(stats):
    for k in ("plateAppearances", "battersFaced", "atBats"):
        if stats.get(k) is not None:
            return max(0.0, _num(stats.get(k)))
    return 0.0


def _lineup_players(result, side):
    return list((((result.get("ctx") or {}).get(f"{side}_lineup") or {}).get("players") or [])[:9])


def _starter(result, side):
    return ((result.get("ctx") or {}).get(f"{side}_starter") or {})


def _team_pitching(result, side):
    team_id = (result.get("ctx") or {}).get(f"{side}_id")
    try:
        return core.season_stats(team_id, "pitching") if team_id else {}
    except Exception:
        return {}


def _module_base(name, active=True):
    return {
        "name": name,
        "enabled": bool(active),
        "status": "DISABLED" if not active else "READY",
        "home_factor": 1.0,
        "away_factor": 1.0,
        "coverage": 0.0,
    }


def platoon_module(result, active=True):
    out = _module_base("platoon", active)
    if not active:
        return out
    lgops = _num(core.league_baselines().get("ops"), .710)
    details = {}
    factors = {}
    usable_total = 0
    possible_total = 0
    for offense, defense in (("home", "away"), ("away", "home")):
        opp = _starter(result, defense)
        hand = _person(opp.get("id")).get("pitch_hand")
        sit = "vr" if hand == "R" else "vl" if hand == "L" else None
        players = _lineup_players(result, offense)
        possible_total += len(players)
        pairs = []
        for i, player in enumerate(players):
            pid = player.get("id")
            overall = _num(player.get("ops"), lgops)
            split = _split_stats(pid, "hitting", sit) if sit else {}
            split_ops = _num(split.get("ops"), 0)
            pa = _plate_appearances(split)
            if not (.35 <= split_ops <= 1.45):
                continue
            shrink = min(1.0, pa/120.0)
            adj_ops = shrink*split_ops+(1-shrink)*overall
            pairs.append((adj_ops/max(.45, overall), _ORDER_WEIGHTS[min(i, 8)]))
        usable_total += len(pairs)
        if pairs:
            ratio = sum(v*w for v, w in pairs)/sum(w for _, w in pairs)
            f = _factor(1+.38*(ratio-1), .955, 1.045)
        else:
            f = 1.0
        factors[offense] = f
        details[offense] = {
            "opposing_pitcher_hand": hand,
            "split_code": sit,
            "usable_hitters": len(pairs),
            "lineup_hitters": len(players),
            "factor": f,
        }
    out.update({
        "home_factor": factors.get("home", 1.0), "away_factor": factors.get("away", 1.0),
        "coverage": usable_total/max(1, possible_total), "details": details,
        "status": "ACTIVE" if usable_total >= 6 else "LOW_COVERAGE",
    })
    return out


def lineup_player_module(result, active=True):
    out = _module_base("lineup_player", active)
    if not active:
        return out
    lgops = _num(core.league_baselines().get("ops"), .710)
    factors, details = {}, {}
    usable_total = possible_total = 0
    for side in ("home", "away"):
        players = _lineup_players(result, side)
        possible_total += len(players)
        values = []
        for i, p in enumerate(players):
            ops = p.get("ops")
            if ops is None:
                continue
            ratio = _ratio(ops, lgops, .55, 1.55)
            # Non-linear player value: elite/weak hitters are not fully erased by averaging.
            transformed = math.copysign(abs(ratio-1.0)**1.10, ratio-1.0)
            values.append((transformed, _ORDER_WEIGHTS[min(i, 8)]))
        usable_total += len(values)
        if values:
            signal = sum(v*w for v, w in values)/sum(w for _, w in values)
            f = _factor(1+.12*signal, .97, 1.03)
        else:
            f = 1.0
        factors[side] = f
        details[side] = {"usable_hitters": len(values), "lineup_hitters": len(players), "factor": f}
    out.update({
        "home_factor": factors.get("home", 1.0), "away_factor": factors.get("away", 1.0),
        "coverage": usable_total/max(1, possible_total), "details": details,
        "status": "ACTIVE" if usable_total >= 10 else "LOW_COVERAGE",
    })
    return out


def expected_starter_ip(starter):
    pid = (starter or {}).get("id")
    st = core.player_stats(pid, "pitching") if pid else {}
    ip = _num(st.get("inningsPitched"), _num((starter or {}).get("innings"), 0))
    starts = max(0.0, _num(st.get("gamesStarted"), 0))
    games = max(0.0, _num(st.get("gamesPitched"), starts))
    denom = starts if starts >= 2 else games if games >= 2 else 0
    avg = ip/denom if denom else 5.1
    era = _num((starter or {}).get("era"), 4.35)
    whip = _num((starter or {}).get("whip"), 1.32)
    skill = .60*_ratio(era, 4.35, .65, 1.45)+.40*_ratio(whip, 1.32, .70, 1.40)
    expected = avg-.45*(skill-1.0)
    sample = min(1.0, starts/12.0) if starts else min(1.0, ip/70.0)
    expected = sample*expected+(1-sample)*5.1
    return max(4.0, min(6.7, expected)), {"season_ip": ip, "starts": starts, "games": games, "sample": sample}


def _starter_quality(starter):
    lg = core.league_baselines()
    lgera, lgwhip = _num(lg.get("era"), 4.35), _num(lg.get("whip"), 1.32)
    era = _num((starter or {}).get("era"), lgera)
    whip = _num((starter or {}).get("whip"), lgwhip)
    k9 = _num((starter or {}).get("k9"), 8.6)
    bb9 = _num((starter or {}).get("bb9"), 3.2)
    hr9 = _num((starter or {}).get("hr9"), 1.15)
    return (
        .43*_ratio(era, lgera, .60, 1.55)
        + .20*_ratio(whip, lgwhip, .65, 1.45)
        + .14*_ratio(bb9, 3.2, .55, 1.65)
        + .13*_ratio(hr9, 1.15, .45, 1.80)
        + .10*_ratio(8.6, max(3.5, k9), .60, 1.55)
    )


def starter_ip_module(result, active=True):
    out = _module_base("starter_ip", active)
    if not active:
        return out
    lg = core.league_baselines()
    lgera = _num(lg.get("era"), 4.35)
    factors, details = {}, {}
    coverage = 0
    for offense, defense in (("home", "away"), ("away", "home")):
        starter = _starter(result, defense)
        team_stats = _team_pitching(result, defense)
        team_q = _ratio(team_stats.get("era"), lgera, .70, 1.40)
        starter_q = _starter_quality(starter)
        exp_ip, meta = expected_starter_ip(starter)
        target = (exp_ip/9.0)*starter_q+(1-exp_ip/9.0)*team_q
        legacy = .48*starter_q+.52*team_q
        f = _factor(target/max(.70, legacy), .96, 1.04)
        factors[offense] = f
        coverage += 1 if starter.get("id") else 0
        details[offense] = {"defense": defense, "expected_ip": exp_ip, "starter_quality": starter_q,
                            "team_pitching_quality": team_q, "legacy_mix": legacy, "target_mix": target,
                            "factor": f, **meta}
    out.update({
        "home_factor": factors.get("home", 1.0), "away_factor": factors.get("away", 1.0),
        "coverage": coverage/2.0, "details": details,
        "status": "ACTIVE" if coverage == 2 else "LOW_COVERAGE",
    })
    return out


def _reliever_quality(reliever):
    pid = (reliever or {}).get("id")
    st = core.player_stats(pid, "pitching") if pid else {}
    if not st:
        return None
    era = _num(st.get("era"), 4.35)
    whip = _num(st.get("whip"), 1.32)
    ip = _num(st.get("inningsPitched"), 0)
    sample = min(1.0, ip/35.0)
    raw = .62*_ratio(era, 4.35, .55, 1.70)+.38*_ratio(whip, 1.32, .60, 1.55)
    return sample*raw+(1-sample)*1.0


def bullpen_player_module(result, active=True):
    out = _module_base("bullpen_player", active)
    if not active:
        return out
    bp = ((result.get("features") or {}).get("bullpen") or {})
    factors, details = {}, {}
    usable = total = 0
    for offense, defense in (("home", "away"), ("away", "home")):
        state = bp.get(defense) or {}
        relievers = list(state.get("relievers") or [])
        total += len(relievers)
        vals = []
        for rel in relievers:
            q = _reliever_quality(rel)
            if q is None:
                continue
            usable += 1
            pitches = _num(rel.get("pitches_3d"), 0)
            days = _num(rel.get("days_used"), 0)
            fatigue = min(.18, max(0.0, (pitches-20)/180.0)+max(0.0, days-1)*.035)
            availability = 0.0 if pitches >= 45 or days >= 3 else 1.0
            # Better and fresher relievers carry more of the expected high-leverage innings.
            weight = max(.20, (1.35-.45*q)*(1-.55*fatigue)*(.35+.65*availability))
            vals.append((q+fatigue, weight))
        if vals:
            q = sum(v*w for v, w in vals)/sum(w for _, w in vals)
        else:
            q = 1.0
        starter = _starter(result, defense)
        exp_ip, _ = expected_starter_ip(starter)
        bullpen_share = max(.20, min(.60, (9-exp_ip)/9.0))
        # q>1 means a weaker/fatigued bullpen and therefore more expected opponent runs.
        f = _factor(1+.42*bullpen_share*(q-1.0), .955, 1.05)
        factors[offense] = f
        details[offense] = {
            "defense": defense, "relievers_seen": len(relievers), "usable_relievers": len(vals),
            "bullpen_quality": q, "expected_bullpen_share": bullpen_share,
            "coverage": _num(state.get("coverage"), 0), "factor": f,
        }
    out.update({
        "home_factor": factors.get("home", 1.0), "away_factor": factors.get("away", 1.0),
        "coverage": usable/max(1, total), "details": details,
        "status": "ACTIVE" if usable >= 4 else "LOW_COVERAGE",
    })
    return out


def _http_text(url, params=None, timeout=25):
    """Point-in-time-recordable text fetch using the same replay journal as core.http_json."""
    if params:
        url += ("&" if "?" in url else "?") + core.urllib.parse.urlencode(params, safe=",|[]")
    request_key = core._request_key(url, "GET", None)
    if core._HTTP_REPLAY is not None:
        calls = core._HTTP_REPLAY["index"].get(request_key) or []
        pos = core._HTTP_REPLAY["positions"].get(request_key, 0)
        if pos >= len(calls):
            raise RuntimeError(f"Replay source manquant pour {core._scrub_url(url)}")
        core._HTTP_REPLAY["positions"][request_key] = pos+1
        call = calls[pos]
        if call.get("error"):
            raise RuntimeError(str(call.get("error")))
        response = call.get("response")
        return response if isinstance(response, str) else str(response or "")
    req = core.urllib.request.Request(url, headers={"User-Agent": "MLB-Betting-Bot-V12.4", "Accept": "text/csv,*/*"})
    with core.urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
    if core._HTTP_RECORDING is not None:
        core._HTTP_RECORDING["payload"]["calls"].append({
            "request_key": request_key, "url": core._scrub_url(url), "method": "GET",
            "payload": None, "response": text, "recorded_at": core.datetime.now(timezone.utc).isoformat(),
        })
    return text


def _savant_rows(player_type, cutoff):
    key = (str(player_type), str(cutoff), core.SEASON)
    if key in _SAVANT_CACHE:
        return _SAVANT_CACHE[key]
    start = f"{core.SEASON}-03-01"
    params = {
        "all": "true", "type": "details", "player_type": player_type,
        "game_date_gt": start, "game_date_lt": cutoff,
        "group_by": "name-year", "hfGT": "R|", "hfSea": f"{core.SEASON}|",
        "min_pas": 0, "min_pitches": 0, "min_results": 0,
        "chk_stats_woba": "on", "chk_stats_xwoba": "on",
        "chk_stats_launch_speed": "on", "chk_stats_hardhit_percent": "on",
        "chk_stats_barrel_batted_rate": "on",
    }
    try:
        text = _http_text("https://baseballsavant.mlb.com/statcast_search/csv", params)
        rows = list(csv.DictReader(io.StringIO(text)))
        # A failed HTML response should never be mistaken for valid CSV data.
        if not rows or not any("xwoba" in str(k).lower() for k in (rows[0].keys() if rows else [])):
            rows = []
    except Exception:
        rows = []
    index = {}
    for row in rows:
        names = [row.get(k) for k in row if str(k).lower() in {"player_name", "name", "player"}]
        ids = [row.get(k) for k in row if str(k).lower() in {"player_id", "batter", "pitcher"}]
        for value in names:
            if value:
                index[("name", _norm(value))] = row
        for value in ids:
            if value and str(value).isdigit():
                index[("id", str(value))] = row
    _SAVANT_CACHE[key] = index
    return index


def _field(row, *names):
    for key, value in (row or {}).items():
        nk = str(key).lower().replace(" ", "_").replace("%", "_percent")
        if nk in names and value not in (None, "", "null", "--"):
            return _num(value, None)
    return None


def _savant_player(index, player):
    if not player:
        return None
    pid = player.get("id")
    if pid is not None and ("id", str(pid)) in index:
        return index[("id", str(pid))]
    name = player.get("name") or player.get("fullName")
    return index.get(("name", _norm(name))) if name else None


def statcast_module(result, active=True):
    out = _module_base("statcast", active)
    if not active:
        return out
    try:
        game_dt = core.parse_dt(((result.get("game") or {}).get("gameDate")))
        cutoff = (game_dt.date()-timedelta(days=1)).isoformat()
    except Exception:
        try:
            cutoff = (date.fromisoformat(core.TARGET_DATE)-timedelta(days=1)).isoformat()
        except Exception:
            out["status"] = "NO_CUTOFF"
            return out
    batters = _savant_rows("batter", cutoff)
    pitchers = _savant_rows("pitcher", cutoff)
    if not batters and not pitchers:
        out.update({"status": "UNAVAILABLE", "provider": "Baseball Savant official point-in-time CSV", "cutoff": cutoff})
        return out
    league_xwoba = _num(os.getenv("V124_LEAGUE_XWOBA", ".320"), .320)
    factors, details = {}, {}
    usable = possible = 0
    for offense, defense in (("home", "away"), ("away", "home")):
        vals = []
        players = _lineup_players(result, offense)
        possible += len(players)+1
        for i, player in enumerate(players):
            row = _savant_player(batters, player)
            if not row:
                continue
            xwoba = _field(row, "xwoba", "estimated_woba_using_speedangle")
            if xwoba is None or not (.20 <= xwoba <= .50):
                continue
            usable += 1
            vals.append((xwoba, _ORDER_WEIGHTS[min(i, 8)]))
        lineup_xwoba = sum(v*w for v, w in vals)/sum(w for _, w in vals) if vals else league_xwoba
        offense_factor = _factor(1+.28*(lineup_xwoba/league_xwoba-1), .965, 1.04)
        starter = _starter(result, defense)
        prow = _savant_player(pitchers, {"id": starter.get("id"), "name": starter.get("name")})
        pxwoba = _field(prow, "xwoba", "estimated_woba_using_speedangle") if prow else None
        pitcher_factor = 1.0
        if pxwoba is not None and .20 <= pxwoba <= .50:
            usable += 1
            exp_ip, _ = expected_starter_ip(starter)
            pitcher_factor = _factor(1+.22*(exp_ip/9.0)*(pxwoba/league_xwoba-1), .975, 1.03)
        factors[offense] = _factor(offense_factor*pitcher_factor, .95, 1.055)
        details[offense] = {
            "lineup_xwoba": lineup_xwoba if vals else None, "lineup_statcast_n": len(vals),
            "opposing_starter_xwoba": pxwoba, "offense_factor": offense_factor,
            "pitcher_factor": pitcher_factor, "factor": factors[offense],
        }
    out.update({
        "home_factor": factors.get("home", 1.0), "away_factor": factors.get("away", 1.0),
        "coverage": usable/max(1, possible), "details": details,
        "provider": "Baseball Savant official point-in-time CSV", "cutoff": cutoff,
        "status": "ACTIVE" if usable >= 6 else "LOW_COVERAGE",
    })
    return out


def weather_park_module(result, active=True):
    out = _module_base("weather_park", active)
    if not active:
        return out
    features = result.get("features") or {}
    weather = features.get("weather") or {}
    home = (result.get("ctx") or {}).get("home")
    park = _num(features.get("park_factor"), core.PARK.get(home, 1.0))
    if not weather.get("available"):
        out.update({"status": "UNAVAILABLE", "details": {"reason": weather.get("reason")}})
        return out
    roof_open = str(os.getenv("V124_ROOF_OPEN_TEAMS", "")).split(",")
    roof_open = {_norm(x) for x in roof_open if x.strip()}
    covered = home in _RETRACTABLE_OR_COVERED and _norm(home) not in roof_open
    if covered:
        out.update({
            "status": "ROOF_NEUTRAL", "coverage": 1.0,
            "details": {"home": home, "roof_policy": "outside weather neutral unless explicitly marked open",
                        "temperature_c": weather.get("temperature_c"), "wind_kph": weather.get("wind_kph"),
                        "wind_direction_deg": weather.get("wind_direction_deg")},
        })
        return out
    temp = _num(weather.get("temperature_c"), 20)
    humidity = _num(weather.get("humidity_pct"), 55)
    wind = max(0.0, _num(weather.get("wind_kph"), 0))
    # Park interaction: hitter parks amplify carry; pitcher parks damp it.
    park_sensitivity = max(.75, min(1.30, 1+2.2*(park-1.0)))
    temp_signal = max(-.025, min(.025, (temp-20.0)*.0014))*park_sensitivity
    humidity_signal = max(-.008, min(.008, (humidity-55.0)*.00018))*park_sensitivity
    # Without verified stadium orientation, wind direction is stored but only a small
    # magnitude term is applied. This avoids fabricating an outfield bearing.
    wind_signal = max(0.0, min(.012, (wind-8.0)*.00055))*max(.80, min(1.20, park_sensitivity))
    factor = _factor(1+temp_signal+humidity_signal+wind_signal, .965, 1.04)
    out.update({
        "home_factor": factor, "away_factor": factor, "coverage": 1.0,
        "status": "ACTIVE_PARTIAL_DIRECTION",
        "details": {
            "home": home, "park_factor": park, "park_sensitivity": park_sensitivity,
            "temperature_c": temp, "humidity_pct": humidity, "wind_kph": wind,
            "wind_direction_deg": weather.get("wind_direction_deg"),
            "temperature_signal": temp_signal, "humidity_signal": humidity_signal,
            "wind_magnitude_signal": wind_signal,
            "direction_policy": "direction recorded; no directional adjustment without verified park bearing",
        },
    })
    return out


def _exact_key(opt):
    point = opt.get("point")
    return (str(opt.get("market") or ""), _norm(opt.get("name")), None if point is None else round(_num(point), 4))


def _model_probability(result, opt, home_mu, away_mu):
    market = str(opt.get("market") or "").upper()
    name = str(opt.get("name") or "")
    point = opt.get("point")
    home = str((result.get("ctx") or {}).get("home") or "")
    if market == "ML":
        p_home = engine.prob_home_win(home_mu, away_mu)
        return (p_home if _norm(name) == _norm(home) else 1-p_home), 0.0
    if market == "RUNLINE":
        side = "home" if _norm(name) == _norm(home) else "away"
        win, push = engine.prob_cover_parts(home_mu, away_mu, side, _num(point),
                                            _num((result.get("features") or {}).get("run_dispersion"), 7.5),
                                            _num((result.get("features") or {}).get("run_environment_sigma"), .08))
        return _clip(win/max(1e-9, 1-push)), push
    if market == "TOTAL":
        side = str(name).lower()
        win, push = engine.prob_total_parts(home_mu, away_mu, side, _num(point),
                                            _num((result.get("features") or {}).get("run_dispersion"), 7.5),
                                            _num((result.get("features") or {}).get("run_environment_sigma"), .08))
        return _clip(win/max(1e-9, 1-push)), push
    return .5, 0.0


def price_variant(result, home_mu, away_mu, uncertainty=None):
    model = pro_model.load_model()
    phase = str(result.get("phase") or "EARLY").upper()
    out = []
    for opt in result.get("options") or []:
        p, push = _model_probability(result, opt, home_mu, away_mu)
        p_market = opt.get("p_market")
        w = max(0.0, min(.30, _num(opt.get("sharp_weight"), 0)))
        if p_market is not None:
            p = _clip((1-w)*p+w*_clip(p_market))
        q, _, qpush, source = pro_model.calibrate_triplet(opt.get("market"), p, 1-p, push, model, phase)
        if uncertainty is not None:
            trust = max(.55, min(1.0, 1-1.8*_num(uncertainty, 0)))
            q = _clip(.5+(q-.5)*trust)
        out.append({
            "market": opt.get("market"), "name": opt.get("name"), "point": opt.get("point"),
            "p_core": round(p, 6), "p_effective": round(q, 6),
            "p_win": round(q*(1-qpush), 6), "p_push": round(qpush, 6),
            "p_market": opt.get("p_market"), "calibration_source": source,
        })
    return out


def uncertainty_module(result, v115=None, statcast=None, active=True):
    out = _module_base("uncertainty", active)
    if not active:
        out["uncertainty"] = 0.0
        return out
    ctx = result.get("ctx") or {}
    comps = {}
    starters = [_starter(result, side) for side in ("home", "away")]
    starter_samples = [min(1.0, _num(s.get("innings"), 0)/80.0) for s in starters]
    comps["starter"] = .08*(1-sum(starter_samples)/max(1, len(starter_samples)))
    lineup_counts = [_num((ctx.get(f"{s}_lineup") or {}).get("count"), 0) for s in ("home", "away")]
    comps["lineup"] = .07*(1-min(1.0, sum(lineup_counts)/18.0))
    bp = ((result.get("features") or {}).get("bullpen") or {})
    bp_cov = [_num((bp.get(s) or {}).get("coverage"), 0) for s in ("home", "away")]
    comps["bullpen"] = .045*(1-sum(bp_cov)/2.0)
    sc_cov = _num((statcast or {}).get("coverage"), 0)
    comps["statcast"] = .025*(1-sc_cov)
    sharp_disps = [_num(o.get("sharp_dispersion"), 0) for o in result.get("options") or [] if o.get("sharp_dispersion") is not None]
    comps["market"] = min(.035, .55*(sum(sharp_disps)/len(sharp_disps))) if sharp_disps else .018
    vmap = {_exact_key(o): o for o in ((v115 or {}).get("options") or [])}
    gaps = []
    for opt in result.get("options") or []:
        other = vmap.get(_exact_key(opt))
        if other:
            gaps.append(abs(_num(opt.get("p_effective"), .5)-_num(other.get("p_effective"), .5)))
    comps["cross_model"] = min(.04, .35*(sum(gaps)/len(gaps))) if gaps else .012
    total = math.sqrt(sum(v*v for v in comps.values()))
    total = max(.012, min(.12, total))
    out.update({"status": "ACTIVE", "coverage": 1.0, "uncertainty": total, "components": comps,
                "v11_v12_common": len(gaps), "mean_v11_v12_gap": sum(gaps)/len(gaps) if gaps else None})
    return out


def _apply_modules(base_h, base_a, modules, names):
    hf = af = 1.0
    for name in names:
        mod = modules.get(name) or {}
        hf *= _num(mod.get("home_factor"), 1.0)
        af *= _num(mod.get("away_factor"), 1.0)
    # Prevent correlated signals from moving a team total excessively before evidence exists.
    hf = max(.88, min(1.12, hf))
    af = max(.88, min(1.12, af))
    return max(1.6, min(8.0, base_h*hf)), max(1.6, min(8.0, base_a*af)), hf, af


def _baseline_variant(result):
    return {
        "home_mu": _num(result.get("hmu"), _num((result.get("features") or {}).get("home_mu"), 4.4)),
        "away_mu": _num(result.get("amu"), _num((result.get("features") or {}).get("away_mu"), 4.2)),
        "options": [{
            "market": o.get("market"), "name": o.get("name"), "point": o.get("point"),
            "p_effective": o.get("p_effective"), "p_win": o.get("p_win"), "p_push": o.get("p_push"),
            "p_market": o.get("p_market"),
        } for o in result.get("options") or []],
    }


def _ensemble_options(result, core_options, v115, uncertainty):
    v11 = {_exact_key(o): o for o in ((v115 or {}).get("options") or [])}
    official = {_exact_key(o): o for o in result.get("options") or []}
    coremap = {_exact_key(o): o for o in core_options}
    out = []
    for key, c in coremap.items():
        candidates = [("v124_core", _num(c.get("p_effective"), .5), .45)]
        o = official.get(key)
        if o:
            candidates.append(("v12", _num(o.get("p_effective"), .5), .25))
        s = v11.get(key)
        if s:
            candidates.append(("v11", _num(s.get("p_effective"), .5), .15))
        if o and o.get("p_market") is not None:
            candidates.append(("sharp", _num(o.get("p_market"), .5), .15))
        sw = sum(w for _, _, w in candidates)
        p = sum(p*w for _, p, w in candidates)/max(1e-9, sw)
        trust = max(.58, min(1.0, 1-1.5*_num(uncertainty, 0)))
        p = _clip(.5+(p-.5)*trust)
        out.append({
            "market": c.get("market"), "name": c.get("name"), "point": c.get("point"),
            "p_effective": round(p, 6), "p_win": round(p*(1-_num(c.get("p_push"), 0)), 6),
            "p_push": c.get("p_push"), "p_market": c.get("p_market"),
            "components": [{"source": n, "p": round(v, 6), "weight": w} for n, v, w in candidates],
        })
    return out


def analyze(result, v115=None):
    """Build the eight-module V12.4 research challenger without changing V12 selection."""
    f = flags()
    base_h = _num(result.get("hmu"), _num((result.get("features") or {}).get("home_mu"), 4.4))
    base_a = _num(result.get("amu"), _num((result.get("features") or {}).get("away_mu"), 4.2))
    modules = {}
    modules["platoon"] = platoon_module(result, f["platoon"])
    modules["statcast"] = statcast_module(result, f["statcast"])
    modules["bullpen_player"] = bullpen_player_module(result, f["bullpen_player"])
    modules["lineup_player"] = lineup_player_module(result, f["lineup_player"])
    modules["starter_ip"] = starter_ip_module(result, f["starter_ip"])
    modules["weather_park"] = weather_park_module(result, f["weather_park"])
    modules["uncertainty"] = uncertainty_module(result, v115, modules["statcast"], f["uncertainty"])

    variants = {"baseline_v1232": _baseline_variant(result)}
    factor_names = ("platoon", "statcast", "bullpen_player", "lineup_player", "starter_ip", "weather_park")
    for name in factor_names:
        h, a, hf, af = _apply_modules(base_h, base_a, modules, [name])
        variants[f"only_{name}"] = {"home_mu": h, "away_mu": a, "home_factor": hf, "away_factor": af,
                                       "options": price_variant(result, h, a, None)}
    all_names = [name for name in factor_names if f.get(name)]
    h, a, hf, af = _apply_modules(base_h, base_a, modules, all_names)
    unc = _num(modules["uncertainty"].get("uncertainty"), 0) if f["uncertainty"] else None
    all_options = price_variant(result, h, a, unc)
    variants["all_core"] = {"home_mu": h, "away_mu": a, "home_factor": hf, "away_factor": af,
                            "uncertainty": unc, "options": all_options}
    modules["ensemble"] = _module_base("ensemble", f["ensemble"])
    if f["ensemble"]:
        ens = _ensemble_options(result, all_options, v115, _num(unc, 0))
        variants["ensemble"] = {"home_mu": h, "away_mu": a, "uncertainty": unc, "options": ens}
        modules["ensemble"].update({"status": "ACTIVE", "coverage": 1.0, "sources": ["v124_core", "v12", "v11", "sharp"]})
    return {
        "schema": SCHEMA, "version": VERSION, "enabled": True, "research_only": True,
        "affects_v12_selection": False, "base_home_mu": base_h, "base_away_mu": base_a,
        "modules": modules, "variants": variants,
        "implementation": implementation_report(modules),
    }


def implementation_report(modules=None):
    modules = modules or {}
    return {
        "1_platoon_handedness": {"status": "ADDED", "runtime": (modules.get("platoon") or {}).get("status"),
                                  "note": "player-level lineup splits vs opposing starter hand; sample shrinkage; fail-neutral"},
        "2_statcast_expected": {"status": "ADDED", "runtime": (modules.get("statcast") or {}).get("status"),
                                 "note": "official Baseball Savant point-in-time xwOBA provider; lineup + opposing starter; fail-neutral"},
        "3_bullpen_player_level": {"status": "ADDED", "runtime": (modules.get("bullpen_player") or {}).get("status"),
                                   "note": "reliever ERA/WHIP quality, 3-day pitch load, consecutive usage and availability"},
        "4_lineup_player_level": {"status": "ADDED", "runtime": (modules.get("lineup_player") or {}).get("status"),
                                  "note": "non-linear player value with batting-order exposure instead of a single average only"},
        "5_starter_expected_ip": {"status": "ADDED", "runtime": (modules.get("starter_ip") or {}).get("status"),
                                  "note": "expected starter innings from season workload/starts and skill; rebalances starter/team pitching mix"},
        "6_weather_park_interaction": {"status": "PARTIAL", "runtime": (modules.get("weather_park") or {}).get("status"),
                                       "note": "temperature/humidity/wind magnitude x park and roof-neutral safety added; wind direction stored but no directional run adjustment without verified park bearing"},
        "7_uncertainty_decomposition": {"status": "ADDED", "runtime": (modules.get("uncertainty") or {}).get("status"),
                                        "note": "starter + lineup + bullpen + Statcast + sharp dispersion + V11/V12 disagreement"},
        "8_model_ensemble": {"status": "ADDED_RESEARCH_ONLY", "runtime": (modules.get("ensemble") or {}).get("status"),
                             "note": "V12.4 core + V12 + V11.5 + sharp; uncertainty shrink; never selects official bets"},
    }


def _settled_result_map(row):
    return {_exact_key(o): o.get("result") for o in row.get("options") or [] if o.get("result") in {"WIN", "LOSS", "PUSH"}}


def metrics(rows):
    agg = {}
    games = 0
    for row in rows or []:
        shadow = row.get("shadow_v124") or {}
        if not shadow.get("enabled") or shadow.get("status") == "ERROR":
            continue
        results = _settled_result_map(row)
        if not results:
            continue
        games += 1
        for variant, payload in (shadow.get("variants") or {}).items():
            a = agg.setdefault(variant, {"n": 0, "wins": 0, "brier_sum": 0.0, "logloss_sum": 0.0,
                                         "gt55_n": 0, "gt55_wins": 0})
            for opt in payload.get("options") or []:
                outcome = results.get(_exact_key(opt))
                if outcome not in {"WIN", "LOSS"}:
                    continue
                y = 1 if outcome == "WIN" else 0
                p = _clip(opt.get("p_effective"))
                a["n"] += 1
                a["wins"] += y
                a["brier_sum"] += (p-y)**2
                a["logloss_sum"] += -(y*math.log(p)+(1-y)*math.log(1-p))
                if p > .55:
                    a["gt55_n"] += 1
                    a["gt55_wins"] += y
    variants = {}
    for name, a in agg.items():
        n = a["n"]
        variants[name] = {
            "n": n, "accuracy": a["wins"]/n if n else None,
            "brier": a["brier_sum"]/n if n else None,
            "logloss": a["logloss_sum"]/n if n else None,
            "gt55_n": a["gt55_n"],
            "gt55_hit_rate": a["gt55_wins"]/a["gt55_n"] if a["gt55_n"] else None,
        }
    return {
        "schema": "v12-4-shadow-metrics-v1", "version": VERSION,
        "settled_games": games, "variants": variants,
        "activation": {"affects_v12_selection": False, "status": "RESEARCH_ONLY",
                       "minimum_settled_games_before_consideration": 75},
        "implementation": implementation_report(),
    }
