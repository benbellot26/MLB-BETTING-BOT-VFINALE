from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

OUT = Path("data/v139_engineering_closure.json")
SCHEMA = "v13-9-reconstructed-engineering-closure-v1"

# IMPORTANT: the historical 275-item audit was never committed as a numbered
# machine-readable registry. The previously discussed "~90 closable points" was
# therefore an engineering estimate. This module freezes that estimate into 90
# concrete, auditable controls. It must never be presented as a recovered copy
# of the missing original audit.


def _check(path: str, token: str | None = None, *, absent: bool = False) -> dict[str, Any]:
    return {"path": path, "token": token, "absent": absent}


def _point(pid: int, category: str, name: str, implementation: str, *checks: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pid,
        "category": category,
        "name": name,
        "implementation": implementation,
        "checks": list(checks),
    }


POINTS = [
    # Architecture / V13 ownership (1-16)
    _point(1,"architecture","Explicit V13 engine object","v11/v13_engine.py",_check("v11/v13_engine.py","class V13Engine")),
    _point(2,"architecture","Runner uses explicit V13 engine composition","v11/v13_runtime.py",_check("v11/v13_runtime.py","runner.engine = engine")),
    _point(3,"architecture","No V13 analyze monkey-patch","v11/v13_runtime.py",_check("v11/v13_runtime.py","engine_v12.analyze =",absent=True)),
    _point(4,"architecture","No V13 analysis-points monkey-patch","v11/v13_runtime.py",_check("v11/v13_runtime.py","engine_v12._analysis_points =",absent=True)),
    _point(5,"architecture","No V13 extra-innings monkey-patch","v11/v13_runtime.py",_check("v11/v13_runtime.py","engine_v12.prob_home_win =",absent=True)),
    _point(6,"architecture","No V13 bootstrap monkey-patch","v11/v13_runtime.py",_check("v11/v13_runtime.py","methodology_v123.bootstrap_prior_v123 =",absent=True)),
    _point(7,"architecture","Pre-candidate validation baseline preserved","v11/v13_engine.py + runtime",_check("v11/v13_engine.py","v13_validation_baseline_home_mu"),_check("v11/v13_runtime.py",'payload["v13_validation_baseline"]')),
    _point(8,"architecture","Software version decoupled from evidence generation","v11/v13_entry.py",_check("v11/v13_entry.py","assert config.VERSION == ENGINE_VERSION"),_check("v11/v13_entry.py","MODEL_GENERATION_FINGERPRINT")),
    _point(9,"architecture","Probability contract owned by V13 engine","v11/v13_engine.py",_check("v11/v13_engine.py","def _apply_probability_contract")),
    _point(10,"architecture","Both standard runline pairs preserved","v11/v13_engine.py",_check("v11/v13_engine.py","for home_point in (-1.5, 1.5):"),_check("v11/v13_engine.py",'(away, "away", -home_point)')),
    _point(11,"architecture","Extra innings owned explicitly by V13","v11/v13_engine.py",_check("v11/v13_engine.py","extra_innings_v13.home_win_probability")),
    _point(12,"architecture","Persistence adapter is explicit and marked","v11/v13_runtime.py",_check("v11/v13_runtime.py","_v13_runtime_adapter")),
    _point(13,"architecture","Engine architecture metadata persisted","v11/v13_runtime.py",_check("v11/v13_runtime.py",'payload["v13_engine"]')),
    _point(14,"architecture","V12.3 declared as compatibility primitives only","v11/v13_engine.py",_check("v11/v13_engine.py","V12.3 compatibility primitives")),
    _point(15,"architecture","Rich run challenger remains downstream shadow","v11/v13_engine.py",_check("v11/v13_engine.py","v13_rich_run_shadow.attach(result)"),_check("v11/v13_engine.py",'"affects_probability": False')),
    _point(16,"architecture","Explicit-engine behavior covered by preflight","tests/test_v139_explicit_engine.py",_check("tests/test_v139_explicit_engine.py","test_runtime_install_does_not_mark_v12_engine_as_v13_hooked"),_check("v11/v13_preflight.py","tests.test_v139_explicit_engine")),

    # Providers / PIT / provenance (17-42)
    _point(17,"providers","Single Runs remains primary historical weather source","v11/v137_free_data.py",_check("v11/v137_free_data.py","single-runs-api.open-meteo.com/v1/forecast")),
    _point(18,"providers","Weather requests only supported deterministic variables","v11/v137_free_data.py",_check("v11/v137_free_data.py","WEATHER_HOURLY"),_check("tests/test_v137_free_data.py","test_historical_weather_request_uses_supported_ecmwf_variables")),
    _point(19,"providers","Conservative ECMWF publication lag","v11/v137_free_data.py",_check("v11/v137_free_data.py","safe_ecmwf_run"),_check("tests/test_v137_free_data.py","test_ecmwf_run_uses_conservative_publication_lag")),
    _point(20,"providers","Weather run PIT validation","v11/v137_free_data.py",_check("v11/v137_free_data.py","weather_run_is_point_in_time")),
    _point(21,"providers","Previous Runs weather fallback","v11/v137_weather_backfill.py",_check("v11/v137_weather_backfill.py","previous-runs-api.open-meteo.com/v1/forecast")),
    _point(22,"providers","Previous Runs chooses conservative fixed lead","v11/v137_weather_backfill.py",_check("v11/v137_weather_backfill.py","def _previous_day_offset"),_check("tests/test_v139_provider_hardening.py","test_previous_runs_offset_is_conservative_for_two_hour_cutoff")),
    _point(23,"providers","Previous Runs rejects postgame analysis","v11/v137_weather_backfill.py",_check("tests/test_v139_provider_hardening.py","test_previous_runs_refuses_postgame_analysis")),
    _point(24,"providers","Weather fallback provenance is explicit","v11/v137_weather_backfill.py",_check("v11/v137_weather_backfill.py",'"provider_fallback": True'),_check("v11/v137_weather_backfill.py","Open-Meteo Previous Runs / Best Match")),
    _point(25,"providers","Weather report separates provider counts","v11/v137_weather_backfill.py",_check("v11/v137_weather_backfill.py",'"provider_counts"')),
    _point(26,"providers","Reconstructed weather cannot promote","v11/v137_weather_backfill.py",_check("v11/v137_weather_backfill.py",'"promotion_eligible": False')),
    _point(27,"providers","Weather fallback has live CI smoke",".github/workflows/v13-provider-hardening-ci.yml",_check(".github/workflows/v13-provider-hardening-ci.yml","Open-Meteo Previous Runs live smoke")),
    _point(28,"providers","Savant remains preferred park-factor source","v11/v137_park_factors.py",_check("v11/v137_park_factors.py","statcast-park-factors")),
    _point(29,"providers","Savant embedded JSON parser retained","v11/v137_park_factors.py",_check("v11/v137_park_factors.py","def _parse_embedded_park_data")),
    _point(30,"providers","Savant static table parser retained","v11/v137_park_factors.py",_check("v11/v137_park_factors.py","def _parse_park_table")),
    _point(31,"providers","MLB Stats park fallback prevents zero coverage","v11/v137_park_factors.py",_check("v11/v137_park_factors.py","def _mlb_fallback_rows")),
    _point(32,"providers","Park fallback uses only three completed seasons","v11/v137_park_factors.py",_check("v11/v137_park_factors.py","source_years = [target - 3, target - 2, target - 1]"),_check("tests/test_v139_provider_hardening.py","test_park_fallback_uses_only_completed_source_seasons")),
    _point(33,"providers","Park fallback consumes final regular-season games only","v11/v137_park_factors.py",_check("v11/v137_park_factors.py","def _fetch_completed_season_games"),_check("v11/v137_park_factors.py",'"gameTypes": "R"')),
    _point(34,"providers","Park fallback enforces minimum venue sample","v11/v137_park_factors.py",_check("v11/v137_park_factors.py","MIN_FALLBACK_VENUE_GAMES = 20")),
    _point(35,"providers","Fallback never pretends handedness specificity","v11/v137_park_factors.py",_check("v11/v137_park_factors.py",'"handedness_specific": False')),
    _point(36,"providers","Reconstructed park factors cannot promote","v11/v137_park_factors.py",_check("v11/v137_park_factors.py",'"promotion_eligible": False')),
    _point(37,"providers","Park factors have live CI smoke",".github/workflows/v13-provider-hardening-ci.yml",_check(".github/workflows/v13-provider-hardening-ci.yml","Park-factor live smoke with fallback allowed")),
    _point(38,"providers","Free-provider health exposes explicit status","v11/v137_free_data_health.py",_check("v11/v137_free_data_health.py",'status = "FAIL" if alerts else "DEGRADED" if warnings else "HEALTHY"')),
    _point(39,"providers","Provider fallbacks are warnings not hidden failures","v11/v137_free_data_health.py",_check("v11/v137_free_data_health.py",'warnings.append("weather_previous_runs_fallback_used")'),_check("v11/v137_free_data_health.py",'warnings.append("park_factor_mlb_stats_fallback_used")')),
    _point(40,"providers","Monitoring reads canonical park row count","v11/v138_monitoring.py",_check("v11/v138_monitoring.py",'"park_rows": park.get("total_venue_rows")')),
    _point(41,"providers","Statcast priors are stable-ID only","v11/v137_free_data.py",_check("tests/test_v137_free_data.py","test_statcast_is_stable_id_only_and_rejects_cutoff_day")),
    _point(42,"providers","Statcast row-cap responses split adaptively","v11/v137_free_data.py",_check("v11/v137_free_data.py","fetch_statcast_rows_adaptive"),_check("tests/test_v137_free_data.py","test_statcast_adaptive_fetch_splits_capped_ranges")),

    # Data/PIT integrity and live-state controls (43-58)
    _point(43,"data_integrity","Single-day Statcast truncation fails closed","v11/v137_free_data.py",_check("tests/test_v137_free_data.py","test_statcast_single_day_cap_fails_closed")),
    _point(44,"data_integrity","Statcast cutoff day cannot enter priors","v11/v137_free_data.py",_check("tests/test_v137_free_data.py","test_statcast_is_stable_id_only_and_rejects_cutoff_day")),
    _point(45,"data_integrity","Reconstructed envelopes cannot count as native evidence","v11/v137_free_data.py",_check("tests/test_v137_free_data.py","test_reconstructed_envelope_can_never_be_native_promotion_evidence")),
    _point(46,"data_integrity","Historical feature and target labels remain separated","v11/v137_team_history.py",_check("tests/test_v137_free_data.py","test_team_history_keeps_target_label_separate_excludes_same_day_and_uses_prior_park")),
    _point(47,"data_integrity","MLB roster state is native point-in-time","v11/v137_mlb_state.py",_check("tests/test_v137_free_data.py","test_mlb_native_state_uses_stable_roster_ids_and_conservative_il_signal")),
    _point(48,"data_integrity","Roster snapshots use stable player IDs","v11/v137_mlb_state.py",_check("tests/test_v137_free_data.py","person_id")),
    _point(49,"data_integrity","IL signal is explicitly conservative","v11/v137_mlb_state.py",_check("tests/test_v137_free_data.py","injured_list_signal")),
    _point(50,"data_integrity","Same-day final counts for doubleheader bullpen state","v11",_check("tests/test_v136_evidence_hardening.py","test_same_day_finished_game_counts_for_doubleheader_bullpen")),
    _point(51,"data_integrity","Point-in-time state is derived not blindly trusted","v11/point_in_time_v13.py",_check("tests/test_v136_evidence_hardening.py","test_point_in_time_is_derived_not_trusted")),
    _point(52,"data_integrity","Live snapshots materialize validated PIT state","v11/point_in_time_v13.py",_check("tests/test_v136_evidence_hardening.py","test_live_snapshot_materialises_validated_point_in_time_state")),
    _point(53,"data_integrity","Feature store never embeds postgame labels","v11/v13_feature_store.py",_check("tests/test_v136_evidence_hardening.py","test_feature_store_never_embeds_postgame_labels")),
    _point(54,"data_integrity","Inactive weather/rich bullpen cannot inflate model DQ","v11/data_quality.py",_check("tests/test_v136_evidence_hardening.py","test_inactive_weather_and_rich_bullpen_do_not_artificially_raise_model_dq")),
    _point(55,"data_integrity","Only learned-active context can affect DQ credit","v11/data_quality.py",_check("tests/test_v136_evidence_hardening.py","test_learned_active_contract_can_use_weather_and_bullpen")),
    _point(56,"data_integrity","Tracking keys are immutable by phase/as-of","v11/v13_daily_tracking.py",_check("tests/test_v1351_audit_fixes.py","test_tracking_key_is_immutable_by_phase_and_asof")),
    _point(57,"data_integrity","Tracking sync keeps latest per game and phase","v11/v13_tracking_sync.py",_check("tests/test_v1351_audit_fixes.py","test_tracking_sync_keeps_latest_per_game_and_phase")),
    _point(58,"data_integrity","Coverage report explains every scheduled game","v11/v13_coverage_report.py",_check("tests/test_v136_evidence_hardening.py","test_coverage_report_explains_every_scheduled_game")),

    # Research/challenger safeguards (59-70)
    _point(59,"models","Log-link GLM challenger implemented","v11/v138_research_models.py",_check("v11/v138_research_models.py","def fit_glm")),
    _point(60,"models","GAM challenger implemented with fixed basis","v11/v138_research_models.py",_check("v11/v138_research_models.py","def fit_gam"),_check("v11/v138_research_models.py","GAM_NONLINEAR_INDICES")),
    _point(61,"models","Portable boosted-stump challenger implemented","v11/v138_research_models.py",_check("v11/v138_research_models.py","def fit_gbdt")),
    _point(62,"models","Empirical-Bayes hierarchy implemented","v11/v138_research_models.py",_check("v11/v138_research_models.py","def fit_hierarchical")),
    _point(63,"models","Ensemble weights learned only among candidates","v11/v138_research_models.py",_check("v11/v138_research_models.py","def _ensemble_weights")),
    _point(64,"models","Transparent naive run baseline retained","v11/v138_research_models.py",_check("v11/v138_research_models.py","def naive_runs")),
    _point(65,"models","Model family finiteness covered by tests","tests/test_v138_audit_closure.py",_check("tests/test_v138_audit_closure.py","test_glm_gam_gbdt_hierarchy_and_ensemble_are_finite")),
    _point(66,"models","Rich-model promotion requires native volume","v11/v13_rich_native_train.py",_check("tests/test_v13_rich_native_train.py","test_requires_native_volume")),
    _point(67,"models","Run-mean candidate remains FINAL transfer-gated","v11/v13_run_mean_runtime.py",_check("tests/test_v1352_final_hardening.py","test_final_run_mean_prior_is_gated_until_native_transfer_passes")),
    _point(68,"models","Distribution candidate rejects stale generation","v11/v13_distribution_prior.py",_check("tests/test_v1352_final_hardening.py","test_distribution_prior_rejects_stale_generation_and_allows_valid_current_generation")),
    _point(69,"models","Posterior remains shadow even when validated","v11/pipeline_v13.py",_check("tests/test_v1352_audit_hardening.py","test_validated_posterior_can_move_shadow_but_not_primary")),
    _point(70,"models","Dynamic calibration requires chronological OOS gain","v11/v138_native_evidence.py",_check("tests/test_v138_native_evidence.py","test_dynamic_calibration_requires_chronological_oos_improvement")),

    # Validation / analytical storage (71-82)
    _point(71,"validation","Calibration gain requires positive bootstrap lower bound","v11/calibration_baseball_v13.py",_check("tests/test_v13_probability_contract.py","test_strict_validation_requires_positive_bootstrap_lower_bound")),
    _point(72,"validation","Multi-season walk-forward validation implemented","v11/v138_validation.py",_check("v11/v138_validation.py","def walk_forward")),
    _point(73,"validation","Per-season chronological validation retained","v11/v138_validation.py",_check("v11/v138_validation.py","walk_forward")),
    _point(74,"validation","Subgroup validation implemented","v11/v138_validation.py",_check("v11/v138_validation.py","def subgroup_validation")),
    _point(75,"validation","Feature ablation implemented","v11/v138_validation.py",_check("v11/v138_validation.py","def ablation_report")),
    _point(76,"validation","Reliability lookup stays in raw probability space","v11",_check("tests/test_v1351_audit_fixes.py","test_reliability_lookup_stays_in_raw_probability_space")),
    _point(77,"validation","Market disagreement cannot widen baseball-only interval","v11/uncertainty_v13.py",_check("tests/test_v135_professional_audit.py","test_market_disagreement_does_not_widen_baseball_interval")),
    _point(78,"validation","Empirical probability-band evidence uses grouped rates","v11/v138_native_evidence.py",_check("tests/test_v138_native_evidence.py","test_probability_band_gate_uses_group_empirical_rates_not_binary_point_coverage")),
    _point(79,"validation","Book weights can activate only on OOS evidence","v11/v138_native_evidence.py",_check("tests/test_v138_native_evidence.py","test_learned_book_weights_can_pass_only_on_oos")),
    _point(80,"validation","DuckDB and Parquet analytical store implemented","v11/v138_dataset_store.py",_check("v11/v138_dataset_store.py","duckdb"),_check("v11/v138_dataset_store.py","parquet")),
    _point(81,"validation","Per-artifact checksums implemented","v11/v138_dataset_store.py",_check("v11/v138_dataset_store.py","def sha256_file")),
    _point(82,"validation","Reproducibility manifest covered by regression test","v11/v138_validation.py",_check("tests/test_v138_audit_closure.py","test_dataset_checksums_and_reproducibility_manifest")),

    # CI / production / monitoring (83-90)
    _point(83,"operations","Shared preflight is used by critical workflows","v11/v13_preflight.py",_check("tests/test_v1352_audit_hardening.py","test_shared_preflight_is_used_by_ci_production_backfill_and_research")),
    _point(84,"operations","Provider live-smoke CI is dedicated and fail-closed",".github/workflows/v13-provider-hardening-ci.yml",_check(".github/workflows/v13-provider-hardening-ci.yml","provider-contracts")),
    _point(85,"operations","Main CI compiles all V11 and test modules",".github/workflows/ci.yml",_check(".github/workflows/ci.yml","python -m py_compile v11/*.py tests/*.py")),
    _point(86,"operations","Production execution is manual-only",".github/workflows/mlb-bot.yml",_check("tests/test_v1352_audit_hardening.py","test_production_is_manual_only_and_research_version_check_is_fingerprint_based")),
    _point(87,"operations","Analytics-only payload is redundantly enforced","v11/v13_analytics_only.py",_check("tests/test_v13_analytics_only.py","test_v13_entry_wires_redundant_fail_closed_guards")),
    _point(88,"operations","Critical starter/lineup changes reopen publication","v11/v138_live_change.py",_check("tests/test_v138_production_change_gate.py","test_sent_game_reopens_when_probable_starter_changes"),_check("tests/test_v138_production_change_gate.py","test_sent_game_reopens_when_free_live_feed_lineup_personnel_changes")),
    _point(89,"operations","Feature drift remains monitored","v11/v138_monitoring.py",_check("v11/v138_monitoring.py","validation.feature_drift")),
    _point(90,"operations","New provider and engine controls are part of critical preflight","v11/v13_preflight.py",_check("v11/v13_preflight.py","tests.test_v139_provider_hardening"),_check("v11/v13_preflight.py","tests.test_v139_explicit_engine")),
]


def _evaluate_check(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["path"])
    token = spec.get("token")
    absent = bool(spec.get("absent"))
    if not path.exists():
        return {**spec, "passed": False, "reason": "missing_path"}
    if token is None:
        return {**spec, "passed": True, "reason": "path_exists"}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return {**spec, "passed": False, "reason": f"read_error:{type(exc).__name__}"}
    found = str(token) in text
    passed = (not found) if absent else found
    return {**spec, "passed": passed, "reason": "forbidden_absent" if absent and passed else "token_present" if found else "token_missing"}


def evaluate() -> dict[str, Any]:
    points = []
    for point in POINTS:
        checks = [_evaluate_check(spec) for spec in point["checks"]]
        closed = bool(checks) and all(item["passed"] for item in checks)
        points.append({**point, "checks": checks, "engineering_closed": closed})
    closed = sum(bool(point["engineering_closed"]) for point in points)
    category_summary: dict[str, dict[str, int]] = {}
    for point in points:
        cat = point["category"]
        bucket = category_summary.setdefault(cat, {"total": 0, "closed": 0})
        bucket["total"] += 1
        bucket["closed"] += int(bool(point["engineering_closed"]))
    return {
        "schema": SCHEMA,
        "registry_kind": "reconstructed_from_previous_engineering_estimate",
        "historical_original_275_registry_available": False,
        "claim": "engineering closure only; statistical evidence gates remain independently governed",
        "total": len(points),
        "engineering_closed": closed,
        "engineering_open": len(points) - closed,
        "category_summary": category_summary,
        "points": points,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the reconstructed 90-point V13 engineering closure registry")
    parser.add_argument("--assert-closed", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = evaluate()
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "total": report["total"],
        "engineering_closed": report["engineering_closed"],
        "engineering_open": report["engineering_open"],
        "category_summary": report["category_summary"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    if args.assert_closed and report["engineering_open"]:
        open_points = [point["id"] for point in report["points"] if not point["engineering_closed"]]
        raise SystemExit(f"Reconstructed engineering registry still open: {open_points}")


if __name__ == "__main__":
    main()
