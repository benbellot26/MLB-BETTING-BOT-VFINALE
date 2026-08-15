from __future__ import annotations

import math

from . import core

VERSION = "v12.4-starter-ip-v2-shadow-v1"
REFERENCE_STARTER_IP = 5.10
DEFAULT_SHRINK = 0.50


def _num(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _ratio(value, baseline, lo, hi):
    return max(lo, min(hi, _num(value, baseline) / max(1e-9, _num(baseline, 1.0))))


def _clip(value, lo, hi):
    return max(lo, min(hi, _num(value)))


def expected_starter_ip_v2(starter):
    """Estimate duration without reusing pitcher quality.

    V1 used ERA/WHIP both in expected duration and pitcher quality. V2 makes
    duration depend on demonstrated workload only, shrunk toward a league-like
    5.1 IP reference. Pitcher quality is handled separately by starter_quality.
    """
    starter = starter or {}
    pid = starter.get("id")
    st = core.player_stats(pid, "pitching") if pid else {}
    ip = _num(st.get("inningsPitched"), _num(starter.get("innings"), 0.0))
    starts = max(0.0, _num(st.get("gamesStarted"), 0.0))
    games = max(0.0, _num(st.get("gamesPitched"), starts))
    denom = starts if starts >= 2 else games if games >= 2 else 0.0
    avg = ip / denom if denom else REFERENCE_STARTER_IP
    sample = min(1.0, starts / 12.0) if starts else min(1.0, ip / 70.0)
    expected = sample * avg + (1.0 - sample) * REFERENCE_STARTER_IP
    return _clip(expected, 4.0, 6.7), {
        "season_ip": ip,
        "starts": starts,
        "games": games,
        "avg_ip_per_start": avg,
        "sample": sample,
        "quality_used_for_duration": False,
    }


def _pitcher_quality_from_stats(stats):
    lg = core.league_baselines()
    lgera = _num(lg.get("era"), 4.35)
    lgwhip = _num(lg.get("whip"), 1.32)
    stats = stats or {}
    ip = max(0.0, _num(stats.get("inningsPitched"), 0.0))
    if ip <= 0:
        return None
    era = _num(stats.get("era"), lgera)
    whip = _num(stats.get("whip"), lgwhip)
    k9 = _num(stats.get("strikeoutsPer9Inn"), 8.6)
    bb9 = _num(stats.get("walksPer9Inn"), 3.2)
    hr9 = _num(stats.get("homeRunsPer9"), 1.15)
    quality = (
        .43 * _ratio(era, lgera, .60, 1.55)
        + .20 * _ratio(whip, lgwhip, .65, 1.45)
        + .14 * _ratio(bb9, 3.2, .55, 1.65)
        + .13 * _ratio(hr9, 1.15, .45, 1.80)
        + .10 * _ratio(8.6, max(3.5, k9), .60, 1.55)
    )
    # Small-sample shrinkage prevents a reliever with a handful of innings from
    # dominating the bullpen estimate.
    reliability = min(1.0, ip / 35.0)
    return reliability * quality + (1.0 - reliability) * 1.0


def _bullpen_quality(result, side):
    bullpen = (((result.get("features") or {}).get("bullpen") or {}).get(side) or {})
    relievers = list(bullpen.get("relievers") or [])
    values = []
    for reliever in relievers:
        pid = reliever.get("id")
        if not pid:
            continue
        stats = core.player_stats(pid, "pitching") or {}
        quality = _pitcher_quality_from_stats(stats)
        if quality is None:
            continue
        pitches_3d = max(0.0, _num(reliever.get("pitches_3d"), 0.0))
        days_used = max(0.0, _num(reliever.get("days_used"), 0.0))
        # Availability is a weighting term, not a quality penalty: heavily used
        # arms simply contribute less to the expected bullpen mix.
        availability = _clip(1.0 - pitches_3d / 150.0 - .08 * max(0.0, days_used - 1.0), .20, 1.0)
        ip = max(0.0, _num(stats.get("inningsPitched"), 0.0))
        role_weight = .60 + .40 * min(1.0, ip / 45.0)
        weight = availability * role_weight
        values.append((quality, weight))
    if not values:
        return 1.0, 0.0, {"usable_relievers": 0, "listed_relievers": len(relievers)}
    quality = sum(q * w for q, w in values) / max(1e-9, sum(w for _, w in values))
    coverage = min(1.0, len(values) / 7.0)
    quality = coverage * quality + (1.0 - coverage) * 1.0
    return quality, coverage, {"usable_relievers": len(values), "listed_relievers": len(relievers)}


def starter_ip_module_v2(result, active=True, shrink=DEFAULT_SHRINK):
    from . import predictive_v124 as v124

    out = v124._module_base("starter_ip", active)
    if not active:
        return out
    factors = {}
    details = {}
    coverage_sum = 0.0
    shrink = _clip(shrink, 0.0, 1.0)

    for offense, defense in (("home", "away"), ("away", "home")):
        starter = v124._starter(result, defense)
        exp_ip, meta = expected_starter_ip_v2(starter)
        starter_q = v124._starter_quality(starter)
        bullpen_q, bullpen_cov, bullpen_meta = _bullpen_quality(result, defense)

        dynamic_share = exp_ip / 9.0
        reference_share = REFERENCE_STARTER_IP / 9.0
        dynamic_mix = dynamic_share * starter_q + (1.0 - dynamic_share) * bullpen_q
        reference_mix = reference_share * starter_q + (1.0 - reference_share) * bullpen_q
        raw_factor = dynamic_mix / max(.70, reference_mix)

        # Only the marginal duration effect is applied. Absolute starter/bullpen
        # quality is intentionally not re-applied on top of the structural model.
        factor = 1.0 + shrink * (raw_factor - 1.0)
        factor = _clip(factor, .975, 1.025)
        starter_cov = 1.0 if starter.get("id") else 0.0
        coverage = starter_cov * (.50 + .50 * bullpen_cov)
        coverage_sum += coverage
        factors[offense] = factor
        details[offense] = {
            "defense": defense,
            "expected_ip": exp_ip,
            "reference_ip": REFERENCE_STARTER_IP,
            "starter_quality": starter_q,
            "bullpen_quality": bullpen_q,
            "bullpen_coverage": bullpen_cov,
            "dynamic_mix": dynamic_mix,
            "reference_mix": reference_mix,
            "raw_marginal_factor": raw_factor,
            "shrink": shrink,
            "factor": factor,
            "duration_quality_decoupled": True,
            "absolute_pitching_quality_reapplied": False,
            **bullpen_meta,
            **meta,
        }

    out.update({
        "home_factor": factors.get("home", 1.0),
        "away_factor": factors.get("away", 1.0),
        "coverage": coverage_sum / 2.0,
        "details": details,
        "status": "ACTIVE" if coverage_sum >= 1.25 else "LOW_COVERAGE",
        "version": VERSION,
    })
    return out


def install():
    """Install V2 only into V12.4 shadow. Production V12.3.2 is untouched."""
    from . import predictive_v124 as v124
    if getattr(v124, "_starter_ip_v2_installed", False):
        return True
    v124.expected_starter_ip = expected_starter_ip_v2
    v124.starter_ip_module = starter_ip_module_v2
    v124._starter_ip_v2_installed = True
    return True
