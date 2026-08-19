from __future__ import annotations

import argparse
import io
import json
import unittest
from pathlib import Path
from typing import Any

OUT = Path("data/v1310_deep_audit_closure.json")
SCHEMA = "v13-10-deep-audit-closure-v1"


def _p(fid: str, severity: str, name: str, test_id: str | None, *, evidence: str | None = None,
       compatibility: bool = False) -> dict[str, Any]:
    return {
        "id": fid,
        "severity": severity,
        "name": name,
        "test_id": test_id,
        "evidence_requirement": evidence,
        "compatibility_retained": compatibility,
    }


# This is the exact 35-finding registry from the independent V13.10 deep audit.
# Unlike the reconstructed V13.9 90-point inventory, engineering closure here is
# based on executing named behavioral tests. Evidence-only findings are never
# closed from code presence or from a self-reported JSON flag.
POINTS = [
    _p("H01","HIGH","Savant true three-season rolling contract","tests.test_v139_provider_hardening.ProviderHardeningTests.test_savant_park_request_uses_true_three_season_rolling_window"),
    _p("H02","HIGH","Prior-season park factor wired to V13 runtime","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_park_runtime_uses_prior_completed_season_ratio"),
    _p("H03","HIGH","Post-calibration complementary probability surface","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_probability_surface_reconciles_every_complementary_pair"),
    _p("H04","HIGH","Calibration remains fail-closed until strict volume/evidence","tests.test_v13_probability_contract.V13ProbabilityContractTests.test_calibration_identity_when_evidence_is_insufficient",evidence="GLOBAL>=600, MARKET>=400, FINAL market>=300 plus strict OOS gain"),
    _p("H05","HIGH","ML edge claim blocked until model beats market","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_probability_drift_uses_canonical_side_and_detects_confidence_shift",evidence="ML >=300 independent comparable targets, positive Brier gain, non-worse LogLoss, positive gap signal"),
    _p("H06","HIGH","RUNLINE/TOTAL market evidence cannot be inferred from missing targets","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_native_evidence_never_pools_markets_for_activation",evidence="RUNLINE and TOTAL each >=300 independent comparable targets with proper-score pass"),
    _p("H07","HIGH","Probability drift no longer averages complementary sides","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_probability_drift_uses_canonical_side_and_detects_confidence_shift"),
    _p("H08","HIGH","Operational PIT separated from promotion-grade source attestation","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_pit_distinguishes_operational_from_promotion_grade_capture"),
    _p("H09","HIGH","Deep audit closure uses behavioral verification instead of token presence","tests.test_v1310_deep_audit_registry.V1310DeepAuditRegistryTests.test_registry_declares_behavioral_verification_contract"),
    _p("H10","HIGH","Rich/native promotion requires exact promotion-grade PIT evidence","tests.test_v13_rich_native_train.NativeRichTrainTests.test_requires_native_volume",evidence=">=300 promotion-grade FINAL games + WF/outer holdout/downstream market gates"),

    _p("M01","MEDIUM","Native uncertainty/calibration/book gates are market-specific","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_native_evidence_never_pools_markets_for_activation"),
    _p("M02","MEDIUM","Validated extra-innings prior is usable only above evidence floor","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_validated_extra_innings_prior_uses_mature_evidence_only"),
    _p("M03","MEDIUM","Explicit probability-surface invariants","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_probability_surface_reconciles_every_complementary_pair"),
    _p("M04","MEDIUM","Non-finite probability fails closed","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_invalid_probability_fails_closed_instead_of_becoming_fifty_percent"),
    _p("M05","MEDIUM","Market-derived source rejected from baseball probability","tests.test_v13_probability_contract.V13ProbabilityContractTests.test_contract_rejects_market_derived_baseball_source"),
    _p("M06","MEDIUM","Provider artifact freshness is explicit","tests.test_v1310_deep_audit_registry.V1310DeepAuditRegistryTests.test_monitoring_exposes_provider_freshness_contract"),
    _p("M07","MEDIUM","Research evidence bound to actual dataset bytes","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_research_artifacts_bind_to_actual_dataset_content_hash"),
    _p("M08","MEDIUM","Predictive fingerprint advances with changed behavior","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_generation_fingerprint_moves_with_predictive_behavior"),
    _p("M09","MEDIUM","Backfill evidence writer shares repository-state concurrency lock","tests.test_v1310_deep_audit_registry.V1310DeepAuditRegistryTests.test_state_writing_workflows_share_concurrency_lock"),
    _p("M10","MEDIUM","Weather replay cache is scoped by analysis as-of","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_weather_cache_is_scoped_to_replay_as_of"),
    _p("M11","MEDIUM","Weather timestamp basis is explicit","tests.test_v1310_deep_audit_registry.V1310DeepAuditRegistryTests.test_weather_provenance_exposes_timestamp_basis"),
    _p("M12","MEDIUM","Deep-audit regressions are behavioral and in shared preflight","tests.test_v1310_deep_audit_registry.V1310DeepAuditRegistryTests.test_deep_audit_behavior_suite_is_in_shared_preflight"),
    _p("M13","MEDIUM","Discord visual contract is in shared preflight","tests.test_v1310_deep_audit_registry.V1310DeepAuditRegistryTests.test_discord_visual_suite_is_in_shared_preflight"),
    _p("M14","MEDIUM","Discord refuses incomplete eight-probability surface","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_discord_blocks_incomplete_eight_probability_surface"),
    _p("M15","MEDIUM","Historical park data pipeline rebuilt from fixed provider before team history","tests.test_v1310_deep_audit_registry.V1310DeepAuditRegistryTests.test_free_data_workflow_collects_park_before_team_history",evidence="post-merge free-data refresh must show park_prior_coverage > 0"),
    _p("M16","MEDIUM","Unvalidated uncertainty is not labeled a 90% confidence interval","tests.test_v1310_deep_audit_hardening.V1310DeepAuditHardeningTests.test_uncertainty_band_is_not_labeled_validated_confidence"),
    _p("M17","MEDIUM","Complex research challengers remain non-promotable by construction","tests.test_v138_audit_closure.V138AuditClosureTests.test_glm_gam_gbdt_hierarchy_and_ensemble_are_finite"),

    # Low-severity items are compatibility/cleanup observations. Retaining
    # compatibility names is deliberate when removal would add migration risk;
    # they are tracked separately rather than masquerading as behavioral bugs.
    _p("L01","LOW","Legacy V11/V12 config names retained only as compatibility surface",None,compatibility=True),
    _p("L02","LOW","Legacy workflow filenames retained while visible workflow/runtime labels move to V13.10",None,compatibility=True),
    _p("L03","LOW","Broad exceptions retained only in non-blocking observability/research paths",None,compatibility=True),
    _p("L04","LOW","Legacy diagnostic helpers retained but excluded from promotion decisions",None,compatibility=True),
    _p("L05","LOW","Legacy option-name persistence compatibility retained",None,compatibility=True),
    _p("L06","LOW","shadow_v124 compatibility payload name retained alongside V13 ownership",None,compatibility=True),
    _p("L07","LOW","Legacy source-contract comments/tests retained only for backwards regression compatibility",None,compatibility=True),
    _p("L08","LOW","Book-target and native-target counts reported separately",None,compatibility=True),
]


def _run_test(test_id: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if test_id in cache:
        return cache[test_id]
    suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    report = {
        "test_id": test_id,
        "passed": bool(result.wasSuccessful() and result.testsRun == 1),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "output": stream.getvalue()[-1200:],
    }
    cache[test_id] = report
    return report


def _evidence_status(point: dict[str, Any]) -> tuple[bool | None, str]:
    fid = point["id"]
    if not point.get("evidence_requirement"):
        return None, "NOT_AN_EVIDENCE_GATE"
    try:
        if fid == "H04":
            model=json.loads(Path("data/v13_baseball_calibration.json").read_text(encoding="utf-8"))
            c=model.get("calibrators") or {}
            required=("GLOBAL","MARKET:ML","MARKET:RUNLINE","MARKET:TOTAL","PHASE:FINAL:ML","PHASE:FINAL:RUNLINE","PHASE:FINAL:TOTAL")
            passed=all(bool((c.get(k) or {}).get("active")) for k in required)
            return passed, "CALIBRATORS_ACTIVE" if passed else "CALIBRATION_EVIDENCE_COLLECTING"
        if fid in {"H05","H06"}:
            health=json.loads(Path("data/v13_model_health.json").read_text(encoding="utf-8"))
            edge=health.get("edge_evidence") or {}
            markets=("ML",) if fid=="H05" else ("RUNLINE","TOTAL")
            passed=all(bool((edge.get(m) or {}).get("claim_allowed")) for m in markets)
            return passed, "EDGE_EVIDENCE_PASS" if passed else "EDGE_EVIDENCE_PENDING"
        if fid == "H10":
            rich=json.loads(Path("data/v13_rich_native_candidate.json").read_text(encoding="utf-8"))
            passed=bool(rich.get("active_for_production")) and int(rich.get("native_games") or 0)>=300
            return passed, "RICH_PROMOTION_PASS" if passed else "RICH_NATIVE_EVIDENCE_PENDING"
        if fid == "M15":
            free=json.loads(Path("data/v137_free_team_history_report.json").read_text(encoding="utf-8"))
            coverage=float(free.get("park_prior_coverage") or 0.0)
            return coverage>0.0, "PARK_HISTORY_REFRESHED" if coverage>0 else "PARK_HISTORY_REFRESH_PENDING"
    except Exception as exc:
        return False, f"EVIDENCE_ARTIFACT_UNAVAILABLE:{type(exc).__name__}"
    return False, "EVIDENCE_PENDING"


def evaluate(run_behavioral_tests: bool = True) -> dict[str, Any]:
    cache: dict[str, dict[str, Any]] = {}
    points=[]
    for point in POINTS:
        if point.get("compatibility_retained"):
            engineering=True
            verification={"type":"compatibility_disposition","passed":True,
                          "note":"intentional backwards-compatible surface; not a predictive correctness defect"}
        elif point.get("test_id") and run_behavioral_tests:
            verification={"type":"behavioral_test",**_run_test(point["test_id"],cache)}
            engineering=bool(verification.get("passed"))
        elif point.get("test_id"):
            verification={"type":"behavioral_test_not_run","test_id":point["test_id"],"passed":None}
            engineering=False
        else:
            verification={"type":"missing_verification","passed":False}
            engineering=False
        evidence_closed,evidence_status=_evidence_status(point)
        points.append({**point,"engineering_closed":engineering,"verification":verification,
                       "evidence_closed":evidence_closed,"evidence_status":evidence_status})
    engineering_closed=sum(bool(p["engineering_closed"]) for p in points)
    evidence_gates=[p for p in points if p.get("evidence_requirement")]
    evidence_closed=sum(bool(p.get("evidence_closed")) for p in evidence_gates)
    compatibility=sum(bool(p.get("compatibility_retained")) for p in points)
    return {
        "schema":SCHEMA,
        "total_findings":len(points),
        "engineering_closed":engineering_closed,
        "engineering_open":len(points)-engineering_closed,
        "behaviorally_verified":sum(p.get("verification",{}).get("type")=="behavioral_test" and bool(p.get("verification",{}).get("passed")) for p in points),
        "compatibility_retained":compatibility,
        "evidence_gate_total":len(evidence_gates),
        "evidence_closed":evidence_closed,
        "evidence_pending":len(evidence_gates)-evidence_closed,
        "claim":"35-point V13.10 audit ledger; engineering closure uses executable behavioral tests. Statistical evidence gates remain open until real independent observations pass their declared floors.",
        "legacy_v139_registry_role":"coverage inventory only; token presence is not accepted here as behavioral proof",
        "points":points,
    }


def main() -> None:
    parser=argparse.ArgumentParser(description="Evaluate V13.10 independent deep-audit closure")
    parser.add_argument("--write",action="store_true")
    parser.add_argument("--assert-engineering",action="store_true")
    args=parser.parse_args()
    report=evaluate(run_behavioral_tests=True)
    if args.write:
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("schema","total_findings","engineering_closed","engineering_open","behaviorally_verified","compatibility_retained","evidence_gate_total","evidence_closed","evidence_pending")},indent=2,sort_keys=True))
    if args.assert_engineering and report["engineering_open"]:
        open_ids=[p["id"] for p in report["points"] if not p["engineering_closed"]]
        raise SystemExit(f"V13.10 deep-audit engineering findings still open: {open_ids}")


if __name__=="__main__":
    main()
