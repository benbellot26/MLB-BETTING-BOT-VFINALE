from __future__ import annotations

"""Explicit ownership contract for probability-bearing V14 feature families.

The structural, contextual and advanced layers intentionally operate on
residual information. This registry makes that separation machine-auditable:
a canonical feature family has exactly one probability-bearing owner. Related
signals may coexist only when their IDs describe different residual information
(e.g. raw outdoor weather vs venue-relative flight physics).

This module never changes a probability. It is a governance/preflight guard.
"""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FeatureClaim:
    feature_id:str
    owner:str
    description:str


CLAIMS=(
    # Structural champion.
    FeatureClaim("team_runs_per_game","STRUCTURAL","season team scoring baseline"),
    FeatureClaim("team_ops","STRUCTURAL","season team OPS baseline"),
    FeatureClaim("confirmed_lineup_ops","STRUCTURAL","confirmed lineup OPS already consumed structurally"),
    FeatureClaim("starter_era_whip_shrinkage","STRUCTURAL","starter run prevention baseline and shrinkage"),
    FeatureClaim("previous_game_bullpen_usage","STRUCTURAL","prior-game bullpen load"),
    FeatureClaim("rest_travel_approx_timezone","STRUCTURAL","rest/travel and approximate timezone context"),
    FeatureClaim("static_park_factor","STRUCTURAL","park run environment baseline"),

    # Context residual layer. These IDs are deliberately narrower than the
    # advanced Statcast IDs below so the same raw concept cannot be claimed twice.
    FeatureClaim("starter_season_k9_bb9_hr9_residual","CONTEXT","season K/BB/HR profile residual beyond ERA/WHIP"),
    FeatureClaim("three_day_bullpen_availability_residual","CONTEXT","multi-day bullpen availability beyond previous game"),
    FeatureClaim("raw_outdoor_weather_residual","CONTEXT","bounded raw temperature/wind/precipitation residual"),
    FeatureClaim("legacy_rich_lineup_residual","CONTEXT","legacy rich/platoon residual only when independently sourced"),

    # V14.6 all-stats residual layer.
    FeatureClaim("statcast_lineup_contact_quality","ALL_STATS","lineup xwOBA/hard-hit/barrel/K-BB contact quality"),
    FeatureClaim("pitch_type_arsenal_matchup","ALL_STATS","starter arsenal x hitter pitch-type matchup"),
    FeatureClaim("pitcher_hand_matchup","ALL_STATS","lineup performance versus probable pitcher hand"),
    FeatureClaim("statcast_starter_quality","ALL_STATS","starter xwOBA allowed/contact/K-BB/velocity"),
    FeatureClaim("statcast_bullpen_quality","ALL_STATS","bullpen xwOBA allowed/contact/K-BB quality"),
    FeatureClaim("defense_catcher_run_value","ALL_STATS","fielding and catcher run-value residual"),
    FeatureClaim("baserunning_run_value","ALL_STATS","baserunning run-value residual"),
    FeatureClaim("exact_timezone_residual","ALL_STATS","exact minus approximate timezone correction"),
    FeatureClaim("venue_relative_flight_physics","ALL_STATS","venue/month-relative air/wind flight residual"),
)

REQUIRED_OWNERS={"STRUCTURAL","CONTEXT","ALL_STATS"}


def claims_by_owner()->dict[str,list[FeatureClaim]]:
    out={owner:[] for owner in REQUIRED_OWNERS}
    for claim in CLAIMS:out.setdefault(claim.owner,[]).append(claim)
    return out


def duplicate_feature_ids(claims:Iterable[FeatureClaim]=CLAIMS)->dict[str,list[str]]:
    seen:dict[str,list[str]]={}
    for claim in claims:seen.setdefault(claim.feature_id,[]).append(claim.owner)
    return {feature:owners for feature,owners in seen.items() if len(owners)>1}


def assert_no_probability_feature_overlap(claims:Iterable[FeatureClaim]=CLAIMS)->None:
    rows=tuple(claims);duplicates=duplicate_feature_ids(rows)
    if duplicates:raise RuntimeError(f"probability feature ownership overlap: {duplicates}")
    owners={claim.owner for claim in rows}
    missing=REQUIRED_OWNERS-owners
    if missing:raise RuntimeError(f"probability feature ownership missing layer(s): {sorted(missing)}")
    for claim in rows:
        if not claim.feature_id.strip() or not claim.description.strip():raise RuntimeError("blank feature ownership claim")


def contract_payload()->dict[str,object]:
    assert_no_probability_feature_overlap()
    grouped=claims_by_owner()
    return {
        "schema":"pulsar-v14-feature-ownership-v1",
        "market_probability_used_as_feature":False,
        "owners":{owner:[claim.feature_id for claim in grouped.get(owner,[])] for owner in sorted(grouped)},
        "duplicate_feature_ids":{},
        "policy":"one canonical probability-bearing feature family -> one production owner; distinct residual transforms require distinct IDs",
    }


assert_no_probability_feature_overlap()
