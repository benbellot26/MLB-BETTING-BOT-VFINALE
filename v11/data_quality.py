from __future__ import annotations

from collections import Counter
from . import config, core


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def assess(result, rec=None):
    """Return an auditable 0..1 data-completeness score and hard blockers.

    The score is deliberately about data availability/recency, not predicted edge.
    It must not double-count model probability or market value.
    """
    ctx = result.get("ctx") or {}
    lineup_home = ctx.get("home_lineup") or {}
    lineup_away = ctx.get("away_lineup") or {}
    starter_home = ctx.get("home_starter") or {}
    starter_away = ctx.get("away_starter") or {}
    phase = str(result.get("phase") or "EARLY").upper()

    components = {}
    components["starter_identity"] = 1.0 if ctx.get("home_sp") and ctx.get("away_sp") else 0.0
    sw = min(_num(starter_home.get("sample_weight")), _num(starter_away.get("sample_weight")))
    components["starter_stats"] = max(0.0, min(1.0, 0.35 + 0.65 * sw)) if components["starter_identity"] else 0.0

    lineup_count = int(_num(lineup_home.get("count"))) + int(_num(lineup_away.get("count")))
    if lineup_count >= 18:
        lineup_score = 1.0
    elif lineup_count >= 14:
        lineup_score = 0.82
    elif lineup_count >= 9:
        lineup_score = 0.58
    elif lineup_count > 0:
        lineup_score = 0.35
    else:
        lineup_score = 0.15 if phase == "EARLY" else 0.0
    components["lineup"] = lineup_score

    features = result.get("features") or {}
    weather = features.get("weather") or {}
    components["weather"] = 1.0 if weather.get("available") else (0.7 if weather.get("not_applicable") else 0.35)

    bp = features.get("bullpen") or {}
    components["bullpen"] = max(0.2, min(1.0, _num(bp.get("coverage"), 0.2)))

    if rec is None:
        refs = int(_num((result.get("con") or {}).get("n")))
        max_age = (result.get("con") or {}).get("max_age_min")
        price = None
    else:
        refs = int(_num(rec.get("refs")))
        max_age = rec.get("sharp_max_age_min")
        price = (rec.get("winamax_eval") or {}).get("price")

    components["sharp_coverage"] = min(1.0, refs / 3.0) if refs else 0.0
    if max_age is None:
        components["sharp_recency"] = 0.0 if refs else 0.2
    else:
        age = max(0.0, _num(max_age))
        components["sharp_recency"] = max(0.0, 1.0 - age / max(1.0, config.MAX_SHARP_AGE_MIN))

    if rec is not None:
        components["execution_price"] = 1.0 if _num(price) > 1.0 else 0.0

    weights = {
        "starter_identity": 0.13,
        "starter_stats": 0.13,
        "lineup": 0.18,
        "weather": 0.08,
        "bullpen": 0.12,
        "sharp_coverage": 0.18,
        "sharp_recency": 0.10,
        "execution_price": 0.08,
    }
    used = [(k, v) for k, v in components.items() if k in weights]
    denom = sum(weights[k] for k, _ in used) or 1.0
    score = sum(weights[k] * v for k, v in used) / denom

    blockers = []
    if not components["starter_identity"] and phase in {"LATE", "FINAL"}:
        blockers.append("starters_unconfirmed")
    if phase == "FINAL" and lineup_count < config.MIN_FINAL_LINEUP_PLAYERS:
        blockers.append("final_lineup_incomplete")
    if rec is not None:
        if refs < config.MIN_SHARP_REFS:
            blockers.append("sharp_reference_missing")
        if components["sharp_recency"] <= 0:
            blockers.append("sharp_timestamp_missing_or_stale")
        if components["execution_price"] <= 0:
            blockers.append("execution_price_missing")

    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "components": {k: round(v, 4) for k, v in components.items()},
        "blockers": blockers,
        "eligible": score >= config.MIN_DATA_QUALITY and not blockers,
        "lineup_players": lineup_count,
        "phase": phase,
    }


def health_report(results, scheduled_games=None, matched_events=None):
    scheduled_games = len(results) if scheduled_games is None else int(scheduled_games)
    matched_events = len(results) if matched_events is None else int(matched_events)
    counts = Counter()
    qualities = []
    for r in results:
        q = assess(r)
        qualities.append(q["score"])
        if q["lineup_players"] >= 18:
            counts["confirmed_lineups"] += 1
        if (r.get("ctx") or {}).get("home_sp") and (r.get("ctx") or {}).get("away_sp"):
            counts["confirmed_starters"] += 1
        for m in ("ML", "RUNLINE", "TOTAL"):
            opts = [o for o in r.get("options") or [] if o.get("market") == m]
            if any(int(_num(o.get("refs"))) >= config.MIN_SHARP_REFS for o in opts):
                counts[f"sharp_{m.lower()}"] += 1
            if any(_num((o.get("winamax_eval") or {}).get("price")) > 1 for o in opts):
                counts[f"winamax_{m.lower()}"] += 1
    return {
        "scheduled_games": scheduled_games,
        "matched_events": matched_events,
        "analyzed_games": len(results),
        "confirmed_starters": counts["confirmed_starters"],
        "confirmed_lineups": counts["confirmed_lineups"],
        "sharp_coverage": {m: counts[f"sharp_{m.lower()}"] for m in ("ML", "RUNLINE", "TOTAL")},
        "winamax_coverage": {m: counts[f"winamax_{m.lower()}"] for m in ("ML", "RUNLINE", "TOTAL")},
        "mean_data_quality": round(sum(qualities) / len(qualities), 4) if qualities else None,
    }
