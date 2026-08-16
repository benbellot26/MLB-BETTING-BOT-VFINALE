from __future__ import annotations

import math

VERSION = "v12.4-convergence-score-v1"
SCHEMA = "v12-4-convergence-score-v1"
SIGNALS = (
    "model",
    "attack",
    "starter",
    "bullpen",
    "lineup",
    "statcast",
    "weather_park",
    "sharp",
)


def _num(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _norm(value):
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _key(option):
    point = option.get("point")
    return (
        str(option.get("market") or "").upper(),
        _norm(option.get("name")),
        None if point is None else round(_num(point, 0.0), 4),
    )


def _state(value, deadband, *, available=True, detail=None):
    if not available or value is None:
        return {"state": "UNAVAILABLE", "value": value, "detail": detail}
    value = _num(value, 0.0)
    if value > deadband:
        state = "SUPPORT"
    elif value < -deadband:
        state = "OPPOSE"
    else:
        state = "NEUTRAL"
    return {"state": state, "value": value, "detail": detail}


def _is_over(option):
    return _norm(option.get("name")) == "over"


def _is_under(option):
    return _norm(option.get("name")) == "under"


def _team_side(row, option):
    name = _norm(option.get("name"))
    if name == _norm(row.get("home")):
        return "home"
    if name == _norm(row.get("away")):
        return "away"
    return None


def _model_signal(option):
    p = _num(option.get("p_effective"))
    return _state(None if p is None else p-.5, .025, available=p is not None, detail={"p": p})


def _sharp_signal(option):
    p = _num(option.get("p_market"))
    # Smaller deadband than the model: the sharp signal is a reference vote,
    # not a replacement for the model probability.
    return _state(None if p is None else p-.5, .015, available=p is not None, detail={"p_market": p})


def _attack_signal(row, option, shadow):
    variants = shadow.get("variants") or {}
    base = variants.get("baseline_v1232") or {}
    home_mu = _num(base.get("home_mu"), _num(shadow.get("base_home_mu")))
    away_mu = _num(base.get("away_mu"), _num(shadow.get("base_away_mu")))
    market = str(option.get("market") or "").upper()
    point = _num(option.get("point"))
    if home_mu is None or away_mu is None:
        return _state(None, 0.0, available=False, detail={"reason": "missing_run_projection"})
    if market == "TOTAL":
        if point is None or not (_is_over(option) or _is_under(option)):
            return _state(None, 0.0, available=False, detail={"reason": "missing_total_line"})
        raw = home_mu + away_mu - point
        value = raw if _is_over(option) else -raw
        return _state(value, .20, detail={"projected_total": home_mu+away_mu, "line": point})
    side = _team_side(row, option)
    if side is None:
        return _state(None, 0.0, available=False, detail={"reason": "unknown_team_side"})
    own, opp = (home_mu, away_mu) if side == "home" else (away_mu, home_mu)
    margin = own-opp
    required = 0.0
    if market == "RUNLINE" and point is not None:
        required = -point
    value = margin-required
    return _state(value, .20, detail={"projected_margin": margin, "required_margin": required})


def _factor_signal(row, option, module, label):
    if not module or module.get("enabled") is False or module.get("status") in {"DISABLED", "UNAVAILABLE", "NO_CUTOFF"}:
        return _state(None, 0.0, available=False, detail={"module": label, "status": (module or {}).get("status")})
    home_factor = _num(module.get("home_factor"))
    away_factor = _num(module.get("away_factor"))
    if home_factor is None or away_factor is None:
        return _state(None, 0.0, available=False, detail={"module": label, "reason": "missing_factors"})
    market = str(option.get("market") or "").upper()
    if market == "TOTAL":
        direction = ((home_factor+away_factor)/2.0)-1.0
        if _is_under(option):
            direction = -direction
        elif not _is_over(option):
            return _state(None, 0.0, available=False, detail={"module": label, "reason": "unknown_total_side"})
        return _state(direction, .004, detail={"home_factor": home_factor, "away_factor": away_factor})
    side = _team_side(row, option)
    if side is None:
        return _state(None, 0.0, available=False, detail={"module": label, "reason": "unknown_team_side"})
    own, opp = (home_factor, away_factor) if side == "home" else (away_factor, home_factor)
    # Side markets care about relative movement, not whether the whole game is
    # slightly more or less run-friendly.
    direction = own/max(1e-9, opp)-1.0
    return _state(direction, .004, detail={"own_factor": own, "opponent_factor": opp})


def score_option(row, option):
    shadow = row.get("shadow_v124") or {}
    modules = shadow.get("modules") or {}
    signals = {
        "model": _model_signal(option),
        "attack": _attack_signal(row, option, shadow),
        "starter": _factor_signal(row, option, modules.get("starter_ip") or {}, "starter_ip"),
        "bullpen": _factor_signal(row, option, modules.get("bullpen_player") or {}, "bullpen_player"),
        "lineup": _factor_signal(row, option, modules.get("lineup_player") or {}, "lineup_player"),
        "statcast": _factor_signal(row, option, modules.get("statcast") or {}, "statcast"),
        "weather_park": _factor_signal(row, option, modules.get("weather_park") or {}, "weather_park"),
        "sharp": _sharp_signal(option),
    }
    support = sum(1 for item in signals.values() if item["state"] == "SUPPORT")
    oppose = sum(1 for item in signals.values() if item["state"] == "OPPOSE")
    neutral = sum(1 for item in signals.values() if item["state"] == "NEUTRAL")
    unavailable = sum(1 for item in signals.values() if item["state"] == "UNAVAILABLE")
    directional = support+oppose
    available = len(SIGNALS)-unavailable
    normalized = support/max(1, available)
    if support >= 6 and oppose <= 1:
        grade = "STRONG"
    elif support >= 5 and oppose <= 2:
        grade = "GOOD"
    elif support >= 3:
        grade = "MIXED"
    else:
        grade = "WEAK"
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "game_pk": row.get("game_pk"),
        "game": f"{row.get('away') or '?'} @ {row.get('home') or '?'}",
        "market": option.get("market"),
        "name": option.get("name"),
        "point": option.get("point"),
        "p_effective": _num(option.get("p_effective")),
        "p_market": _num(option.get("p_market")),
        "support": support,
        "oppose": oppose,
        "neutral": neutral,
        "unavailable": unavailable,
        "available": available,
        "directional": directional,
        "score_8": support,
        "normalized_support": normalized,
        "net_support": support-oppose,
        "grade": grade,
        "signals": signals,
        "research_only": True,
        "affects_v12_selection": False,
    }


def current_run(rows, run_id=None, limit=12):
    scored = []
    seen = set()
    for row in rows or []:
        if run_id and str(row.get("run_id")) != str(run_id):
            continue
        shadow = row.get("shadow_v124") or {}
        if not shadow.get("enabled") or shadow.get("status") == "ERROR":
            continue
        base = ((shadow.get("variants") or {}).get("baseline_v1232") or {})
        for option in base.get("options") or []:
            key = (str(row.get("game_pk")), _key(option))
            if key in seen:
                continue
            seen.add(key)
            scored.append(score_option(row, option))
    # Focus the summary on the direction the model itself considers at least
    # plausible, while retaining every option in the detailed output if the
    # caller requests a larger limit.
    scored.sort(
        key=lambda item: (
            item.get("score_8", 0),
            item.get("net_support", 0),
            item.get("normalized_support", 0.0),
            _num(item.get("p_effective"), .5),
        ),
        reverse=True,
    )
    plausible = [item for item in scored if _num(item.get("p_effective"), 0) >= .50]
    return (plausible or scored)[:max(1, int(limit))]


def build(rows, run_id=None, limit=12):
    options = current_run(rows, run_id=run_id, limit=limit)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "research_only": True,
        "affects_v12_selection": False,
        "signal_count": len(SIGNALS),
        "signals": list(SIGNALS),
        "method": "unweighted directional agreement; missing/neutral signals never become artificial support",
        "top_options": options,
        "guardrail": "diagnostic only; never changes probability, selector, Kelly, staking or Discord picks",
    }
