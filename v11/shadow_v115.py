from __future__ import annotations

import math
import os
from collections import Counter
from datetime import date, timedelta, timezone

from . import core

VERSION = "11.5-standalone-all-markets-v3-shadow"
SOURCE_COMMIT = "34b35283d043c6ec9a004013945a23a7da356a77"
RUN_DISPERSION = 7.5
MAX_RUNS_MATRIX = 22
SHARP_WEIGHT_1 = 0.12
SHARP_WEIGHT_2 = 0.20
SHARP_WEIGHT_3PLUS = 0.25
MAX_SHARP_AGE_MIN = 90.0
SHARP_DISAGREEMENT_SCALE = 0.10
MAX_OPERATIONAL_RUN_ADJ = 0.05
DEFAULT_THRESHOLD = 0.55
DEFAULT_STRONG_GAP = 0.08

_PREV_CACHE = {}
_BOX_CACHE = {}


def enabled():
    return str(os.getenv("V1232_ENABLE_V115_SHADOW", "1")).strip().lower() not in {"0", "false", "no", "off"}


def _nb_pmf(mu, k, dispersion=None):
    r = max(.5, float(dispersion or RUN_DISPERSION))
    p = r/(r+max(.01, mu))
    return math.exp(math.lgamma(k+r)-math.lgamma(r)-math.lgamma(k+1)+r*math.log(p)+k*math.log1p(-p))


def score_matrix(home_mu, away_mu, max_runs=None):
    mx = int(max_runs or MAX_RUNS_MATRIX)
    hp = [_nb_pmf(home_mu, k) for k in range(mx+1)]
    ap = [_nb_pmf(away_mu, k) for k in range(mx+1)]
    hs, aps = sum(hp), sum(ap)
    return [x/hs for x in hp], [x/aps for x in ap]


def _home_extra_win(home_mu, away_mu):
    share = home_mu/max(.01, home_mu+away_mu)
    return max(.46, min(.59, .70*share+.30*.52))


def prob_home_win(home_mu, away_mu):
    hp, ap = score_matrix(home_mu, away_mu)
    win = tie = 0.0
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            if h > a:
                win += ph*pa
            elif h == a:
                tie += ph*pa
    return core.clamp(win+tie*_home_extra_win(home_mu, away_mu))


def prob_cover_parts(home_mu, away_mu, side, point):
    hp, ap = score_matrix(home_mu, away_mu)
    win = push = 0.0
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            margin = (h-a+point) if side == "home" else (a-h+point)
            if margin > 1e-9:
                win += ph*pa
            elif abs(margin) <= 1e-9:
                push += ph*pa
    return max(0.0, min(1.0, win)), max(0.0, min(1.0, push))


def prob_total_parts(home_mu, away_mu, side, point):
    hp, ap = score_matrix(home_mu, away_mu)
    win = push = 0.0
    for h, ph in enumerate(hp):
        for a, pa in enumerate(ap):
            d = h+a-point
            if abs(d) <= 1e-9:
                push += ph*pa
            elif side == "over" and d > 0:
                win += ph*pa
            elif side == "under" and d < 0:
                win += ph*pa
    return max(0.0, min(1.0, win)), max(0.0, min(1.0, push))


def _lineup(game_pk):
    try:
        box = core.mlb(f"v1/game/{game_pk}/boxscore") or {}
    except Exception:
        return {"home": {"count": 0}, "away": {"count": 0}}
    out = {}
    weights = [1.04, 1.05, 1.08, 1.10, 1.06, 1.00, .96, .93, .90]
    for side in ("home", "away"):
        team = (box.get("teams") or {}).get(side) or {}
        hitters = []
        for player in (team.get("players") or {}).values():
            bo = player.get("battingOrder")
            if bo is None:
                continue
            pid = (player.get("person") or {}).get("id")
            stats = core.player_stats(pid, "hitting") if pid else {}
            ops = core.num(stats.get("ops"), 0)
            hitters.append({
                "id": pid,
                "name": (player.get("person") or {}).get("fullName"),
                "batting_order": bo,
                "ops": ops if .3 <= ops <= 1.5 else None,
            })
        hitters.sort(key=lambda x: int(core.num(x.get("batting_order"), 999)))
        weighted = []
        for i, x in enumerate(hitters[:9]):
            if x.get("ops") is not None:
                weighted.append((x["ops"], weights[min(i, 8)]))
        wops = sum(v*w for v, w in weighted)/sum(w for _, w in weighted) if len(weighted) >= 5 else None
        out[side] = {"count": len(hitters), "players": hitters, "weighted_ops": wops}
    return out


def _starter(game, side, league_era=4.35, league_whip=1.32):
    pp = (((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {})
    pid = pp.get("id")
    stats = core.player_stats(pid, "pitching") if pid else {}
    ip = core.num(stats.get("inningsPitched"), 0)
    weight = max(0.0, min(1.0, ip/70.0))
    era = weight*core.num(stats.get("era"), league_era)+(1-weight)*league_era
    whip = weight*core.num(stats.get("whip"), league_whip)+(1-weight)*league_whip
    return {
        "id": pid, "name": pp.get("fullName"), "era": era, "whip": whip, "innings": ip,
        "k9": core.num(stats.get("strikeoutsPer9Inn"), None) if stats.get("strikeoutsPer9Inn") is not None else None,
        "bb9": core.num(stats.get("walksPer9Inn"), None) if stats.get("walksPer9Inn") is not None else None,
        "hr9": core.num(stats.get("homeRunsPer9"), None) if stats.get("homeRunsPer9") is not None else None,
        "sample_weight": weight,
    }


def _previous_game(team_id, target_date):
    key = (str(team_id), str(target_date))
    if key in _PREV_CACHE:
        return _PREV_CACHE[key]
    try:
        d = date.fromisoformat(str(target_date))
    except Exception:
        _PREV_CACHE[key] = None
        return None
    for back in range(1, 5):
        day = (d-timedelta(days=back)).isoformat()
        try:
            games = core.mlb_schedule(day, team_id=team_id, hydrate="linescore")
        except Exception:
            continue
        finals = []
        for game in games:
            status = game.get("status") or {}
            if str(status.get("abstractGameState") or "").lower() == "final" or str(status.get("codedGameState") or "").upper() == "F":
                finals.append(game)
        if finals:
            game = finals[-1]
            teams = game.get("teams") or {}
            home_name = ((teams.get("home") or {}).get("team") or {}).get("name")
            innings = int(core.num((game.get("linescore") or {}).get("currentInning"), 9))
            out = {
                "game_pk": game.get("gamePk"), "days_back": back, "venue_home_team": home_name,
                "extra_innings": innings > 9, "doubleheader": str(game.get("doubleHeader") or "N") != "N",
            }
            _PREV_CACHE[key] = out
            return out
    _PREV_CACHE[key] = None
    return None


def _bullpen_usage(team_id, prev):
    if not prev or not prev.get("game_pk"):
        return {"relief_pitches": 0, "heavy_relievers": 0, "relievers_used": 0}
    gid = str(prev["game_pk"])
    if gid not in _BOX_CACHE:
        try:
            _BOX_CACHE[gid] = core.mlb(f"v1/game/{gid}/boxscore") or {}
        except Exception:
            _BOX_CACHE[gid] = {}
    box = _BOX_CACHE[gid]
    team = None
    for side in ("home", "away"):
        candidate = (box.get("teams") or {}).get(side) or {}
        if str((candidate.get("team") or {}).get("id") or "") == str(team_id):
            team = candidate
            break
    if not team:
        return {"relief_pitches": 0, "heavy_relievers": 0, "relievers_used": 0}
    ids = list(team.get("pitchers") or [])
    relievers = ids[1:] if len(ids) > 1 else []
    players = team.get("players") or {}
    counts = []
    for pid in relievers:
        stats = (((players.get(f"ID{pid}") or {}).get("stats") or {}).get("pitching") or {})
        counts.append(int(core.num(stats.get("pitchesThrown"), 0)))
    return {"relief_pitches": sum(counts), "heavy_relievers": sum(x >= 20 for x in counts), "relievers_used": len(counts)}


def _distance_km(a, b):
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742*math.asin(min(1, math.sqrt(h)))


def _operational(game, ctx):
    current = core.COORD.get(ctx.get("home"))
    out = {"current_doubleheader": str(game.get("doubleHeader") or "N") != "N"}
    for side in ("home", "away"):
        tid = ctx.get(f"{side}_id")
        prev = _previous_game(tid, core.TARGET_DATE)
        prev_coord = core.COORD.get(prev.get("venue_home_team")) if prev else None
        dist = _distance_km(prev_coord, current)
        bull = _bullpen_usage(tid, prev)
        out[side] = {
            "rest_days": max(0, int(prev.get("days_back", 1))-1) if prev else None,
            "travel_km": round(dist, 1) if dist is not None else None,
            "timezone_shift_hours_approx": round((current[1]-prev_coord[1])/15, 2) if current and prev_coord else None,
            "previous_extra_innings": bool(prev.get("extra_innings")) if prev else None,
            "previous_doubleheader": bool(prev.get("doubleheader")) if prev else None,
            "bullpen_previous_game": bull,
        }
    return out


def _project_runs(game):
    teams = game.get("teams") or {}
    home = ((teams.get("home") or {}).get("team") or {})
    away = ((teams.get("away") or {}).get("team") or {})
    hid, aid = home.get("id"), away.get("id")
    hn, an = home.get("name"), away.get("name")
    lg = core.league_baselines()
    rpg, lgops = core.num(lg.get("rpg"), 4.45), core.num(lg.get("ops"), .710)
    lgera, lgwhip = core.num(lg.get("era"), 4.35), core.num(lg.get("whip"), 1.32)
    hh, ah = core.season_stats(hid, "hitting"), core.season_stats(aid, "hitting")
    hp, ap = core.season_stats(hid, "pitching"), core.season_stats(aid, "pitching")
    h_ops, a_ops = core.num(hh.get("ops"), lgops), core.num(ah.get("ops"), lgops)
    h_rpg, a_rpg = core.num(hh.get("runsPerGame"), rpg), core.num(ah.get("runsPerGame"), rpg)
    h_era, a_era = core.num(hp.get("era"), lgera), core.num(ap.get("era"), lgera)
    hs, away_starter = _starter(game, "home", lgera, lgwhip), _starter(game, "away", lgera, lgwhip)
    lineups = _lineup(game.get("gamePk"))
    h_lu = core.num(lineups["home"].get("weighted_ops"), h_ops)
    a_lu = core.num(lineups["away"].get("weighted_ops"), a_ops)

    def ratio(x, baseline, lo=.75, hi=1.28):
        return max(lo, min(hi, x/max(1e-9, baseline)))

    h_off = .42*ratio(h_rpg, rpg)+.33*ratio(h_ops, lgops)+.25*ratio(h_lu, lgops)
    a_off = .42*ratio(a_rpg, rpg)+.33*ratio(a_ops, lgops)+.25*ratio(a_lu, lgops)
    h_sp_quality = .68*ratio(away_starter.get("era", lgera), lgera)+.32*ratio(away_starter.get("whip", lgwhip), lgwhip)
    a_sp_quality = .68*ratio(hs.get("era", lgera), lgera)+.32*ratio(hs.get("whip", lgwhip), lgwhip)
    h_opp = .52*ratio(a_era, lgera)+.48*h_sp_quality
    a_opp = .52*ratio(h_era, lgera)+.48*a_sp_quality
    park = core.PARK.get(hn, 1.0)
    home_mu = rpg*h_off*h_opp*park*1.025
    away_mu = rpg*a_off*a_opp*park*.975
    ctx = {
        "home": hn, "away": an, "home_id": hid, "away_id": aid,
        "home_sp": hs.get("name"), "away_sp": away_starter.get("name"),
        "home_lineup": lineups["home"], "away_lineup": lineups["away"],
        "home_starter": hs, "away_starter": away_starter,
    }
    oper = _operational(game, ctx)

    def fatigue(side):
        x = oper.get(side) or {}
        adj = 0.0
        dist = core.num(x.get("travel_km"), 0)
        tz = abs(core.num(x.get("timezone_shift_hours_approx"), 0))
        if dist >= 1500: adj -= .012
        if dist >= 3000: adj -= .008
        if tz >= 2: adj -= .008
        if x.get("previous_extra_innings"): adj -= .010
        if x.get("previous_doubleheader"): adj -= .008
        if x.get("rest_days") is not None and x.get("rest_days") >= 1: adj += .006
        return adj

    def bullpen_attack(opponent_side):
        b = ((oper.get(opponent_side) or {}).get("bullpen_previous_game") or {})
        return min(.035, .00022*core.num(b.get("relief_pitches"), 0)+.006*core.num(b.get("heavy_relievers"), 0))

    hadj = max(-MAX_OPERATIONAL_RUN_ADJ, min(MAX_OPERATIONAL_RUN_ADJ, fatigue("home")+bullpen_attack("away")))
    aadj = max(-MAX_OPERATIONAL_RUN_ADJ, min(MAX_OPERATIONAL_RUN_ADJ, fatigue("away")+bullpen_attack("home")))
    if oper.get("current_doubleheader"):
        hadj -= .004
        aadj -= .004
    home_mu = max(1.8, min(7.5, home_mu*(1+hadj)))
    away_mu = max(1.8, min(7.5, away_mu*(1+aadj)))
    return home_mu, away_mu, ctx


def _age_minutes(book, as_of):
    stamp = book.get("last_update") or book.get("lastUpdate")
    if not stamp:
        return 0.0
    try:
        dt = core.parse_dt(stamp)
        ref = core.parse_dt(as_of) if isinstance(as_of, str) else as_of
        ref = ref or core.datetime.now(timezone.utc)
        return max(0.0, (ref-dt).total_seconds()/60.0)
    except Exception:
        return 0.0


def sharp_consensus(event, market, name, point=None, as_of=None):
    key = {"ML": "h2h", "RUNLINE": "spreads", "TOTAL": "totals"}[market]
    vals, books, ages = [], [], []
    for book in event.get("bookmakers") or []:
        if book.get("key") not in core.SHARP_BOOKS:
            continue
        age = _age_minutes(book, as_of)
        if age > MAX_SHARP_AGE_MIN:
            continue
        featured = next((x for x in book.get("markets") or [] if x.get("key") == key), None)
        if not featured:
            continue
        relevant = []
        for outcome in featured.get("outcomes") or []:
            if point is not None:
                op = core.num(outcome.get("point"), 999)
                if market == "RUNLINE":
                    if abs(abs(op)-abs(core.num(point))) > 1e-6:
                        continue
                elif abs(op-core.num(point)) > 1e-6:
                    continue
            if core.num(outcome.get("price"), 0) > 1:
                relevant.append(outcome)
        if len(relevant) < 2:
            continue
        target = next((o for o in relevant if core.norm_name(o.get("name")) == core.norm_name(name)
                       and (point is None or market != "RUNLINE" or abs(core.num(o.get("point"))-core.num(point)) < 1e-6)), None)
        if target is None:
            continue
        inv = [1/core.num(o.get("price")) for o in relevant]
        total = sum(inv)
        if total <= 0:
            continue
        p = (1/core.num(target.get("price")))/total
        freshness = max(.25, 1-age/max(1.0, MAX_SHARP_AGE_MIN)*.75)
        vals.append((p, freshness))
        books.append(book.get("key"))
        ages.append(age)
    if not vals:
        return {"p": None, "n": 0, "books": [], "dispersion": None, "max_age_min": None, "robustness": 0.0}
    wsum = sum(w for _, w in vals)
    p = sum(v*w for v, w in vals)/wsum
    variance = sum(w*(v-p)**2 for v, w in vals)/wsum if wsum else 0.0
    dispersion = math.sqrt(max(0.0, variance))
    robustness = max(.35, min(1.0, 1-dispersion/max(.001, SHARP_DISAGREEMENT_SCALE)))
    return {"p": p, "n": len(vals), "books": books, "dispersion": dispersion,
            "max_age_min": max(ages) if ages else None, "robustness": robustness}


def _blend(structural, sharp):
    n, sp = int(sharp.get("n") or 0), sharp.get("p")
    if sp is None or n <= 0:
        return structural, 0.0
    base = SHARP_WEIGHT_1 if n == 1 else SHARP_WEIGHT_2 if n == 2 else SHARP_WEIGHT_3PLUS
    weight = base*max(.35, min(1.0, core.num(sharp.get("robustness"), 1.0)))
    return core.clamp((1-weight)*structural+weight*core.clamp(sp)), weight


def _quality(phase, refs, lineup_count, starter_ok):
    q = .50+min(refs, 4)*.06+(.11 if phase == "FINAL" else .055 if phase == "LATE" else 0)
    if lineup_count >= 16: q += .08
    if starter_ok: q += .07
    return max(.35, min(.95, q))


def _effective(p, phase, quality):
    trust = (.62 if phase == "EARLY" else .75 if phase == "LATE" else .88)*(.74+.26*quality)
    return core.clamp(.5+(p-.5)*trust)


def _confidence(p, quality, refs):
    return max(0.0, min(10.0, 3.0+abs(p-.5)*16+quality*2+min(refs, 4)*.35))


def _most_common_spread(event, home_name):
    vals = []
    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != "spreads":
                continue
            for outcome in market.get("outcomes") or []:
                if core.norm_name(outcome.get("name")) == core.norm_name(home_name) and outcome.get("point") is not None:
                    vals.append(round(core.num(outcome.get("point")), 1))
    return Counter(vals).most_common(1)[0][0] if vals else -1.5


def _most_common_total(event):
    vals = []
    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != "totals":
                continue
            for outcome in market.get("outcomes") or []:
                if outcome.get("point") is not None:
                    vals.append(round(core.num(outcome.get("point")), 1))
    return Counter(vals).most_common(1)[0][0] if vals else None


def analyze(game, event, as_of=None):
    if not enabled():
        return {"enabled": False, "version": VERSION, "source_commit": SOURCE_COMMIT, "options": []}
    hmu, amu, ctx = _project_runs(game)
    phase = core.phase_for_game(game, as_of=as_of)
    structural_home = prob_home_win(hmu, amu)
    sharp_home = sharp_consensus(event, "ML", ctx["home"], as_of=as_of)
    lineup_count = int(core.num(ctx["home_lineup"].get("count"))+core.num(ctx["away_lineup"].get("count")))
    starter_ok = bool(ctx.get("home_sp") and ctx.get("away_sp"))
    options = []

    def add(market_name, name, point, p_win, p_push=0.0):
        nonpush = max(1e-9, 1-p_push)
        struct_cond = core.clamp(p_win/nonpush)
        sharp = sharp_consensus(event, market_name, name, point, as_of=as_of)
        quality = _quality(phase, sharp.get("n", 0), lineup_count, starter_ok)
        p_model, sharp_weight = _blend(struct_cond, sharp)
        p_effective = _effective(p_model, phase, quality)
        options.append({
            "market": market_name, "name": name, "point": point,
            "p_structural": round(struct_cond, 6), "p_model": round(p_model, 6),
            "p_effective": round(p_effective, 6), "p_win": round(p_effective*nonpush, 6),
            "p_push": round(p_push, 6), "p_market": round(sharp["p"], 6) if sharp.get("p") is not None else None,
            "refs": sharp.get("n", 0), "sharp_books": sharp.get("books", []),
            "sharp_weight": round(sharp_weight, 6), "quality": round(quality, 4),
            "confidence": round(_confidence(p_effective, quality, sharp.get("n", 0)), 3),
            "result": None, "brier": None, "logloss": None,
        })

    add("ML", ctx["home"], None, structural_home)
    add("ML", ctx["away"], None, 1-structural_home)
    home_point = _most_common_spread(event, ctx["home"])
    away_point = -home_point
    hw, hp = prob_cover_parts(hmu, amu, "home", home_point)
    aw, ap = prob_cover_parts(hmu, amu, "away", away_point)
    add("RUNLINE", ctx["home"], home_point, hw, hp)
    add("RUNLINE", ctx["away"], away_point, aw, ap)
    total = _most_common_total(event)
    if total is not None:
        ow, op = prob_total_parts(hmu, amu, "over", total)
        uw, up = prob_total_parts(hmu, amu, "under", total)
        add("TOTAL", "Over", total, ow, op)
        add("TOTAL", "Under", total, uw, up)
    home_ml = next(o for o in options if o["market"] == "ML" and core.norm_name(o["name"]) == core.norm_name(ctx["home"]))
    return {
        "enabled": True, "version": VERSION, "source_commit": SOURCE_COMMIT, "status": "OK",
        "phase": phase, "home": ctx["home"], "away": ctx["away"],
        "projected_home_runs": round(hmu, 4), "projected_away_runs": round(amu, 4),
        "p_home": home_ml["p_effective"], "options": options,
    }


def option_key(option):
    point = option.get("point")
    point = None if point is None else round(core.num(point), 3)
    return (str(option.get("market") or "").upper(), core.norm_name(option.get("name")), point)


def compare(v12_result, shadow, threshold=DEFAULT_THRESHOLD, strong_gap=DEFAULT_STRONG_GAP):
    v11 = {option_key(o): o for o in (shadow or {}).get("options") or []}
    pairs = []
    for v12 in v12_result.get("options") or []:
        old = v11.get(option_key(v12))
        if old is None:
            continue
        p12, p11 = core.num(v12.get("p_effective"), .5), core.num(old.get("p_effective"), .5)
        pairs.append({
            "market": v12.get("market"), "name": v12.get("name"), "point": v12.get("point"),
            "v12_p_effective": round(p12, 6), "v11_p_effective": round(p11, 6),
            "delta_v12_minus_v11": round(p12-p11, 6),
            "consensus_gt55": bool(p12 > threshold and p11 > threshold),
            "v12_only_gt55": bool(p12 > threshold and p11 <= threshold),
            "v11_only_gt55": bool(p11 > threshold and p12 <= threshold),
            "strong_disagreement": bool(abs(p12-p11) >= strong_gap),
        })
    return {
        "threshold": threshold, "strong_gap": strong_gap, "exact_common_options": len(pairs),
        "consensus_gt55": sum(x["consensus_gt55"] for x in pairs),
        "v12_only_gt55": sum(x["v12_only_gt55"] for x in pairs),
        "v11_only_gt55": sum(x["v11_only_gt55"] for x in pairs),
        "strong_disagreement": sum(x["strong_disagreement"] for x in pairs),
        "pairs": pairs,
    }


def _summary(rows):
    wins = sum(x.get("result") == "WIN" for x in rows)
    losses = sum(x.get("result") == "LOSS" for x in rows)
    pushes = sum(x.get("result") == "PUSH" for x in rows)
    return {"n": len(rows), "wins": wins, "losses": losses, "pushes": pushes,
            "hit_rate_ex_push": wins/(wins+losses) if wins+losses else None}


def metrics(rows, threshold=DEFAULT_THRESHOLD, strong_gap=DEFAULT_STRONG_GAP):
    latest = {}
    for row in rows:
        shadow = row.get("shadow_v115") or {}
        if row.get("result_status") != "FINAL" or not row.get("game_pk") or not shadow.get("enabled"):
            continue
        gid, rank = str(row.get("game_pk")), str(row.get("analyzed_at") or "")
        if gid not in latest or rank > latest[gid][0]:
            latest[gid] = (rank, row)
    games = [x[1] for x in latest.values()]
    buckets = {"consensus_gt55": [], "v12_only_gt55": [], "v11_only_gt55": [], "strong_disagreement": []}
    market_buckets = {m: {k: [] for k in buckets} for m in ("ML", "RUNLINE", "TOTAL")}
    for row in games:
        v12_map = {option_key(o): o for o in row.get("options") or []}
        v11_map = {option_key(o): o for o in (row.get("shadow_v115") or {}).get("options") or []}
        for key in set(v12_map) & set(v11_map):
            a, b = v12_map[key], v11_map[key]
            p12, p11 = core.num(a.get("p_effective"), .5), core.num(b.get("p_effective"), .5)
            result = a.get("result") or b.get("result")
            if result not in {"WIN", "LOSS", "PUSH"}:
                continue
            record = {"game_pk": row.get("game_pk"), "market": a.get("market"), "name": a.get("name"),
                      "point": a.get("point"), "v12_p": p12, "v11_p": p11, "result": result}
            labels = []
            if p12 > threshold and p11 > threshold:
                labels.append("consensus_gt55")
            elif p12 > threshold and p11 <= threshold:
                labels.append("v12_only_gt55")
            elif p11 > threshold and p12 <= threshold:
                labels.append("v11_only_gt55")
            if abs(p12-p11) >= strong_gap:
                labels.append("strong_disagreement")
            for label in labels:
                buckets[label].append(record)
                if a.get("market") in market_buckets:
                    market_buckets[a.get("market")][label].append(record)
    return {
        "version": VERSION, "source_commit": SOURCE_COMMIT, "settled_games": len(games),
        "threshold": threshold, "strong_gap": strong_gap,
        "overall": {k: _summary(v) for k, v in buckets.items()},
        "by_market": {m: {k: _summary(v) for k, v in groups.items()} for m, groups in market_buckets.items()},
        "activation": {"affects_v12_selection": False, "minimum_games_before_any_use": 50},
    }
