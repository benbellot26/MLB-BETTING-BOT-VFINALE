from __future__ import annotations

from collections import Counter
from . import config


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def decision_sharp_age_limit(phase):
    phase = str(phase or "EARLY").upper()
    if phase == "FINAL":
        return config.MAX_SHARP_AGE_FINAL_MIN
    if phase == "LATE":
        return config.MAX_SHARP_AGE_LATE_MIN
    return config.MAX_SHARP_AGE_EARLY_MIN


def active_model_feature_contract(result):
    """Return only data families that can affect the active production forecast.

    Weather and the enriched three-day bullpen state exist in the research
    payload even when the production champion is purely structural. They must
    not make the production probability look more certain until a learned
    model that actually consumes them is active.
    """
    active = ["starter_identity", "starter_stats", "lineup_identity", "lineup_stats", "team_stats"]
    model = result.get("model") or {}
    learned_active = bool(model.get("active"))
    learned_features = set((model.get("features") or []) if isinstance(model.get("features"), list) else [])
    features = result.get("features") or {}
    learned = features.get("learned_run_adjustment") or {}
    learned_active = learned_active or bool(learned.get("active"))
    if learned_active:
        if not learned_features or any(k in learned_features for k in ("temperature_c","wind_kph","humidity_pct")):
            active.append("weather")
        if not learned_features or any("bullpen" in k for k in learned_features):
            active.append("bullpen")
    return tuple(active)


def assess(result, rec=None):
    ctx = result.get("ctx") or {}
    phase = str(result.get("phase") or "EARLY").upper()
    lineup_home, lineup_away = ctx.get("home_lineup") or {}, ctx.get("away_lineup") or {}
    starter_home, starter_away = ctx.get("home_starter") or {}, ctx.get("away_starter") or {}
    features = result.get("features") or {}
    source = features.get("source_quality") or {}

    components = {}
    components["starter_identity"] = 1.0 if ctx.get("home_sp") and ctx.get("away_sp") else 0.0
    starter_sources = []
    for st in (starter_home, starter_away):
        if st.get("current_stats_available"):
            starter_sources.append(1.0)
        elif st.get("prior_available"):
            starter_sources.append(.70)
        else:
            starter_sources.append(0.0)
    components["starter_stats"] = min(starter_sources) if starter_sources else 0.0

    lineup_count = int(_num(lineup_home.get("count")))+int(_num(lineup_away.get("count")))
    usable_home = int(_num(source.get("home_lineup_usable_ops"), sum(1 for p in lineup_home.get("players") or [] if p.get("ops") is not None)))
    usable_away = int(_num(source.get("away_lineup_usable_ops"), sum(1 for p in lineup_away.get("players") or [] if p.get("ops") is not None)))
    usable_lineup = usable_home+usable_away
    identity_fraction = min(1.0, lineup_count/18.0)
    stats_fraction = min(1.0, usable_lineup/18.0)
    components["lineup_identity"] = identity_fraction
    components["lineup_stats"] = .65*stats_fraction+.35*identity_fraction if lineup_count else (0.10 if phase == "EARLY" else 0.0)

    team_flags = [source.get(k) for k in ("home_team_hitting", "away_team_hitting", "home_team_pitching", "away_team_pitching")]
    components["team_stats"] = sum(bool(x) for x in team_flags)/4.0 if team_flags else 0.0

    weather = features.get("weather") or {}
    components["weather"] = 1.0 if weather.get("available") else (.8 if weather.get("not_applicable") else .30)
    bp = features.get("bullpen") or {}
    components["bullpen"] = max(0.0, min(1.0, _num(bp.get("coverage"), 0.0)))

    if rec is None:
        refs = int(_num((result.get("con") or {}).get("n")))
        max_age = (result.get("con") or {}).get("max_age_min")
        price = None
    else:
        refs = int(_num(rec.get("refs")))
        max_age = rec.get("sharp_max_age_min")
        price = (rec.get("winamax_eval") or {}).get("price")
    components["sharp_coverage"] = min(1.0, refs/3.0) if refs else 0.0
    broad_age_limit = max(1.0, config.MAX_SHARP_AGE_MIN)
    if max_age is None:
        components["sharp_recency"] = 0.0 if refs else .15
    else:
        components["sharp_recency"] = max(0.0, 1-max(0.0, _num(max_age))/broad_age_limit)
    if rec is not None:
        components["execution_price"] = 1.0 if _num(price) > 1.0 else 0.0

    # Base weights describe the structural production model. Optional research
    # inputs join only when an active learned production artifact actually uses
    # them. This keeps epistemic confidence tied to the active feature contract.
    base_model_weights = {"starter_identity": .15, "starter_stats": .24, "lineup_identity": .12,
                          "lineup_stats": .24, "team_stats": .25}
    optional_model_weights = {"weather": .08, "bullpen": .14}
    active_contract = active_model_feature_contract(result)
    model_weights = {k:v for k,v in base_model_weights.items() if k in active_contract}
    model_weights.update({k:v for k,v in optional_model_weights.items() if k in active_contract})
    model_denom = sum(model_weights.values()) or 1.0
    model_input_score = sum(model_weights[k]*components.get(k,0.0) for k in model_weights)/model_denom

    weights = {"starter_identity": .09, "starter_stats": .14, "lineup_identity": .08, "lineup_stats": .14,
               "team_stats": .11, "weather": .06, "bullpen": .11, "sharp_coverage": .13,
               "sharp_recency": .08, "execution_price": .06}
    used = [(k, v) for k, v in components.items() if k in weights]
    denom = sum(weights[k] for k, _ in used) or 1.0
    score = sum(weights[k]*v for k, v in used)/denom

    blockers = []
    if not components["starter_identity"] and phase in {"LATE", "FINAL"}:
        blockers.append("starters_unconfirmed")
    if phase == "FINAL" and components["starter_stats"] <= 0:
        blockers.append("starter_stats_unusable")
    if phase == "FINAL" and lineup_count < config.MIN_FINAL_LINEUP_PLAYERS:
        blockers.append("final_lineup_incomplete")
    if phase == "FINAL" and usable_lineup < config.MIN_FINAL_USABLE_LINEUP_STATS:
        blockers.append("final_lineup_stats_incomplete")
    if components["team_stats"] < .75:
        blockers.append("team_stats_incomplete")
    model = result.get("model") or {}
    if model.get("artifact_status") in {"INVALID", "INCOMPATIBLE"} or model.get("artifact_error"):
        blockers.append("model_artifact_invalid")
    if rec is not None:
        if refs < config.MIN_SHARP_REFS:
            blockers.append("sharp_reference_missing")
        if max_age is None:
            blockers.append("sharp_timestamp_missing_or_stale")
        elif _num(max_age, 9999) > decision_sharp_age_limit(phase):
            blockers.append(f"sharp_stale_for_{phase.lower()}")
        if components["execution_price"] <= 0:
            blockers.append("execution_price_missing")

    return {"score": round(max(0.0, min(1.0, score)), 4),
            "model_input_score": round(max(0.0, min(1.0, model_input_score)), 4),
            "model_input_contract": list(active_contract),
            "model_input_weights": {k:round(v,4) for k,v in model_weights.items()},
            "components": {k: round(v, 4) for k, v in components.items()}, "blockers": blockers,
            "eligible": score >= config.MIN_DATA_QUALITY and not blockers,
            "lineup_players": lineup_count, "usable_lineup_stats": usable_lineup,
            "usable_home_lineup_stats": usable_home, "usable_away_lineup_stats": usable_away,
            "phase": phase, "decision_sharp_age_limit_min": decision_sharp_age_limit(phase)}


def health_report(results, scheduled_games=None, matched_events=None):
    scheduled_games = len(results) if scheduled_games is None else int(scheduled_games)
    matched_events = len(results) if matched_events is None else int(matched_events)
    counts, qualities = Counter(), []
    for r in results:
        q = assess(r)
        qualities.append(q["score"])
        if q["lineup_players"] >= 18:
            counts["confirmed_lineups"] += 1
        if q["usable_lineup_stats"] >= config.MIN_FINAL_USABLE_LINEUP_STATS:
            counts["usable_lineups"] += 1
        if (r.get("ctx") or {}).get("home_sp") and (r.get("ctx") or {}).get("away_sp"):
            counts["confirmed_starters"] += 1
        if q["components"].get("starter_stats", 0) > 0:
            counts["usable_starters"] += 1
        for m in ("ML", "RUNLINE", "TOTAL"):
            opts = [o for o in r.get("options") or [] if o.get("market") == m]
            if any(int(_num(o.get("refs"))) >= config.MIN_SHARP_REFS for o in opts):
                counts[f"sharp_{m.lower()}"] += 1
            if any(_num((o.get("winamax_eval") or {}).get("price")) > 1 for o in opts):
                counts[f"winamax_{m.lower()}"] += 1
    return {"scheduled_games": scheduled_games, "matched_events": matched_events, "analyzed_games": len(results),
            "confirmed_starters": counts["confirmed_starters"], "usable_starters": counts["usable_starters"],
            "confirmed_lineups": counts["confirmed_lineups"], "usable_lineups": counts["usable_lineups"],
            "sharp_coverage": {m: counts[f"sharp_{m.lower()}"] for m in ("ML", "RUNLINE", "TOTAL")},
            "winamax_coverage": {m: counts[f"winamax_{m.lower()}"] for m in ("ML", "RUNLINE", "TOTAL")},
            "mean_data_quality": round(sum(qualities)/len(qualities), 4) if qualities else None}
