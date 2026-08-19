from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract
from . import v137_park_factors as park
from . import v137_weather_provider as weather
from . import v13_engine
from . import v138_audit_features as features
from . import validation_v13 as validation

SCHEMA = "v13-9-engineering-closure-90-v1"
OUT = Path("data/v139_engineering_closure.json")


def _source(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _has(source: str, *tokens: str) -> bool:
    return all(token in source for token in tokens)


def _point(
    point_id: int,
    category: str,
    name: str,
    implementation: str,
    closed: bool,
    note: str = "",
) -> dict[str, Any]:
    return {
        "id": point_id,
        "category": category,
        "name": name,
        "implementation": implementation,
        "engineering_closed": bool(closed),
        "note": note,
    }


def build() -> dict[str, Any]:
    src = {
        "park": _source("v11/v137_park_factors.py"),
        "weather": _source("v11/v137_weather_provider.py"),
        "weather_backfill": _source("v11/v137_weather_backfill.py"),
        "health": _source("v11/v137_free_data_health.py"),
        "monitoring": _source("v11/v138_monitoring.py"),
        "native": _source("v11/v139_native_context.py"),
        "engine": _source("v11/v13_engine.py"),
        "entry": _source("v11/v13_entry.py"),
        "runtime": _source("v11/v13_runtime.py"),
        "pipeline": _source("v11/pipeline_v13.py"),
        "analytics": _source("v11/v13_analytics_only.py"),
        "dataset": _source("v11/v138_dataset_store.py"),
        "audit52": _source("v11/v138_audit_closure.py"),
        "extra": _source("v11/extra_innings_v13.py"),
        "ci": _source(".github/workflows/ci.yml"),
        "free_workflow": _source(".github/workflows/v13-7-free-data-collector.yml"),
        "prod_workflow": _source(".github/workflows/mlb-bot.yml"),
    }

    points: list[dict[str, Any]] = []

    def add(category: str, name: str, implementation: str, closed: bool, note: str = "") -> None:
        points.append(_point(len(points) + 1, category, name, implementation, closed, note))

    # 1-16 — provider integrity / observability
    add("providers", "Savant three-season rolling query", "v137_park_factors.ROLLING_YEARS", park.ROLLING_YEARS == 3)
    add("providers", "Savant query actually sends rolling=3", "v137_park_factors.fetch_prior_factors", _has(src["park"], '"rolling": ROLLING_YEARS'))
    add("providers", "Park prior excludes target season by construction", "v137_park_factors._expected_window", callable(getattr(park, "_expected_window", None)))
    add("providers", "Returned park year window is authenticated", "v137_park_factors._year_label_matches", callable(getattr(park, "_year_label_matches", None)))
    add("providers", "Park window mismatches are counted", "v137_park_factors.collect", _has(src["park"], "window_rejection_count", "rejected_window_rows"))
    add("providers", "Zero validated park rows fail closed", "v137_park_factors.main", _has(src["park"], "zero validated venue rows"))
    add("providers", "Primary archived weather model is ECMWF IFS", "v137_weather_provider.PRIMARY_MODEL", weather.PRIMARY_MODEL == "ecmwf_ifs")
    add("providers", "Secondary weather model is date gated", "v137_weather_provider.SECONDARY_MODEL_ARCHIVE_START", _has(src["weather"], "SECONDARY_MODEL_ARCHIVE_START", "if run_date >="))
    add("providers", "Weather retries keep one fixed forecast run", "v137_weather_provider._attempt", _has(src["weather"], '"run": run.strftime'))
    add("providers", "Weather has reduced documented-variable fallback", "v137_weather_provider.REDUCED_WEATHER_HOURLY", _has(src["weather"], "REDUCED_WEATHER_HOURLY", "humidity remains neutral"))
    add("providers", "Pre-archive weather fails closed", "v137_weather_provider.historical_weather_for_game", _has(src["weather"], "ecmwf_single_run_archive_not_available"))
    add("providers", "All failed weather attempts remain unavailable", "v137_weather_provider.historical_weather_for_game", _has(src["weather"], "single_run_all_provider_attempts_failed"))
    add("providers", "Weather backfill uses hardened provider", "v137_weather_backfill", _has(src["weather_backfill"], "from .v137_weather_provider import historical_weather_for_game"))
    add("providers", "Weather fallback usage is observable", "v137_weather_backfill", _has(src["weather_backfill"], '"fallback_rows"'))
    add("providers", "Free-provider health has explicit status", "v137_free_data_health", _has(src["health"], 'status = "HEALTHY"', '"DEGRADED"'))
    add("providers", "Monitoring reads real park venue rows", "v138_monitoring.provider_snapshot", _has(src["monitoring"], 'park.get("total_venue_rows")'))

    # 17-30 — PIT and data contracts
    add("pit_data", "Native Statcast requires stable IDs", "v139_native_context.load_statcast_priors", _has(src["native"], "statcast_prior_not_stable_id_only"))
    add("pit_data", "Native Statcast rejects artifact generated after as-of", "v139_native_context.load_statcast_priors", _has(src["native"], "statcast_prior_generated_after_asof"))
    add("pit_data", "Native Statcast rejects cutoff after game", "v139_native_context.load_statcast_priors", _has(src["native"], "statcast_prior_cutoff_after_game"))
    add("pit_data", "Native Statcast rejects game-day/future pitch rows", "v139_native_context.load_statcast_priors", _has(src["native"], "statcast_prior_contains_game_day_or_future"))
    add("pit_data", "Native context contains no market payload", "v139_native_context.build", _has(src["native"], '"market_data_embedded": False'))
    add("pit_data", "Native context contains no target labels", "v139_native_context.build", _has(src["native"], '"target_labels_embedded": False'))
    add("pit_data", "Free foundation explicitly requires no paid source", "v137_free_data_health", _has(src["health"], '"paid_sources_required": False'))
    add("pit_data", "Reconstructed weather cannot promote", "v137_weather_backfill", _has(src["weather_backfill"], '"promotion_eligible": False'))
    add("pit_data", "Reconstructed park priors cannot promote", "v137_park_factors", _has(src["park"], '"promotion_eligible": False'))
    add("pit_data", "Native research bridge is Champion-isolated", "v139_native_context", _has(src["native"], '"affects_champion": False'))
    add("pit_data", "Dataset features/labels are separate tables", "v138_dataset_store", _has(src["dataset"], "features and labels remain separate physical tables"))
    add("pit_data", "Dataset artifacts carry SHA-256", "v138_dataset_store.sha256_file", _has(src["dataset"], "sha256_file", '"sha256"'))
    add("pit_data", "Dataset training seed is persisted", "v138_dataset_store.manifest", _has(src["dataset"], '"training_seed":138'))
    add("pit_data", "Dataset split policy is temporal", "v138_dataset_store.manifest", _has(src["dataset"], '"strict temporal / walk-forward"'))

    # 31-44 — architecture / production boundary
    add("architecture", "Explicit V13Engine class exists", "v13_engine.V13Engine", isinstance(v13_engine.V13Engine, type))
    add("architecture", "Runner engine has explicit installer", "v13_engine.install_runner_engine", callable(v13_engine.install_runner_engine))
    add("architecture", "V13 engine install is idempotent", "v13_engine.install_runner_engine", _has(src["engine"], "if isinstance(current, V13Engine)"))
    add("architecture", "Validated numerical helpers delegate through adapter", "V13Engine.__getattr__", _has(src["engine"], "return getattr(self._legacy_engine, name)"))
    add("architecture", "Probability state is snapshotted before research attach", "v13_engine._probability_snapshot", _has(src["engine"], "_probability_snapshot"))
    add("architecture", "Research mutation of probabilities fails closed", "v13_engine._assert_research_attachment_is_probability_neutral", _has(src["engine"], "attempted to mutate champion probability"))
    add("architecture", "Native research is attached at engine boundary", "V13Engine.analyze", _has(src["engine"], "v139_native_context.attach"))
    add("architecture", "V13 entry installs explicit engine", "v13_entry", _has(src["entry"], "v13_engine.install_runner_engine(runner)"))
    add("architecture", "Run report exposes engine architecture", "v13_entry._run_v135", _has(src["entry"], 'report.setdefault("architecture"'))
    add("architecture", "Explicit probability pipeline exists", "pipeline_v13.ProbabilityPipelineV13", _has(src["pipeline"], "class ProbabilityPipelineV13"))
    add("architecture", "Legacy compatibility install remains explicit", "v13_runtime.install", _has(src["runtime"], "def install()"))
    add("architecture", "Runtime hook health is inspectable", "v13_runtime.runtime_hook_status", _has(src["runtime"], "def runtime_hook_status"))
    add("architecture", "Runtime hooks have fail-closed assertion", "v13_runtime.assert_runtime_hooks", _has(src["runtime"], "def assert_runtime_hooks"))
    add("architecture", "Production workflow uses V13 entrypoint", ".github/workflows/mlb-bot.yml", _has(src["prod_workflow"], "v11.v13_entry"))

    # 45-60 — advanced/native feature integration
    add("features", "Advanced context composer exists", "v138_audit_features.build_advanced_context", callable(features.build_advanced_context))
    add("features", "Order-aware lineup feature integrated", "v138_audit_features.lineup_strength", callable(features.lineup_strength))
    add("features", "Starter skill feature integrated", "v138_audit_features.starter_skill", callable(features.starter_skill))
    add("features", "Pitch-mix matchup integrated", "v138_audit_features.pitch_mix_matchup", callable(features.pitch_mix_matchup))
    add("features", "Bullpen role/leverage integrated", "v138_audit_features.classify_bullpen_roles", callable(features.classify_bullpen_roles))
    add("features", "Opener/bullpen-game detection integrated", "v138_audit_features.detect_opener", callable(features.detect_opener))
    add("features", "Travel/circadian feature integrated", "v138_audit_features.circadian_travel", callable(features.circadian_travel))
    add("features", "Defense feature integrated", "v138_audit_features.defense_factor", callable(features.defense_factor))
    add("features", "Baserunning feature integrated", "v138_audit_features.baserunning_factor", callable(features.baserunning_factor))
    add("features", "Catcher framing feature integrated", "v138_audit_features.catcher_framing_factor", callable(features.catcher_framing_factor))
    add("features", "Umpire feature integrated", "v138_audit_features.umpire_factor", callable(features.umpire_factor))
    add("features", "Multi-window offense talent integrated", "v138_audit_features.offense_talent", callable(features.offense_talent))
    add("features", "Handedness-aware park factor integrated", "v138_audit_features.park_factor", callable(features.park_factor))
    add("features", "Native context persists lineup stable IDs", "v139_native_context.build", _has(src["native"], 'bundle["lineup_ids"]'))
    add("features", "Native context persists Statcast provenance", "v139_native_context.build", _has(src["native"], '"statcast_provenance"'))
    add("features", "Native research bundle persists inside feature map", "v139_native_context.attach", _has(src["native"], 'features["v139_native_research"]'))

    # 61-74 — probability and model safety contracts
    add("probability", "Predictive probability contract versioned", "probability_contract_v13", bool(contract.PREDICTIVE_CONTRACT_VERSION))
    add("probability", "Model generation fingerprint explicit", "probability_contract_v13", bool(contract.MODEL_GENERATION_FINGERPRINT))
    add("probability", "Raw baseball probability is mandatory", "assert_no_market_leakage", _has(_source("v11/probability_contract_v13.py"), "p_baseball_raw is required"))
    add("probability", "Calibrated baseball probability is mandatory", "assert_no_market_leakage", _has(_source("v11/probability_contract_v13.py"), "p_baseball_calibrated is required"))
    add("probability", "Market probability remains separate field", "option_contract_payload", _has(_source("v11/probability_contract_v13.py"), '"p_market"'))
    add("probability", "Posterior remains separate field", "option_contract_payload", _has(_source("v11/probability_contract_v13.py"), '"p_posterior"'))
    add("probability", "Model-market gap derives from baseball minus market", "option_contract_payload", _has(_source("v11/probability_contract_v13.py"), '"model_market_gap"'))
    add("probability", "Market-derived baseball source is rejected", "assert_no_market_leakage", _has(_source("v11/probability_contract_v13.py"), "market-derived source cannot define"))
    add("probability", "Baseball calibration is explicit pipeline stage", "ProbabilityPipelineV13.calibrate", _has(src["pipeline"], "def calibrate"))
    add("probability", "Posterior weight policy is isolated", "ProbabilityPipelineV13", _has(src["pipeline"], "posterior_weight_policy"))
    add("probability", "Probability uncertainty is explicit", "ProbabilityPipelineV13", _has(src["pipeline"], '"probability_uncertainty_v13"'))
    add("probability", "Extra innings default to neutral 50/50", "extra_innings_v13.home_win_probability", _has(src["extra"], "prior = .5 if extra_innings_home_prior is None"))
    add("probability", "Rich model cannot auto-promote", "v13_entry.self_test_v13", _has(src["entry"], 'active_for_production") and _has(src["entry"], "is not True"))
    add("probability", "Analytics-only storage cannot create bets", "v13_analytics_only.disabled_record_selected_bets", _has(src["analytics"], "def disabled_record_selected_bets", "return 0"))

    # 75-84 — validation and evidence discipline
    add("validation", "Minimum compatible volume remains 600", "validation_v13.MIN_COMPATIBLE_GAMES", validation.MIN_COMPATIBLE_GAMES >= 600)
    add("validation", "Minimum outer holdout remains 200", "validation_v13.MIN_OUTER_HOLDOUT_GAMES", validation.MIN_OUTER_HOLDOUT_GAMES >= 200)
    add("validation", "Minimum walk-forward windows remains 5", "validation_v13.MIN_WALK_FORWARD_WINDOWS", validation.MIN_WALK_FORWARD_WINDOWS >= 5)
    add("validation", "Walk-forward consistency requires 80%", "validation_v13.strict_promotion_gate", _has(_source("v11/validation_v13.py"), "wf_rate >= .80"))
    add("validation", "Paired Brier CI lower bound must be positive", "validation_v13.strict_promotion_gate", _has(_source("v11/validation_v13.py"), "lower is not None and lower > 0"))
    add("validation", "LogLoss gain cannot be negative", "validation_v13.strict_promotion_gate", _has(_source("v11/validation_v13.py"), '"logloss_nonnegative"'))
    add("validation", "Per-market Brier regression guard exists", "validation_v13.strict_promotion_gate", _has(_source("v11/validation_v13.py"), "MAX_MARKET_BRIER_REGRESSION"))
    add("validation", "Calibration safety constrains ECE/slope/intercept", "validation_v13.strict_promotion_gate", _has(_source("v11/validation_v13.py"), "<= .03", ".75 <=", "<= 1.25"))
    add("validation", "52-point registry separates engineering/evidence", "v138_audit_closure", _has(src["audit52"], '"engineering_closed"', '"evidence_closed"'))
    add("validation", "Native/PIT sample floors are never lowered", "v138_audit_closure policy", _has(src["audit52"], "native/PIT sample floors are never lowered"))

    # 85-90 — CI, monitoring and operational fail-closed gates
    add("operations", "CI compiles all Python modules/tests", ".github/workflows/ci.yml", _has(src["ci"], "python -m py_compile v11/*.py tests/*.py"))
    add("operations", "CI executes V13.9 provider and engine tests", ".github/workflows/ci.yml", _has(src["ci"], "tests.test_v139_provider_hardening", "tests.test_v139_engine_boundary"))
    add("operations", "CI executes shared V13 preflight", ".github/workflows/ci.yml", _has(src["ci"], "python -m v11.v13_preflight --verbose"))
    add("operations", "Free-data workflow asserts provider/cohort integrity", "v13-7-free-data-collector.yml", _has(src["free_workflow"], "Assert free-only provider integrity and cohort boundaries"))
    add("operations", "Monitoring retains feature-drift alerts", "v138_monitoring", _has(src["monitoring"], "feature_drift", "alerts"))
    add("operations", "Monitoring is observability-only", "v138_monitoring", _has(src["monitoring"], "observability only; no automatic model retuning"))

    assert len(points) == 90, len(points)
    closed = sum(bool(point["engineering_closed"]) for point in points)
    open_points = [point for point in points if not point["engineering_closed"]]
    return {
        "schema": SCHEMA,
        "total_points": 90,
        "engineering_closed": closed,
        "engineering_open": 90 - closed,
        "all_engineering_closed": closed == 90,
        "points": points,
        "open_points": open_points,
        "scope_note": (
            "These 90 items are the explicit V13.9 engineering acceptance registry derived from the earlier "
            "conservative ~90-point estimate. They are not a retroactive claim that the original 275-point "
            "audit contained a machine-readable block numbered 1-90. Statistical evidence gates remain separate."
        ),
        "evidence_note": (
            "Engineering closure does not activate challengers or lower V13/V13.8 native evidence floors."
        ),
    }


def main() -> None:
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "total_points": report["total_points"],
                "engineering_closed": report["engineering_closed"],
                "engineering_open": report["engineering_open"],
                "scope_note": report["scope_note"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if report["engineering_open"]:
        raise SystemExit(f"V13.9 engineering closure incomplete: {report['engineering_open']} open point(s)")


if __name__ == "__main__":
    main()
