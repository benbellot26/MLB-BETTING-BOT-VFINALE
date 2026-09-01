from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID, VERSION
from v14.ablation_shadow import build as build_ablation
from v14.champion_contract import (
    CHAMPION_DISPERSION,
    CHAMPION_ENVIRONMENT_SIGMA,
    validated_extra_innings_home_probability,
)
from v14.champion_dashboard import build_dashboard
from v14.distribution import probability_surface
from v14.model import RunProjection
from v14.reproducibility_guard import audit as reproducibility_audit
from v14.research_registry import GOVERNANCE_POLICY, register, verify
from v14.structural import LeagueBaselines, Starter, StructuralInputs, TeamInputs, project
from v14.structural_sensitivity import sensitivity_report, shadow_project


def _inputs() -> StructuralInputs:
    home_starter = Starter(era=3.80, whip=1.20, innings=90)
    away_starter = Starter(era=4.45, whip=1.34, innings=85)
    home_enhanced = Starter(era=3.95, whip=1.23, innings=90)
    away_enhanced = Starter(era=4.30, whip=1.31, innings=85)
    return StructuralInputs(
        league=LeagueBaselines(),
        home=TeamInputs(
            runs_per_game=4.8,
            ops=.735,
            lineup_ops=.750,
            team_era=4.10,
            starter=home_starter,
            enhanced_starter=home_enhanced,
            operational={},
        ),
        away=TeamInputs(
            runs_per_game=4.2,
            ops=.695,
            lineup_ops=.705,
            team_era=4.55,
            starter=away_starter,
            enhanced_starter=away_enhanced,
            operational={},
        ),
        static_park_factor=1.03,
    )


class V14ProfessionalizationAuditTests(unittest.TestCase):
    def test_structural_sensitivity_default_is_exact_champion_parity(self) -> None:
        inputs = _inputs()
        champion = project(inputs)
        shadow = shadow_project(inputs)
        self.assertAlmostEqual(shadow["home_mu"], champion["home_mu"], places=12)
        self.assertAlmostEqual(shadow["away_mu"], champion["away_mu"], places=12)
        report = sensitivity_report(inputs)
        self.assertEqual(report["role"], "RESEARCH_ONLY")
        self.assertFalse(report["champion_impact"])
        self.assertGreater(len(report["scenarios"]), 0)

    def test_raw_ablation_requires_full_reconstruction_parity(self) -> None:
        extra, _ = validated_extra_innings_home_probability()
        run = RunProjection(
            game_pk="1",
            game_date="2026-09-02T23:00:00Z",
            analyzed_at="2026-09-02T22:30:00Z",
            home="Home",
            away="Away",
            home_mu=4.4,
            away_mu=4.0,
            total_line=8.5,
            phase="FINAL",
            dispersion=CHAMPION_DISPERSION,
            environment_sigma=CHAMPION_ENVIRONMENT_SIGMA,
            extra_innings_home_probability=extra,
        ).validated()
        raw, _tail = probability_surface(run)
        prediction = {
            "game_pk": run.game_pk,
            "game_date": run.game_date,
            "analyzed_at": run.analyzed_at,
            "home": run.home,
            "away": run.away,
            "phase": run.phase,
            "model_generation": MODEL_GENERATION,
            "total_line": run.total_line,
            "run_projection": {
                "dispersion": run.dispersion,
                "environment_sigma": run.environment_sigma,
                "extra_innings_home_probability": run.extra_innings_home_probability,
            },
            "base_run_projection": {"home_mu": 4.4, "away_mu": 4.0},
            "context_adjustment": {"home_delta": 0.0, "away_delta": 0.0, "components": {}},
            "advanced_stats_adjustment": {"home_delta": 0.0, "away_delta": 0.0, "components": {}},
            "raw_probabilities": raw.as_dict(),
        }
        report = build_ablation(prediction)
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["score_contract"], "RAW_UNCALIBRATED_PROBABILITY_SURFACE")
        self.assertLessEqual(report["raw_reconstruction_max_abs_delta"], 1e-12)
        self.assertTrue(report["variants"])
        for payload in report["variants"].values():
            self.assertIn("raw_probabilities", payload)
            self.assertNotIn("probabilities", payload)
            self.assertFalse(payload["market_probability_used_as_feature"])

        leaked = dict(prediction)
        leaked["raw_probabilities"] = dict(prediction["raw_probabilities"])
        leaked["raw_probabilities"]["home_ml"] += .01
        rejected = build_ablation(leaked)
        self.assertEqual(rejected["status"], "UNAVAILABLE")
        self.assertEqual(rejected["reason"], "full_raw_reconstruction_mismatch")

    def test_new_registry_contract_seals_research_budget_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.jsonl"
            row = register({
                "governance_policy": GOVERNANCE_POLICY,
                "experiment_id": "TEST-STRICT-01",
                "hypothesis": "test",
                "model": "shadow",
                "features": ["x"],
                "training_period": "none",
                "validation_period": "future",
                "primary_metric": "brier",
                "secondary_metrics": ["logloss"],
                "success_rule": "CI lower > 0",
                "minimum_independent_games": 20,
                "analysis_plan": "paired future games",
                "stopping_rule": "stop only at declared n",
                "promotion_scope": "nomination only",
                "code_commit_sha": "deadbeef",
                "multiplicity_family": "TEST",
                "research_budget_family": "TEST",
            }, path, registered_at="2026-09-01T12:00:00+00:00")
            self.assertEqual(row["governance_policy"], GOVERNANCE_POLICY)
            self.assertTrue(row["spec_fingerprint"])
            status = verify(path)
            self.assertTrue(status["valid"])
            self.assertEqual(status["strict_governance_experiments"], 1)

    def test_dashboard_is_read_only_and_uses_authoritative_certification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / "cert.json"
            cert.write_text(json.dumps({
                "betting_status": "RESEARCH_ONLY",
                "probability_status": "COLLECTING",
                "certified": False,
                "markets": {},
            }), encoding="utf-8")
            paths = {
                "performance": root / "missing-performance.json",
                "certification": cert,
                "paper": root / "missing-paper.json",
                "authorized": root / "missing-authorized.json",
                "sharp": root / "missing-sharp.json",
                "coverage": root / "missing-coverage.json",
                "data_quality": root / "missing-quality.json",
                "research": root / "missing-research.json",
                "promotion": root / "missing-promotion.json",
            }
            dashboard = build_dashboard(paths)
            self.assertEqual(dashboard["authoritative_status"]["betting_status"], "RESEARCH_ONLY")
            self.assertFalse(dashboard["authoritative_status"]["certified"])
            self.assertFalse(dashboard["research_governance"]["champion_impact"])
            serialized = json.dumps(dashboard)
            self.assertNotIn('"status": "BET"', serialized)
            self.assertNotIn('"publication_authorized": true', serialized)

    def test_reproducibility_and_documented_identity(self) -> None:
        report = reproducibility_audit(Path("v14"))
        self.assertTrue(report["valid"], report["third_party_runtime_imports"])
        root_readme = Path("README.md").read_text(encoding="utf-8")
        self.assertIn(f"V{VERSION}", root_readme)
        self.assertIn(MODEL_GENERATION, root_readme)
        self.assertIn(PROBABILITY_POLICY_ID, root_readme)


if __name__ == "__main__":
    unittest.main()
