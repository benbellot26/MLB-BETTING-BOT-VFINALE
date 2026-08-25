from __future__ import annotations

"""Conservative point-in-time residual overlay for Pulsar V14.

The structural model already consumes team offense, lineup OPS, ERA/WHIP,
starter shrinkage, prior-game bullpen usage, travel/rest and park. This overlay
therefore applies only information that is genuinely incremental:
- starter K/BB/HR profile not consumed by structural starter quality;
- advanced lineup/Statcast/platoon modules, never lineup OPS again;
- three-day bullpen availability beyond the structural previous-game summary;
- bounded weather/roof context;
- H2H and recent form remain explicitly disabled pending live validation.
"""

from dataclasses import asdict, dataclass
import math
import re
from typing import Any

CONTEXT_SCHEMA = "v14-context-residual-v2"
MAX_TEAM_DELTA = 0.025
MAX_STARTER_DELTA = 0.010
MAX_LINEUP_DELTA = 0.012
MAX_BULLPEN_DELTA = 0.012
MAX_ENVIRONMENT_DELTA = 0.020
MAX_H2H_DELTA = 0.0
MAX_RECENT_FORM_DELTA = 0.0


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
    provenance = _mapping(row.get("feature_provenance"))
    if not provenance:
        return True
    candidates: list[dict[str, Any]] = []
    for key, value in provenance.items():
        low = str(key).lower()
        if any(alias in low for alias in aliases) and isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        if candidate.get("postgame_identity") is True:
            return False
        if candidate.get("point_in_time") is False:
            return False
        # Only an explicit False is rejected. None means the source does not
        # expose its own timestamp; retrieval time still provides PIT evidence.
        if candidate.get("source_timestamp_attested") is False and candidate.get("retrieval_timestamp_attested") is not True:
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
    identity = data.get("id") or data.get("player_id") or data.get("pitcher_id") or data.get("name") or data.get("fullName")
    if not identity:
        return {}, 0.0
    stats = _nested_first(data, ("season_stats", "current_stats", "stats", "pitching", "season", "current")) or data
    ip = _first_num(stats, "inningsPitched", "innings_pitched", "ip", "IP")
    if ip is None:
        ip = _first_num(data, "inningsPitched", "innings_pitched", "ip", "IP")
    return stats, max(0.0, ip or 0.0)


def starter_vulnerability(starter: dict[str, Any] | None, advanced: dict[str, Any] | None = None) -> Signal:
    """Residual starter signal using metrics not consumed by structural ERA/WHIP."""
    stats, ip = _starter_stats(starter)
    if not stats:
        return Signal(50.0, 0.0, 0.0, False, "starter identity/stats unavailable")
    k9 = _first_num(stats, "strikeoutsPer9Inn", "k9", "K9", "k_per_9")
    bb9 = _first_num(stats, "walksPer9Inn", "bb9", "BB9", "bb_per_9")
    hr9 = _first_num(stats, "homeRunsPer9", "homeRunsPer9Inn", "hr9", "HR9")
    advanced_data = _mapping(advanced)
    k_minus_bb = _first_num(advanced_data, "k_minus_bb")
    xera_gap = _first_num(advanced_data, "xera_minus_era", "xera_gap")

    contributions: list[tuple[float, float]] = []
    if k9 is not None:
        contributions.append((_clip((8.40 - k9) / 3.00, -1.0, 1.0), 0.35))
    if bb9 is not None:
        contributions.append((_clip((bb9 - 3.05) / 2.00, -1.0, 1.0), 0.30))
    if hr9 is not None:
        contributions.append((_clip((hr9 - 1.18) / 0.95, -1.0, 1.0), 0.35))
    if k_minus_bb is not None:
        contributions.append((_clip((0.142 - k_minus_bb) / 0.10, -1.0, 1.0), 0.25))
    if xera_gap is not None:
        contributions.append((_clip(xera_gap / 1.25, -1.0, 1.0), 0.20))
    if len(contributions) < 2:
        return Signal(50.0, 0.0, 0.0, False, "no independent starter residual metrics")

    weight = sum(w for _, w in contributions)
    centered = sum(v * w for v, w in contributions) / max(1e-12, weight)
    score = _clip(50.0 + 40.0 * centered, 0.0, 100.0)
    sample_conf = _clip(ip / 120.0, 0.20, 1.0) if ip > 0 else 0.35
    metric_conf = _clip(len(contributions) / 4.0, 0.0, 1.0)
    confidence = sample_conf * metric_conf
    delta = _clip(centered * MAX_STARTER_DELTA * confidence, -MAX_STARTER_DELTA, MAX_STARTER_DELTA)
    return Signal(score, confidence, delta, True, "residual starter K/BB/HR profile")


def _lineup_players(lineup: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(lineup, list):
        players = [p for p in lineup if isinstance(p, dict)]
        return players, len(players) >= 9
    data = _mapping(lineup)
    players: list[dict[str, Any]] = []
    for key in ("players", "lineup", "ordered", "batters", "starting_lineup"):
        value = data.get(key)
        if isinstance(value, list):
            players = [p for p in value if isinstance(p, dict)]
            if players:
                break
    confirmed = bool(data.get("confirmed") or data.get("is_confirmed") or str(data.get("status") or "").upper() in {"CONFIRMED", "OFFICIAL"})
    return players, confirmed and len(players) >= 9


def _player_ops(player: dict[str, Any]) -> float | None:
    direct = _first_num(player, "ops", "OPS")
    if direct is not None:
        return direct
    stats = _nested_first(player, ("stats", "season_stats", "hitting", "season"))
    return _first_num(stats, "ops", "OPS")


def lineup_strength(lineup: Any, rich_modules: dict[str, Any] | None = None, side: str | None = None) -> Signal:
    """Only advanced lineup residuals may move the model; OPS is diagnostic."""
    players, confirmed = _lineup_players(lineup)
    if not confirmed:
        return Signal(50.0, 0.0, 0.0, False, "lineup not confirmed 9/9")

    ops_values = [x for x in (_player_ops(p) for p in players[:9]) if x is not None]
    baseline_score = 50.0
    if len(ops_values) >= 5:
        baseline_score = _clip(50.0 + ((sum(ops_values) / len(ops_values)) - 0.725) / 0.125 * 40.0, 0.0, 100.0)

    rich = _mapping(rich_modules)
    side_key = str(side or "").lower()
    modules: list[dict[str, Any]] = []
    side_block = _mapping(rich.get(side_key)) if side_key else {}
    for nested_key in ("lineup", "statcast_lineup", "platoon", "lineup_statcast"):
        nested = side_block.get(nested_key)
        if isinstance(nested, dict):
            modules.append(nested)
    for key, value in rich.items():
        low = str(key).lower()
        if isinstance(value, dict) and (not side_key or side_key in low) and any(token in low for token in ("lineup", "statcast", "platoon")):
            modules.append(value)

    residuals: list[tuple[float, float]] = []
    for module in modules:
        status = str(module.get("status") or module.get("state") or "").upper()
        if status and status not in {"ACTIVE", "OK", "READY"}:
            continue
        xwoba = _first_num(module, "xwoba", "lineup_xwoba", "avg_xwoba", "mean_xwoba")
        if xwoba is not None:
            residuals.append((_clip((xwoba - 0.320) / 0.055, -1.0, 1.0), 0.55))
        platoon = _first_num(module, "platoon_factor", "factor_vs_hand")
        if platoon is not None:
            residuals.append((_clip((platoon - 1.0) / 0.10, -1.0, 1.0), 0.30))
        factor = _first_num(module, "factor", "lineup_factor", "offense_factor")
        if factor is not None:
            residuals.append((_clip((factor - 1.0) / 0.10, -1.0, 1.0), 0.15))

    if not residuals:
        return Signal(baseline_score, 0.0, 0.0, False, "lineup OPS already consumed structurally; no advanced residual")
    weight = sum(w for _, w in residuals)
    centered = sum(v * w for v, w in residuals) / max(weight, 1e-12)
    confidence = _clip(len(residuals) / 3.0, 0.35, 1.0)
    score = _clip(50.0 + 40.0 * centered, 0.0, 100.0)
    delta = _clip(centered * MAX_LINEUP_DELTA * confidence, -MAX_LINEUP_DELTA, MAX_LINEUP_DELTA)
    return Signal(score, confidence, delta, True, "advanced lineup residual")


def _relievers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("relievers", "pitchers", "bullpen", "players"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def bullpen_stress(snapshot: dict[str, Any] | None) -> Signal:
    data = _mapping(snapshot)
    relievers = _relievers(data)
    coverage = _first_num(data, "coverage", "coverage_ratio", "player_coverage")
    if coverage is None and relievers:
        coverage = min(1.0, len(relievers) / 7.0)
    if (coverage or 0.0) < 0.45 or len(relievers) < 3:
        return Signal(50.0, 0.0, 0.0, False, "three-day bullpen coverage insufficient")

    taxed = unavailable = repeat = 0
    pitches3: list[float] = []
    for reliever in relievers:
        if reliever.get("taxed") is True:
            taxed += 1
        if reliever.get("available") is False or reliever.get("likely_unavailable") is True:
            unavailable += 1
        uses = _first_num(reliever, "uses_last_3d", "appearances_last_3d")
        if uses is not None and uses >= 2:
            repeat += 1
        p3 = _first_num(reliever, "pitches_last_3d", "pitch_count_last_3d")
        if p3 is not None:
            pitches3.append(p3)

    n = max(1, len(relievers))
    workload = 0.38 * _clip(taxed / n / 0.45, 0.0, 1.0)
    workload += 0.34 * _clip(unavailable / n / 0.30, 0.0, 1.0)
    workload += 0.18 * _clip(repeat / n / 0.45, 0.0, 1.0)
    if pitches3:
        workload += 0.10 * _clip((sum(pitches3) / len(pitches3)) / 45.0, 0.0, 1.0)
    score = _clip(100.0 * workload, 0.0, 100.0)
    confidence = _clip(float(coverage), 0.0, 1.0)
    # Neutral around moderate normal workload. This is incremental to the
    # structural previous-game bullpen adjustment, not a second copy of it.
    delta = _clip(((score - 40.0) / 60.0) * MAX_BULLPEN_DELTA * confidence, -MAX_BULLPEN_DELTA, MAX_BULLPEN_DELTA)
    return Signal(score, confidence, delta, True, "three-day bullpen availability residual")


def environment_signal(environment: dict[str, Any] | None) -> Signal:
    data = _mapping(environment)
    if not data or data.get("available") is not True:
        return Signal(50.0, 0.0, 0.0, False, "weather/roof unavailable")
    roof = str(data.get("roof") or "").lower()
    condition = str(data.get("condition") or "").lower()
    if any(token in roof for token in ("dome", "closed", "roofed")):
        return Signal(50.0, 1.0, 0.0, True, "closed/indoor roof neutralizes weather")

    delta = 0.0
    evidence = 0
    temp = _num(data.get("temperature_f"))
    if temp is not None:
        evidence += 1
        if temp > 75:
            delta += min(0.012, (temp - 75.0) * 0.0008)
        elif temp < 60:
            delta -= min(0.012, (60.0 - temp) * 0.0008)
    wind = str(data.get("wind") or "").lower()
    mph = _num(data.get("wind_mph"))
    if mph is None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*mph", wind)
        mph = float(match.group(1)) if match else None
    if mph is not None and mph >= 8:
        evidence += 1
        magnitude = min(0.010, (mph - 7.0) * 0.0007)
        if "out" in wind:
            delta += magnitude
        elif "in" in wind:
            delta -= magnitude
    if any(token in condition for token in ("rain", "drizzle", "snow")):
        evidence += 1
        delta -= 0.004
    delta = _clip(delta, -MAX_ENVIRONMENT_DELTA, MAX_ENVIRONMENT_DELTA)
    confidence = _clip(evidence / 2.0, 0.25 if evidence else 0.0, 1.0)
    score = _clip(50.0 + (delta / MAX_ENVIRONMENT_DELTA) * 40.0 if MAX_ENVIRONMENT_DELTA else 50.0, 0.0, 100.0)
    return Signal(score, confidence, delta * confidence, evidence > 0, "bounded outdoor weather residual")


def h2h_micro_signal(records: Any) -> Signal:
    return Signal(50.0, 0.0, 0.0, False, "H2H disabled pending live out-of-sample validation")


def recent_form_signal(form: dict[str, Any] | None) -> Signal:
    return Signal(50.0, 0.0, 0.0, False, "recent form disabled pending live out-of-sample validation")


def _bullpen_snapshot(row: dict[str, Any], side: str) -> dict[str, Any]:
    features = _mapping(row.get("features"))
    bullpen = _mapping(features.get("bullpen"))
    value = bullpen.get(side)
    return value if isinstance(value, dict) else {}


def context_overlay_from_feature_row(row: dict[str, Any] | None, home_mu: float, away_mu: float) -> dict[str, Any]:
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
    home_rich = _mapping(rich.get("home"))
    away_rich = _mapping(rich.get("away"))

    away_starter = starter_vulnerability(context.get("away_starter"), _mapping(home_rich.get("starter_against"))) if _component_provenance_safe(row, ("starter", "pitcher")) else Signal(50, 0, 0, False, "starter provenance rejected")
    home_starter = starter_vulnerability(context.get("home_starter"), _mapping(away_rich.get("starter_against"))) if _component_provenance_safe(row, ("starter", "pitcher")) else Signal(50, 0, 0, False, "starter provenance rejected")
    home_lineup = lineup_strength(context.get("home_lineup"), rich, "home") if _component_provenance_safe(row, ("lineup", "platoon", "statcast")) else Signal(50, 0, 0, False, "lineup provenance rejected")
    away_lineup = lineup_strength(context.get("away_lineup"), rich, "away") if _component_provenance_safe(row, ("lineup", "platoon", "statcast")) else Signal(50, 0, 0, False, "lineup provenance rejected")
    away_bullpen = bullpen_stress(_bullpen_snapshot(row, "away"))
    home_bullpen = bullpen_stress(_bullpen_snapshot(row, "home"))
    environment = environment_signal(_mapping((_mapping(row.get("features"))).get("environment")))
    home_h2h = h2h_micro_signal(None)
    away_h2h = h2h_micro_signal(None)
    home_form = recent_form_signal(None)
    away_form = recent_form_signal(None)

    home_delta = _clip(away_starter.delta + home_lineup.delta + away_bullpen.delta + environment.delta, -MAX_TEAM_DELTA, MAX_TEAM_DELTA)
    away_delta = _clip(home_starter.delta + away_lineup.delta + home_bullpen.delta + environment.delta, -MAX_TEAM_DELTA, MAX_TEAM_DELTA)

    return {
        "schema": CONTEXT_SCHEMA,
        "eligible": True,
        "market_probability_used_as_feature": False,
        "home_delta": home_delta,
        "away_delta": away_delta,
        "home_mu": max(0.05, base_home * (1.0 + home_delta)),
        "away_mu": max(0.05, base_away * (1.0 + away_delta)),
        "caps": {
            "team": MAX_TEAM_DELTA,
            "starter": MAX_STARTER_DELTA,
            "lineup": MAX_LINEUP_DELTA,
            "bullpen": MAX_BULLPEN_DELTA,
            "environment": MAX_ENVIRONMENT_DELTA,
            "h2h": MAX_H2H_DELTA,
            "recent_form": MAX_RECENT_FORM_DELTA,
        },
        "double_count_policy": "only residual signals not already consumed by structural model",
        "components": {
            "home_offense_vs_away_starter_residual": away_starter.as_dict(),
            "away_offense_vs_home_starter_residual": home_starter.as_dict(),
            "home_lineup_residual": home_lineup.as_dict(),
            "away_lineup_residual": away_lineup.as_dict(),
            "away_bullpen_three_day_for_home": away_bullpen.as_dict(),
            "home_bullpen_three_day_for_away": home_bullpen.as_dict(),
            "shared_environment": environment.as_dict(),
            "home_h2h_micro": home_h2h.as_dict(),
            "away_h2h_micro": away_h2h.as_dict(),
            "home_recent_form_micro": home_form.as_dict(),
            "away_recent_form_micro": away_form.as_dict(),
        },
    }
