from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

VERSION = "13.8-audit-features-v1"


def _num(v: Any, d: float | None = None) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _ratio(v: Any, baseline: float, lo: float = .65, hi: float = 1.55) -> float:
    x = _num(v, baseline)
    return _clip(float(x) / max(1e-9, baseline), lo, hi)


def _weighted(values: list[tuple[float, float]], default: float = 1.0) -> float:
    good = [(float(v), max(0.0, float(w))) for v, w in values if v is not None and w is not None and float(w) > 0]
    if not good:
        return default
    return sum(v * w for v, w in good) / sum(w for _, w in good)


def shrink(value: Any, sample: Any, prior: float, prior_strength: float) -> float:
    """Empirical-Bayes style shrinkage toward a league/prior value."""
    x = _num(value, prior)
    n = max(0.0, float(_num(sample, 0.0) or 0.0))
    k = max(1e-9, float(prior_strength))
    return (n * float(x) + k * float(prior)) / (n + k)


def offense_talent(team_form: dict[str, Any] | None, league_rpg: float = 4.45) -> dict[str, Any]:
    """Multi-window offense talent with recency weighting and shrinkage.

    The function deliberately accepts only pregame summaries. It never reads a
    target score or a postgame label.
    """
    form = team_form or {}
    season = form.get("season_to_date") or {}
    l30 = form.get("last_30_games") or {}
    l14 = form.get("last_14_games") or {}
    l7 = form.get("last_7_games") or {}
    estimates = []
    for block, weight, prior_strength in ((season, .38, 40), (l30, .28, 18), (l14, .22, 10), (l7, .12, 7)):
        games = int(_num(block.get("games"), 0) or 0)
        rpg = block.get("runs_for_pg")
        if games and rpg is not None:
            estimates.append((shrink(rpg, games, league_rpg, prior_strength), weight))
    talent = _weighted(estimates, league_rpg)
    return {
        "runs_per_game": talent,
        "factor": _clip(talent / max(.1, league_rpg), .72, 1.35),
        "windows_used": len(estimates),
        "method": "multi-window recency blend with shrinkage",
    }


def starter_skill(
    starter: dict[str, Any] | None,
    statcast: dict[str, Any] | None = None,
    league: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Advanced starter run-prevention score; 1.0 is league average.

    Accepts standard MLB fields plus optional stable-ID Statcast priors. Missing
    metrics are neutral rather than imputed from future/postgame information.
    """
    s = starter or {}
    st = statcast or {}
    lg = {"era": 4.35, "whip": 1.32, "k_rate": .225, "bb_rate": .083, "xwoba": .320,
          "hard_hit_rate": .38, "barrel_rate": .075, "velocity": 93.5, **(league or {})}
    parts: list[tuple[float, float]] = []
    if s.get("era") is not None:
        parts.append((_ratio(s.get("era"), lg["era"], .55, 1.70), .22))
    if s.get("whip") is not None:
        parts.append((_ratio(s.get("whip"), lg["whip"], .60, 1.60), .12))
    k = _num(st.get("k_rate"), None)
    bb = _num(st.get("bb_rate"), None)
    if k is not None and bb is not None:
        kbb = k - bb
        lg_kbb = lg["k_rate"] - lg["bb_rate"]
        # Larger K-BB is better -> quality multiplier below 1.
        parts.append((_clip(lg_kbb / max(.04, kbb), .58, 1.65), .22))
    xwoba = _num(st.get("xwoba"), None)
    if xwoba is not None:
        parts.append((_clip(xwoba / lg["xwoba"], .60, 1.55), .18))
    hard = _num(st.get("hard_hit_rate"), None)
    if hard is not None:
        parts.append((_clip(hard / lg["hard_hit_rate"], .65, 1.50), .09))
    barrel = _num(st.get("barrel_rate"), None)
    if barrel is not None:
        parts.append((_clip(barrel / lg["barrel_rate"], .55, 1.70), .09))
    velo = _num(st.get("avg_velocity"), _num(st.get("velocity"), None))
    if velo is not None:
        parts.append((_clip(lg["velocity"] / max(85.0, velo), .91, 1.10), .08))
    quality = _weighted(parts, 1.0)
    return {"run_prevention_multiplier": _clip(quality, .62, 1.55), "components": len(parts),
            "k_minus_bb": None if k is None or bb is None else k - bb,
            "method": "ERA/WHIP + K-BB + contact-quality + velocity composite"}


def pitch_mix_matchup(
    pitcher_mix: dict[str, Any] | None,
    lineup_pitch_values: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Lineup response to the expected pitch mix.

    Each hitter entry may expose a ``pitch_values`` mapping where 1.0 is neutral
    and >1 means better offense versus that pitch. No value is manufactured when
    pitch-level batter data is absent.
    """
    mix = {str(k): max(0.0, float(_num(v, 0.0) or 0.0)) for k, v in (pitcher_mix or {}).items()}
    total = sum(mix.values())
    if total <= 0 or not lineup_pitch_values:
        return {"available": False, "factor": 1.0, "hitters": 0, "pitch_types": 0}
    mix = {k: v / total for k, v in mix.items()}
    hitter_scores = []
    for hitter in lineup_pitch_values:
        pv = hitter.get("pitch_values") or {}
        vals = [(float(_num(pv.get(pt), 1.0) or 1.0), share) for pt, share in mix.items() if pv.get(pt) is not None]
        if vals:
            hitter_scores.append(_weighted(vals, 1.0))
    if not hitter_scores:
        return {"available": False, "factor": 1.0, "hitters": 0, "pitch_types": len(mix)}
    factor = sum(hitter_scores) / len(hitter_scores)
    return {"available": True, "factor": _clip(factor, .90, 1.10), "hitters": len(hitter_scores),
            "pitch_types": len(mix), "pitch_mix": mix}


def lineup_strength(players: list[dict[str, Any]] | None, league_ops: float = .710) -> dict[str, Any]:
    """Order-aware lineup talent with PA/sample shrinkage."""
    order_weights = (1.06, 1.07, 1.10, 1.12, 1.07, 1.00, .95, .91, .88)
    vals = []
    for i, p in enumerate((players or [])[:9]):
        ops = _num(p.get("ops"), None)
        if ops is None:
            continue
        pa = _num(p.get("plate_appearances"), _num(p.get("pa"), 0.0)) or 0.0
        shrunk = shrink(ops, pa, league_ops, 120.0)
        vals.append((shrunk / league_ops, order_weights[i]))
    factor = _weighted(vals, 1.0)
    return {"factor": _clip(factor, .78, 1.28), "usable_hitters": len(vals), "lineup_size": len((players or [])[:9]),
            "confirmed": len((players or [])[:9]) >= 9}


def classify_bullpen_roles(relievers: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Infer practical roles from recent leverage/usage without name-based rules."""
    rows = list(relievers or [])
    scored = []
    for r in rows:
        saves = _num(r.get("saves"), 0.0) or 0.0
        holds = _num(r.get("holds"), 0.0) or 0.0
        gm_li = _num(r.get("gm_li"), _num(r.get("leverage_index"), 1.0)) or 1.0
        recent = _num(r.get("appearances_recent"), 0.0) or 0.0
        score = 2.0 * saves + .9 * holds + 3.0 * max(0.0, gm_li - 1.0) + .12 * recent
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    roles: dict[str, list[dict[str, Any]]] = {"closer": [], "setup": [], "high_leverage": [], "middle": [], "long": []}
    for idx, (_, r) in enumerate(scored):
        pitches = _num(r.get("pitches_3d"), 0.0) or 0.0
        apps = _num(r.get("appearances_recent"), 0.0) or 0.0
        if idx == 0:
            role = "closer"
        elif idx <= 2:
            role = "setup"
        elif idx <= 4:
            role = "high_leverage"
        elif apps <= 2 and pitches >= 40:
            role = "long"
        else:
            role = "middle"
        availability = _clip(1.0 - max(0.0, pitches - 20.0) / 45.0 - .18 * max(0.0, (_num(r.get("days_used"), 0.0) or 0.0) - 1), 0.0, 1.0)
        roles[role].append({"id": r.get("id"), "name": r.get("name"), "availability": availability,
                            "pitches_3d": pitches})
    return {"roles": roles, "relievers": len(rows),
            "high_leverage_available": sum(x["availability"] for k in ("closer", "setup", "high_leverage") for x in roles[k])}


def detect_opener(starter: dict[str, Any] | None) -> dict[str, Any]:
    """Detect likely opener/bullpen-game profile from starter workload history."""
    s = starter or {}
    starts = _num(s.get("gamesStarted"), _num(s.get("starts"), 0.0)) or 0.0
    ip = _num(s.get("inningsPitched"), _num(s.get("innings"), 0.0)) or 0.0
    avg_ip = _num(s.get("avg_ip_per_start"), None)
    if avg_ip is None and starts > 0:
        avg_ip = ip / starts
    recent = _num(s.get("recent_expected_ip"), avg_ip)
    opener = recent is not None and recent < 3.0 and starts >= 1
    bullpen_game = recent is not None and recent < 2.0
    return {"opener": bool(opener), "bullpen_game": bool(bullpen_game), "expected_starter_ip": recent,
            "confidence": _clip(starts / 8.0, 0.0, 1.0)}


def park_factor(prior: dict[str, Any] | None, expected_lhb_share: float | None = None) -> dict[str, Any]:
    """Shrink raw Savant index toward 100 and blend handedness when available."""
    p = prior or {}
    if not p.get("available"):
        return {"available": False, "run_factor": 1.0}
    all_idx = _num(p.get("ALL") or p.get("all") or p.get("index"), 100.0) or 100.0
    lhb = _num(p.get("LHB") or p.get("lhb"), all_idx) or all_idx
    rhb = _num(p.get("RHB") or p.get("rhb"), all_idx) or all_idx
    share = .45 if expected_lhb_share is None else _clip(expected_lhb_share, 0.0, 1.0)
    raw = share * lhb + (1.0 - share) * rhb
    # Park indices are noisy; use a deliberately strong shrink toward neutral.
    shrunk = 100.0 + .60 * (raw - 100.0)
    return {"available": True, "raw_index": raw, "shrunk_index": shrunk,
            "run_factor": _clip(shrunk / 100.0, .88, 1.13), "lhb_share": share}


def circadian_travel(context: dict[str, Any] | None) -> dict[str, Any]:
    """Travel/rest/circadian feature from explicitly supplied pregame metadata."""
    c = context or {}
    tz_shift = _num(c.get("timezone_shift_hours"), 0.0) or 0.0
    travel_km = max(0.0, _num(c.get("travel_km"), 0.0) or 0.0)
    rest = max(0.0, _num(c.get("rest_days"), 1.0) or 1.0)
    local_hour = _num(c.get("body_clock_game_hour"), _num(c.get("local_game_hour"), 19.0)) or 19.0
    circadian_penalty = max(0.0, abs(tz_shift) - 1.0) * .006 + max(0.0, travel_km - 1200.0) / 1000.0 * .004
    if local_hour < 12 or local_hour > 23:
        circadian_penalty += .008
    if rest >= 1:
        circadian_penalty *= .65
    return {"timezone_shift_hours": tz_shift, "travel_km": travel_km, "rest_days": rest,
            "offense_factor": _clip(1.0 - circadian_penalty, .95, 1.01), "penalty": circadian_penalty}


def roster_availability(
    lineup_ids: list[int] | None,
    roster_ids: list[int] | None,
    il_signals: list[dict[str, Any]] | None = None,
    player_values: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Quantify known absences without pretending transactions are a full injury feed."""
    lineup = {int(x) for x in (lineup_ids or []) if x is not None}
    roster = {int(x) for x in (roster_ids or []) if x is not None}
    values = player_values or {}
    il_ids = {int(t["person_id"]) for t in (il_signals or []) if t.get("person_id") is not None and t.get("injured_list_signal")}
    known_absent = sorted((lineup - roster) | (lineup & il_ids))
    impact = 0.0
    for pid in known_absent:
        impact += max(0.0, float(_num(values.get(str(pid)), .01) or .01))
    return {"known_absent_ids": known_absent, "known_absent_count": len(known_absent),
            "offense_factor": _clip(1.0 - impact, .90, 1.0), "impact": impact,
            "complete_injury_report": False}


def defense_factor(context: dict[str, Any] | None) -> dict[str, Any]:
    c = context or {}
    oaa = _num(c.get("oaa"), None)
    drs = _num(c.get("drs"), None)
    vals = []
    if oaa is not None:
        vals.append((_clip(oaa / 30.0, -1.0, 1.0), .65))
    if drs is not None:
        vals.append((_clip(drs / 35.0, -1.0, 1.0), .35))
    signal = _weighted(vals, 0.0) if vals else 0.0
    return {"available": bool(vals), "runs_allowed_factor": _clip(1.0 - .035 * signal, .965, 1.035), "signal": signal}


def baserunning_factor(context: dict[str, Any] | None) -> dict[str, Any]:
    c = context or {}
    br = _num(c.get("baserunning_runs"), _num(c.get("bsr"), None))
    sprint = _num(c.get("sprint_speed_index"), None)
    vals = []
    if br is not None:
        vals.append((_clip(br / 12.0, -1.0, 1.0), .8))
    if sprint is not None:
        vals.append((_clip(sprint, -1.0, 1.0), .2))
    signal = _weighted(vals, 0.0) if vals else 0.0
    return {"available": bool(vals), "offense_factor": _clip(1.0 + .018 * signal, .982, 1.018), "signal": signal}


def catcher_framing_factor(context: dict[str, Any] | None) -> dict[str, Any]:
    runs = _num((context or {}).get("framing_runs"), None)
    if runs is None:
        return {"available": False, "runs_allowed_factor": 1.0}
    signal = _clip(runs / 12.0, -1.0, 1.0)
    return {"available": True, "runs_allowed_factor": _clip(1.0 - .012 * signal, .988, 1.012), "signal": signal}


def umpire_factor(context: dict[str, Any] | None) -> dict[str, Any]:
    c = context or {}
    run_env = _num(c.get("run_environment_index"), None)
    called_strike = _num(c.get("called_strike_index"), None)
    if run_env is None and called_strike is None:
        return {"available": False, "run_factor": 1.0}
    vals = []
    if run_env is not None:
        vals.append((_clip(run_env, .94, 1.06), .75))
    if called_strike is not None:
        vals.append((_clip(2.0 - called_strike, .96, 1.04), .25))
    return {"available": True, "run_factor": _clip(_weighted(vals, 1.0), .95, 1.05)}


def contextual_dispersion(base: float, context: dict[str, Any] | None) -> dict[str, Any]:
    c = context or {}
    uncertainty = max(0.0, _num(c.get("lineup_uncertainty"), 0.0) or 0.0)
    bullpen = max(0.0, _num(c.get("bullpen_uncertainty"), 0.0) or 0.0)
    weather = max(0.0, _num(c.get("weather_uncertainty"), 0.0) or 0.0)
    starter = max(0.0, _num(c.get("starter_uncertainty"), 0.0) or 0.0)
    multiplier = 1.0 + .10 * uncertainty + .08 * bullpen + .05 * weather + .08 * starter
    return {"dispersion": _clip(float(base) * multiplier, max(.5, float(base) * .80), float(base) * 1.35),
            "multiplier": multiplier, "learned": False, "requires_oos_validation": True}


def build_advanced_context(result: dict[str, Any], statcast_priors: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compose advanced research features from a live/replay result.

    This is research-only metadata. It does not mutate V13 champion probabilities.
    """
    ctx = result.get("ctx") or {}
    features = result.get("features") or {}
    stat = statcast_priors or {}
    hitters = stat.get("hitters") or {}
    pitchers = stat.get("pitchers") or {}
    out: dict[str, Any] = {"version": VERSION, "research_only": True, "affects_champion": False}
    for side, opp in (("home", "away"), ("away", "home")):
        lineup = ((ctx.get(f"{side}_lineup") or {}).get("players") or [])[:9]
        starter = ctx.get(f"{opp}_starter") or {}
        starter_id = str(starter.get("id") or "")
        out[side] = {
            "lineup": lineup_strength(lineup),
            "starter_against": starter_skill(starter, pitchers.get(starter_id) or {}),
            "pitch_matchup": pitch_mix_matchup((pitchers.get(starter_id) or {}).get("pitch_mix") or {},
                                                [{"pitch_values": (hitters.get(str(p.get("id") or "")) or {}).get("pitch_values") or {}} for p in lineup]),
            "travel": circadian_travel((features.get("travel") or {}).get(side) or {}),
            "defense": defense_factor((features.get("defense") or {}).get(side) or {}),
            "baserunning": baserunning_factor((features.get("baserunning") or {}).get(side) or {}),
            "catcher": catcher_framing_factor((features.get("catcher") or {}).get(side) or {}),
        }
    bp = features.get("bullpen") or {}
    out["bullpen"] = {side: classify_bullpen_roles((bp.get(side) or {}).get("relievers") or []) for side in ("home", "away")}
    out["opener"] = {side: detect_opener(ctx.get(f"{side}_starter") or {}) for side in ("home", "away")}
    out["umpire"] = umpire_factor(features.get("umpire") or {})
    return out
