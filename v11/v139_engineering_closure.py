from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import probability_contract_v13 as contract
from . import v137_park_factors as park
from . import v137_weather_provider as weather
from . import v13_engine
from . import v138_audit_features as advanced
from . import validation_v13 as validation

SCHEMA = "v13-9-engineering-closure-90-v2"
OUT = Path("data/v139_engineering_closure.json")


def _source(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _has(source: str, *tokens: str) -> bool:
    return all(token in source for token in tokens)


def _callable(module: Any, name: str) -> bool:
    return callable(getattr(module, name, None))


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
        "probability": _source("v11/probability_contract_v13.py"),
        "analytics": _source("v11/v13_analytics_only.py"),
        "dataset": _source("v11/v138_dataset_store.py"),
        "audit52": _source("v11/v138_audit_closure.py"),
        "extra": _source("v11/extra_innings_v13.py"),
        "ci": _source(".github/workflows/ci.yml"),
        "free_workflow": _source(".github/workflows/v13-7-free-data-collector.yml"),
        "prod_workflow": _source(".github/workflows/mlb-bot.yml"),
        "validation": _source("v11/validation_v13.py"),
    }

    raw: list[tuple[str, str, str, Callable[[], bool]]] = []

    def add(category: str, name: str, implementation: str, check: Callable[[], bool]) -> None:
        raw.append((category, name, implementation, check))

    # 1-16: provider integrity and observability.
    add("providers", "Three-season Savant rolling constant", "v137_park_factors.ROLLING_YEARS", lambda: park.ROLLING_YEARS == 3)
    add("providers", "Savant query sends rolling=3", "v137_park_factors.fetch_prior_factors", lambda: _has(src["park"], '"rolling": ROLLING_YEARS'))
    add("providers", "Park prior excludes target season", "v137_park_factors._expected_window", lambda: _callable(park, "_expected_window"))
    add("providers", "Park returned window is validated", "v137_park_factors._year_label_matches", lambda: _callable(park, "_year_label_matches"))
    add("providers", "Park window rejections are counted", "v137_park_factors.collect", lambda: _has(src["park"], "window_rejection_count", "rejected_window_rows"))
    add("providers", "Zero park rows fail closed", "v137_park_factors.main", lambda: _has(src["park"], "zero validated venue rows"))
    add("providers", "Primary archived weather model explicit", "v137_weather_provider.PRIMARY_MODEL", lambda: weather.PRIMARY_MODEL == "ecmwf_ifs")
    add("providers", "Secondary weather model date-gated", "v137_weather_provider._models_for_run", lambda: _has(src["weather"], "SECONDARY_MODEL_ARCHIVE_START", "if run_date >="))
    add("providers", "Weather fallback keeps fixed run", "v137_weather_provider._attempt", lambda: _has(src["weather"], '"run": run.strftime'))
    add("providers", "Reduced weather request fallback", "v137_weather_provider.REDUCED_WEATHER_HOURLY", lambda: _has(src["weather"], "REDUCED_WEATHER_HOURLY"))
    add("providers", "Missing fallback humidity remains neutral", "v137_weather_provider", lambda: _has(src["weather"], "Missing humidity", "neutral"))
    add("providers", "Pre-archive weather fails closed", "v137_weather_provider.historical_weather_for_game", lambda: _has(src["weather"], "ecmwf_single_run_archive_not_available"))
    add("providers", "Exhausted weather fallbacks fail closed", "v137_weather_provider.historical_weather_for_game", lambda: _has(src["weather"], "single_run_all_provider_attempts_failed"))
    add("providers", "Weather backfill uses hardened provider", "v137_weather_backfill", lambda: _has(src["weather_backfill"], "v137_weather_provider", "historical_weather_for_game"))
    add("providers", "Free-provider health has explicit status", "v137_free_data_health", lambda: _has(src["health"], '"HEALTHY"', '"DEGRADED"'))
    add("providers", "Monitoring reads actual park row count", "v138_monitoring.provider_snapshot", lambda: _has(src["monitoring"], 'park.get("total_venue_rows")'))

    # 17-30: PIT/data contracts.
    add("pit_data", "Native Statcast stable-ID gate", "v139_native_context.load_statcast_priors", lambda: _has(src["native"], "statcast_prior_not_stable_id_only"))
    add("pit_data", "Statcast generated-after-asof gate", "v139_native_context.load_statcast_priors", lambda: _has(src["native"], "statcast_prior_generated_after_asof"))
    add("pit_data", "Statcast cutoff-after-game gate", "v139_native_context.load_statcast_priors", lambda: _has(src["native"], "statcast_prior_cutoff_after_game"))
    add("pit_data", "Statcast game-day/future-row gate", "v139_native_context.load_statcast_priors", lambda: _has(src["native"], "statcast_prior_contains_game_day_or_future"))
    add("pit_data", "Native context excludes market payload", "v139_native_context.build", lambda: _has(src["native"], '"market_data_embedded": False'))
    add("pit_data", "Native context excludes target labels", "v139_native_context.build", lambda: _has(src["native"], '"target_labels_embedded": False'))
    add("pit_data", "Free foundation requires no paid sources", "v137_free_data_health", lambda: _has(src["health"], '"paid_sources_required": False'))
    add("pit_data", "Reconstructed weather cannot promote", "v137_weather_backfill", lambda: _has(src["weather_backfill"], '"promotion_eligible": False'))
    add("pit_data", "Reconstructed park data cannot promote", "v137_park_factors", lambda: _has(src["park"], '"promotion_eligible": False'))
    add("pit_data", "Native research cannot affect Champion", "v139_native_context", lambda: _has(src["native"], '"affects_champion": False'))
    add("pit_data", "Features and labels are physically separate", "v138_dataset_store", lambda: _has(src["dataset"], "features and labels remain separate physical tables"))
    add("pit_data", "Dataset artifacts are checksummed", "v138_dataset_store.sha256_file", lambda: _has(src["dataset"], "sha256_file", '"sha256"'))
    add("pit_data", "Dataset training seed persisted", "v138_dataset_store.manifest", lambda: _has(src["dataset"], '"training_seed":138'))
    add("pit_data", "Dataset split policy is temporal", "v138_dataset_store.manifest", lambda: _has(src["dataset"], "strict temporal / walk-forward"))

    # 31-44: architecture/production boundary.
    add("architecture", "Explicit V13Engine exists", "v13_engine.V13Engine", lambda: isinstance(v13_engine.V13Engine, type))
    add("architecture", "V13Engine runner installer exists", "v13_engine.install_runner_engine", lambda: _callable(v13_engine, "install_runner_engine"))
    add("architecture", "V13Engine install is idempotent", "v13_engine.install_runner_engine", lambda: _has(src["engine"], "if isinstance(current, V13Engine)"))
    add("architecture", "Legacy numerical helpers delegate", "V13Engine.__getattr__", lambda: _has(src["engine"], "return getattr(self._legacy_engine, name)"))
    add("architecture", "Probability snapshot before research attach", "v13_engine._probability_snapshot", lambda: _has(src["engine"], "_probability_snapshot"))
    add("architecture", "Research probability mutation fails closed", "v13_engine", lambda: _has(src["engine"], "attempted to mutate champion probability"))
    add("architecture", "Native research attaches at engine boundary", "V13Engine.analyze", lambda: _has(src["engine"], "v139_native_context.attach"))
    add("architecture", "V13 entry installs explicit engine", "v13_entry", lambda: _has(src["entry"], "v13_engine.install_runner_engine(runner)"))
    add("architecture", "Run report exposes engine architecture", "v13_entry._run_v135", lambda: _has(src["entry"], 'report.setdefault("architecture"'))
    add("architecture", "Explicit probability pipeline exists", "pipeline_v13.ProbabilityPipelineV13", lambda: _has(src["pipeline"], "class ProbabilityPipelineV13"))
    add("architecture", "Legacy compatibility install explicit", "v13_runtime.install", lambda: _has(src["runtime"], "def install()"))
    add("architecture", "Runtime hook health inspectable", "v13_runtime.runtime_hook_status", lambda: _has(src["runtime"], "def runtime_hook_status"))
    add("architecture", "Runtime integration has fail-closed assertion", "v13_runtime.assert_runtime_hooks", lambda: _has(src["runtime"], "def assert_runtime_hooks"))
    add("architecture", "Production workflow runs V13 entry", ".github/workflows/mlb-bot.yml", lambda: _has(src["prod_workflow"], "v11.v13_entry"))

    # 45-60: advanced/native feature paths.
    feature_checks = [
        ("Advanced context composer", "build_advanced_context"),
        ("Order-aware lineup", "lineup_strength"),
        ("Starter skill", "starter_skill"),
        ("Pitch-mix matchup", "pitch_mix_matchup"),
        ("Bullpen role/leverage", "classify_bullpen_roles"),
        ("Opener detection", "detect_opener"),
        ("Travel/circadian", "circadian_travel"),
        ("Defense", "defense_factor"),
        ("Baserunning", "baserunning_factor"),
        ("Catcher framing", "catcher_framing_factor"),
        ("Umpire context", "umpire_factor"),
        ("Multi-window offense talent", "offense_talent"),
        ("Handedness park factor", "park_factor"),
    ]
    for label, function_name in feature_checks:
        add("features", f"{label} feature path", f"v138_audit_features.{function_name}", lambda name=function_name: _callable(advanced, name))
    add("features", "Native context stores lineup stable IDs", "v139_native_context.build", lambda: _has(src["native"], 'bundle["lineup_ids"]'))
    add("features", "Native context stores Statcast provenance", "v139_native_context.build", lambda: _has(src["native"], '"statcast_provenance"'))
    add("features", "Native research persists in feature map", "v139_native_context.attach", lambda: _has(src["native"], 'features["v139_native_research"]'))

    # 61-74: probability/model safety.
    add("probability", "Predictive contract versioned", "probability_contract_v13", lambda: bool(contract.PREDICTIVE_CONTRACT_VERSION))
    add("probability", "Model generation fingerprint explicit", "probability_contract_v13", lambda: bool(contract.MODEL_GENERATION_FINGERPRINT))
    add("probability", "Raw baseball probability mandatory", "assert_no_market_leakage", lambda: _has(src["probability"], "p_baseball_raw is required"))
    add("probability", "Calibrated baseball probability mandatory", "assert_no_market_leakage", lambda: _has(src["probability"], "p_baseball_calibrated is required"))
    add("probability", "Market probability separate", "option_contract_payload", lambda: _has(src["probability"], '"p_market"'))
    add("probability", "Posterior probability separate", "option_contract_payload", lambda: _has(src["probability"], '"p_posterior"'))
    add("probability", "Model-market gap explicit", "option_contract_payload", lambda: _has(src["probability"], '"model_market_gap"'))
    add("probability", "Market-derived baseball source rejected", "assert_no_market_leakage", lambda: _has(src["probability"], "market-derived source cannot define"))
    add("probability", "Calibration is explicit pipeline stage", "ProbabilityPipelineV13.calibrate", lambda: _has(src["pipeline"], "def calibrate"))
    add("probability", "Posterior weight policy isolated", "ProbabilityPipelineV13", lambda: _has(src["pipeline"], "posterior_weight_policy"))
    add("probability", "Probability uncertainty explicit", "ProbabilityPipelineV13", lambda: _has(src["pipeline"], '"probability_uncertainty_v13"'))
    add("probability", "Extra innings default neutral", "extra_innings_v13.home_win_probability", lambda: _has(src["extra"], "prior = .5 if extra_innings_home_prior is None"))
    add("probability", "Rich model cannot auto-promote", "v13_entry.self_test_v13", lambda: _has(src["entry"], "active_for_production", "is not True"))
    add("probability", "Analytics-only storage creates no bets", "v13_analytics_only.disabled_record_selected_bets", lambda: _has(src["analytics"], "def disabled_record_selected_bets", "return 0"))

    # 75-84: validation/evidence discipline.
    add("validation", "Compatible-game floor >=600", "validation_v13.MIN_COMPATIBLE_GAMES", lambda: validation.MIN_COMPATIBLE_GAMES >= 600)
    add("validation", "Outer-holdout floor >=200", "validation_v13.MIN_OUTER_HOLDOUT_GAMES", lambda: validation.MIN_OUTER_HOLDOUT_GAMES >= 200)
    add("validation", "Walk-forward floor >=5", "validation_v13.MIN_WALK_FORWARD_WINDOWS", lambda: validation.MIN_WALK_FORWARD_WINDOWS >= 5)
    add("validation", "Walk-forward consistency >=80%", "validation_v13.strict_promotion_gate", lambda: _has(src["validation"], "wf_rate >= .80"))
    add("validation", "Paired Brier CI lower bound positive", "validation_v13.strict_promotion_gate", lambda: _has(src["validation"], "lower is not None and lower > 0"))
    add("validation", "LogLoss cannot regress", "validation_v13.strict_promotion_gate", lambda: _has(src["validation"], '"logloss_nonnegative"'))
    add("validation", "Per-market Brier safety guard", "validation_v13.strict_promotion_gate", lambda: _has(src["validation"], "MAX_MARKET_BRIER_REGRESSION"))
    add("validation", "Calibration ECE/slope/intercept guard", "validation_v13.strict_promotion_gate", lambda: _has(src["validation"], "<= .03", ".75 <=", "<= 1.25"))
    add("validation", "52-point registry separates engineering/evidence", "v138_audit_closure", lambda: _has(src["audit52"], '"engineering_closed"', '"evidence_closed"'))
    add("validation", "Native/PIT evidence floors cannot be lowered", "v138_audit_closure", lambda: _has(src["audit52"], "native/PIT sample floors are never lowered"))

    # 85-90: CI/operations.
    add("operations", "CI compiles all Python code/tests", ".github/workflows/ci.yml", lambda: _has(src["ci"], "python -m py_compile v11/*.py tests/*.py"))
    add("operations", "CI runs V13.9 provider/engine tests", ".github/workflows/ci.yml", lambda: _has(src["ci"], "tests.test_v139_provider_hardening", "tests.test_v139_engine_boundary"))
    add("operations", "CI runs shared V13 preflight", ".github/workflows/ci.yml", lambda: _has(src["ci"], "python -m v11.v13_preflight --verbose"))
    add("operations", "Free workflow gates provider/cohort integrity", "v13-7-free-data-collector.yml", lambda: _has(src["free_workflow"], "Assert free-only provider integrity and cohort boundaries"))
    add("operations", "Monitoring retains feature-drift alerts", "v138_monitoring", lambda: _has(src["monitoring"], "feature_drift", "alerts"))
    add("operations", "Monitoring cannot auto-retune model", "v138_monitoring", lambda: _has(src["monitoring"], "observability only; no automatic model retuning"))

    if len(raw) != 90:
        raise RuntimeError(f"V13.9 closure registry must contain exactly 90 checks, got {len(raw)}")

    points: list[dict[str, Any]] = []
    for index, (category, name, implementation, check) in enumerate(raw, start=1):
        try:
            closed = bool(check())
            note = ""
        except Exception as exc:
            closed = False
            note = f"check_error:{type(exc).__name__}:{exc}"
        points.append(
            {
                "id": index,
                "category": category,
                "name": name,
                "implementation": implementation,
                "engineering_closed": closed,
                "note": note,
            }
        )

    closed_count = sum(int(point["engineering_closed"]) for point in points)
    open_points = [point for point in points if not point["engineering_closed"]]
    return {
        "schema": SCHEMA,
        "total_points": 90,
        "engineering_closed": closed_count,
        "engineering_open": 90 - closed_count,
        "all_engineering_closed": closed_count == 90,
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
                "open_points": report["open_points"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if report["engineering_open"]:
        raise SystemExit(f"V13.9 engineering closure incomplete: {report['engineering_open']} open point(s)")


if __name__ == "__main__":
    main()
