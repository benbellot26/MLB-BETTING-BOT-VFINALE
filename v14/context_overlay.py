from __future__ import annotations

"""Conservative PIT contextual overlay for the isolated Pulsar V14 shadow.

This module intentionally does *not* replace the V13.10 run stack. It converts a
small set of defensible pregame contextual signals into tightly capped residual
adjustments on top of the frozen champion run means.

Design rules:
- fail closed on missing/unsafe data;
- use confirmed/ordered lineups only (never invent a "top 9");
- shrink tiny H2H samples aggressively;
- keep recent form as a micro-signal;
- never use market probability/odds as a predictive feature;
- cap every team's total contextual move at +/-2.5%.
"""

from dataclasses import dataclass, asdict
import math
from typing import Any

CONTEXT_SCHEMA = "v14-context-residual-v1"
MAX_TEAM_DELTA = 0.025
MAX_STARTER_DELTA = 0.018
MAX_LINEUP_DELTA = 0.018
MAX_BULLPEN_DELTA = 0.015
MAX_H2H_DELTA = 0.004
MAX_RECENT_FORM_DELTA = 0.004


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _first_num(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in mapping:
            value = _num(mapping.get(key))
            if value is not None:
                return value
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested_first(root: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    for name in names:
        value = root.get(name)
        if isinstance(value, dict) and value:
            return value
    return {}


def row_is_safe(row: dict[str, Any] | None) -> bool:
    """Return True only for a feature-store row that is explicitly PIT-safe."""
    if not isinstance(row, dict) or not row:
        return False
    if row.get("point_in_time") is not True:
        return False
    if row.get("point_in_time_validation_reasons"):
        return False
    quality = _mapping(row.get("data_quality"))
    if quality.get("eligible") is False:
        return False
    return True


def _component_provenance_safe(row: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    """Optional extra provenance gate.

    The V13 feature store itself is already built only from validated pregame
    rows. Some generations additionally persist per-module provenance. When
    such metadata exists, reject an explicitly unsafe component; when it does
    not exist, inherit the validated feature-store PIT contract.
    """
    provenance = _mapping(row.get("feature_provenance"))
    if not provenance:
        return True

    candidates: list[dict[str, Any]] = []
    for key, value in provenance.items():
        lowered = str(key).lower()
        if any(alias in lowered for alias in aliases) and isinstance(value, dict):
            candidates.append(value)

    if not candidates:
        return True

    for candidate in candidates:
        if candidate.get("postgame_identity") is True:
            return False
        if candidate.get("point_in_time") is False:
            return False
        if candidate.get("source_timestamp_attested") is False:
            return False
    return True


@dataclass(frozen=True)
class Signal:
    score: float
    confidence: float
    delta: float
    available: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _starter_stats(starter: dict[str, Any] | None) -> tuple[dict[str, Any], float]:
    data = _mapping(starter)
    if not data:
        return {}, 0.0

    identity = (
        data.get("id")
        or data.get("player_id")
        or data.get("pitcher_id")
        or data.get("name")
        or data.get("fullName")
    )
    if not identity:
        return {}, 0.0

    stats = _nested_first(
        data,
        ("season_stats", "current_stats", "stats", "pitching", "season", "current"),
    )
    if not stats:
        stats = data

    ip = _first_num(stats, "inningsPitched", "innings_pitched", "ip", "IP")
    if ip is None:
        ip = _first_num(data, "inningsPitched", "innings_pitched", "ip", "IP")
    return stats, max(0.0, ip or 0.0)


def starter_vulnerability(starter: dict[str, Any] | None) -> Signal:
    """Continuous starter-vulnerability score (0 elite -> 100 vulnerable)."""
    stats, ip = _starter_stats(starter)
    if not stats:
        return Signal(50.0, 0.0, 0.0, False, "starter identity/stats unavailable")

    era = _first_num(stats, "era", "ERA")
    whip = _first_num(stats, "whip", "WHIP")
    bb9 = _first_num(stats, "walksPer9Inn", "bb9", "BB9", "bb_per_9")
    hr9 = _first_num(stats, "homeRunsPer9", "homeRunsPer9Inn", "hr9", "HR9")
    k9 = _first_num(stats, "strikeoutsPer9Inn", "k9", "K9", "k_per_9")

    metrics = [x for x in (era, whip, bb9, hr9, k9) if x is not None]
    if len(metrics) < 2:
        return Signal(50.0, 0.0, 0.0, False, "insufficient starter metrics")

    contributions: list[tuple[float, float]] = []
    if era is not None:
        contributions.append((_clip((era - 4.10) / 2.25, -1.0, 1.0), 0.30))
    if whip is not None:
        contributions.append((_clip((whip - 1.28) / 0.42, -1.0, 1.0), 0.25))
    if bb9 is not None:
        contributions.append((_clip((bb9 - 3.05) / 2.00, -1.0, 1.0), 0.15))
    if hr9 is not None:
        contributions.append((_clip((hr9 - 1.18) / 0.95, -1.0, 1.0), 0.15))
    if k9 is not None:
        contributions.append((_clip((8.40 - k9) / 3.00, -1.0, 1.0), 0.15))

    weight = sum(w for _v, w in contributions)
    centered = sum(v * w for v, w in contributions) / max(1e-12, weight)
    score = _clip(50.0 + 40.0 * centered, 0.0, 100.0)

    sample_conf = _clip(ip / 120.0, 0.15, 1.0) if ip > 0 else 0.45
    metric_conf = _clip(len(contributions) / 5.0, 0.0, 1.0)
    confidence = sample_conf * metric_conf
    delta = _clip(((score - 50.0) / 50.0) * MAX_STARTER_DELTA * confidence,
                  -MAX_STARTER_DELTA, MAX_STARTER_DELTA)
    return Signal(score, confidence, delta, True, "continuous starter vulnerability")


def _lineup_players(lineup: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(lineup, list):
        players = [p for p in lineup if isinstance(p, dict)]
        return players, len(players) >= 7
    data = _mapping(lineup)
    players = []
    for key in ("players", "lineup", "ordered", "batters", "starting_lineup"):
        value = data.get(key)
        if isinstance(value, list):
            players = [p for p in value if isinstance(p, dict)]
            if players:
                break
    confirmed = bool(
        data.get("confirmed")
        or data.get("is_confirmed")
        or str(data.get("status") or "").upper() in {"CONFIRMED", "OFFICIAL"}
        or str(data.get("source") or "").lower().find("official") >= 0
    )
    return players, confirmed or len(players) >= 7


def _player_ops(player: dict[str, Any]) -> float | None:
    direct = _first_num(player, "ops", "OPS")
    if direct is not None:
        return direct
    stats = _nested_first(player, ("stats", "season_stats", "hitting", "season"))
    return _first_num(stats, "ops", "OPS")


def lineup_strength(lineup: Any, rich_modules: dict[str, Any] | None = None,
                    side: str | None = None) -> Signal:
    """Score a real ordered/confirmed lineup; never synthesizes a batting order."""
    players, confirmed = _lineup_players(lineup)
    if not confirmed or len(players) < 7:
        return Signal(50.0, 0.0, 0.0, False, "confirmed/ordered lineup coverage < 7")

    ops_values = [x for x in (_player_ops(p) for p in players[:9]) if x is not None]
    if len(ops_values) < 5:
        return Signal(50.0, 0.0, 0.0, False, "insufficient hitter OPS coverage")

    mean_ops = sum(ops_values) / len(ops_values)
    score = _clip(50.0 + (mean_ops - 0.725) / 0.125 * 40.0, 0.0, 100.0)
    confidence = _clip(len(ops_values) / 9.0, 0.0, 1.0)

    rich = _mapping(rich_modules)
    side_key = str(side or "").lower()
    candidate_modules: list[dict[str, Any]] = []
    for key, value in rich.items():
        if not isinstance(value, dict):
            continue
        low = str(key).lower()
        if side_key and side_key not in low:
            continue
        if any(token in low for token in ("lineup", "statcast", "platoon")):
            candidate_modules.append(value)

    xwobas = []
    player_factor = None
    platoon_factor = None
    for module in candidate_modules:
        status = str(module.get("status") or module.get("state") or "").upper()
        if status and status not in {"ACTIVE", "OK", "READY"}:
            continue
        for key in ("xwoba", "lineup_xwoba", "avg_xwoba", "mean_xwoba"):
            value = _num(module.get(key))
            if value is not None:
                xwobas.append(value)
        for key in ("factor", "lineup_factor", "offense_factor"):
            value = _num(module.get(key))
            if value is not None:
                player_factor = value
                break
        for key in ("platoon_factor", "factor_vs_hand"):
            value = _num(module.get(key))
            if value is not None:
                platoon_factor = value
                break

    if xwobas:
        xwoba = sum(xwobas) / len(xwobas)
        x_score = _clip(50.0 + (xwoba - 0.320) / 0.055 * 35.0, 0.0, 100.0)
        score = 0.70 * score + 0.30 * x_score
    if player_factor is not None:
        score += _clip((player_factor - 1.0) * 80.0, -8.0, 8.0)
    if platoon_factor is not None:
        score += _clip((platoon_factor - 1.0) * 60.0, -6.0, 6.0)
    score = _clip(score, 0.0, 100.0)

    delta = _clip(((score - 50.0) / 50.0) * MAX_LINEUP_DELTA * confidence,
                  -MAX_LINEUP_DELTA, MAX_LINEUP_DELTA)
    return Signal(score, confidence, delta, True, "confirmed lineup strength")


def _relievers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("relievers", "pitchers", "bullpen", "players"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def bullpen_stress(snapshot: dict[str, Any] | None) -> Signal:
    """Score bullpen fatigue/availability (0 rested -> 100 highly stressed)."""
    data = _mapping(snapshot)
    if not data:
        return Signal(50.0, 0.0, 0.0, False, "bullpen snapshot unavailable")
    relievers = _relievers(data)
    coverage = _first_num(data, "coverage", "coverage_ratio", "player_coverage")
    if coverage is None and relievers:
        coverage = min(1.0, len(relievers) / 7.0)
    if (coverage or 0.0) < 0.60 or len(relievers) < 3:
        return Signal(50.0, 0.0, 0.0, False, "bullpen coverage insufficient")

    taxed = unavailable = repeat = 0
    pitches3 = []
    eras = []
    whips = []
    for reliever in relievers:
        if reliever.get("taxed") is True or str(reliever.get("status") or "").upper() == "TAXED":
            taxed += 1
        if reliever.get("available") is False or reliever.get("likely_unavailable") is True:
            unavailable += 1
        uses = _first_num(reliever, "uses_last_3d", "appearances_last_3d", "recent_appearances")
        if uses is not None and uses >= 2:
            repeat += 1
        p3 = _first_num(reliever, "pitches_last_3d", "pitch_count_last_3d", "three_day_pitches")
        if p3 is not None:
            pitches3.append(p3)
        stats = _nested_first(reliever, ("stats", "season_stats", "recent_stats"))
        eras.append(_first_num(stats or reliever, "era", "ERA"))
        whips.append(_first_num(stats or reliever, "whip", "WHIP"))

    n = max(1, len(relievers))
    workload = 0.0
    workload += 0.34 * _clip(taxed / n / 0.45, 0.0, 1.0)
    workload += 0.28 * _clip(unavailable / n / 0.30, 0.0, 1.0)
    workload += 0.18 * _clip(repeat / n / 0.45, 0.0, 1.0)
    if pitches3:
        workload += 0.20 * _clip((sum(pitches3) / len(pitches3)) / 45.0, 0.0, 1.0)

    quality_penalty = 0.0
    valid_era = [x for x in eras if x is not None]
    valid_whip = [x for x in whips if x is not None]
    if valid_era:
        quality_penalty += 0.55 * _clip((sum(valid_era) / len(valid_era) - 4.00) / 2.50, -1.0, 1.0)
    if valid_whip:
        quality_penalty += 0.45 * _clip((sum(valid_whip) / len(valid_whip) - 1.28) / 0.45, -1.0, 1.0)

    score = _clip(100.0 * (0.82 * workload + 0.18 * _clip(0.5 + quality_penalty / 2.0, 0.0, 1.0)),
                  0.0, 100.0)
    confidence = _clip(float(coverage), 0.0, 1.0)
    delta = _clip(((score - 35.0) / 65.0) * MAX_BULLPEN_DELTA * confidence,
                  -MAX_BULLPEN_DELTA, MAX_BULLPEN_DELTA)
    return Signal(score, confidence, delta, True, "bullpen fatigue/availability")


def h2h_micro_signal(records: Any) -> Signal:
    """Tiny, heavily shrunk batter-vs-pitcher signal."""
    hits = at_bats = 0.0
    if isinstance(records, dict):
        h = _first_num(records, "hits", "H")
        ab = _first_num(records, "at_bats", "atBats", "AB")
        if h is not None and ab is not None:
            hits, at_bats = h, ab
    elif isinstance(records, list):
        for rec in records:
            if not isinstance(rec, dict):
                continue
            h = _first_num(rec, "hits", "H")
            ab = _first_num(rec, "at_bats", "atBats", "AB")
            if h is not None and ab is not None and ab >= 0:
                hits += h
                at_bats += ab

    if at_bats <= 0:
        return Signal(50.0, 0.0, 0.0, False, "no attested H2H sample")

    prior_ab, prior_avg = 40.0, 0.250
    posterior = (hits + prior_ab * prior_avg) / (at_bats + prior_ab)
    confidence = _clip(at_bats / (at_bats + prior_ab), 0.0, 1.0)
    score = _clip(50.0 + (posterior - prior_avg) / 0.120 * 30.0, 0.0, 100.0)
    delta = _clip((posterior - prior_avg) / 0.120 * MAX_H2H_DELTA * confidence,
                  -MAX_H2H_DELTA, MAX_H2H_DELTA)
    return Signal(score, confidence, delta, True, "Bayesian-shrunk H2H micro-signal")


def recent_form_signal(form: dict[str, Any] | None) -> Signal:
    """Small recent-form signal; never a primary driver."""
    data = _mapping(form)
    games = _first_num(data, "games", "sample_games", "n_games")
    recent_ops = _first_num(data, "recent_ops", "ops_recent", "OPS")
    baseline_ops = _first_num(data, "baseline_ops", "season_ops", "career_ops")
    if games is None or games < 3 or recent_ops is None or baseline_ops is None:
        return Signal(50.0, 0.0, 0.0, False, "recent-form sample unavailable")
    confidence = _clip(games / 15.0, 0.0, 1.0)
    gap = _clip(recent_ops - baseline_ops, -0.250, 0.250)
    score = _clip(50.0 + gap / 0.180 * 30.0, 0.0, 100.0)
    delta = _clip(gap / 0.180 * MAX_RECENT_FORM_DELTA * confidence,
                  -MAX_RECENT_FORM_DELTA, MAX_RECENT_FORM_DELTA)
    return Signal(score, confidence, delta, True, "recent form micro-signal")


def _bullpen_snapshot(row: dict[str, Any], side: str) -> dict[str, Any]:
    features = _mapping(row.get("features"))
    rich = _mapping(row.get("rich_modules"))
    for root in (features, rich):
        for key in (f"{side}_bullpen", f"bullpen_{side}", f"{side}_bullpen_snapshot", f"{side}_bullpen_player"):
            value = root.get(key)
            if isinstance(value, dict):
                return value
    for root in (features, rich):
        for key, value in root.items():
            low = str(key).lower()
            if side in low and "bullpen" in low and isinstance(value, dict):
                return value
    return {}


def _supplemental(row: dict[str, Any], side: str, key: str) -> Any:
    supplemental = _mapping(row.get("v14_supplemental"))
    side_data = _mapping(supplemental.get(side))
    return side_data.get(key)


def context_overlay_from_feature_row(row: dict[str, Any] | None, home_mu: float,
                                     away_mu: float) -> dict[str, Any]:
    """Apply only capped residual corrections to V13.10 run means."""
    base_home, base_away = float(home_mu), float(away_mu)
    no_op = {
        "schema": CONTEXT_SCHEMA,
        "eligible": False,
        "market_probability_used_as_feature": False,
        "home_delta": 0.0,
        "away_delta": 0.0,
        "home_mu": base_home,
        "away_mu": base_away,
        "components": {},
    }
    if not row_is_safe(row):
        no_op["reason"] = "feature row not PIT-safe/eligible"
        return no_op
    assert isinstance(row, dict)

    context = _mapping(row.get("context"))
    rich = _mapping(row.get("rich_modules"))

    away_starter = starter_vulnerability(context.get("away_starter")) if _component_provenance_safe(row, ("starter", "pitcher")) else Signal(50.0, 0.0, 0.0, False, "starter provenance rejected")
    home_starter = starter_vulnerability(context.get("home_starter")) if _component_provenance_safe(row, ("starter", "pitcher")) else Signal(50.0, 0.0, 0.0, False, "starter provenance rejected")
    home_lineup = lineup_strength(context.get("home_lineup"), rich, "home") if _component_provenance_safe(row, ("lineup", "platoon", "statcast")) else Signal(50.0, 0.0, 0.0, False, "lineup provenance rejected")
    away_lineup = lineup_strength(context.get("away_lineup"), rich, "away") if _component_provenance_safe(row, ("lineup", "platoon", "statcast")) else Signal(50.0, 0.0, 0.0, False, "lineup provenance rejected")
    away_bullpen = bullpen_stress(_bullpen_snapshot(row, "away")) if _component_provenance_safe(row, ("bullpen",)) else Signal(50.0, 0.0, 0.0, False, "bullpen provenance rejected")
    home_bullpen = bullpen_stress(_bullpen_snapshot(row, "home")) if _component_provenance_safe(row, ("bullpen",)) else Signal(50.0, 0.0, 0.0, False, "bullpen provenance rejected")

    home_h2h = h2h_micro_signal(_supplemental(row, "home", "h2h"))
    away_h2h = h2h_micro_signal(_supplemental(row, "away", "h2h"))
    home_form = recent_form_signal(_mapping(_supplemental(row, "home", "recent_form")))
    away_form = recent_form_signal(_mapping(_supplemental(row, "away", "recent_form")))

    feature_contract = str(row.get("feature_contract") or "").lower()
    rich_keys = " ".join(str(k).lower() for k in rich)
    starter_guard = 0.35 if ("starter" in rich_keys or "starter" in feature_contract) else 0.45
    lineup_guard = 0.35 if any(x in rich_keys for x in ("lineup", "platoon", "statcast")) else 0.55
    bullpen_guard = 0.35 if "bullpen" in rich_keys else 0.55

    home_delta = away_starter.delta * starter_guard + home_lineup.delta * lineup_guard + away_bullpen.delta * bullpen_guard + home_h2h.delta + home_form.delta
    away_delta = home_starter.delta * starter_guard + away_lineup.delta * lineup_guard + home_bullpen.delta * bullpen_guard + away_h2h.delta + away_form.delta
    home_delta = _clip(home_delta, -MAX_TEAM_DELTA, MAX_TEAM_DELTA)
    away_delta = _clip(away_delta, -MAX_TEAM_DELTA, MAX_TEAM_DELTA)

    return {
        "schema": CONTEXT_SCHEMA,
        "eligible": True,
        "market_probability_used_as_feature": False,
        "home_delta": home_delta,
        "away_delta": away_delta,
        "home_mu": max(0.05, base_home * (1.0 + home_delta)),
        "away_mu": max(0.05, base_away * (1.0 + away_delta)),
        "caps": {"team": MAX_TEAM_DELTA, "starter": MAX_STARTER_DELTA, "lineup": MAX_LINEUP_DELTA, "bullpen": MAX_BULLPEN_DELTA, "h2h": MAX_H2H_DELTA, "recent_form": MAX_RECENT_FORM_DELTA},
        "double_count_guards": {"starter": starter_guard, "lineup": lineup_guard, "bullpen": bullpen_guard},
        "components": {
            "home_offense_vs_away_starter": away_starter.as_dict(),
            "away_offense_vs_home_starter": home_starter.as_dict(),
            "home_lineup": home_lineup.as_dict(),
            "away_lineup": away_lineup.as_dict(),
            "away_bullpen_stress_for_home_offense": away_bullpen.as_dict(),
            "home_bullpen_stress_for_away_offense": home_bullpen.as_dict(),
            "home_h2h_micro": home_h2h.as_dict(),
            "away_h2h_micro": away_h2h.as_dict(),
            "home_recent_form_micro": home_form.as_dict(),
            "away_recent_form_micro": away_form.as_dict(),
        },
    }
