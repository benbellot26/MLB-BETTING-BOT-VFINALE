from __future__ import annotations

import ast
from pathlib import Path
import unittest

NATIVE_MODULES=(
    "acquisition.py","all_stats_context.py","certification.py","context_overlay.py","decision.py","defense_baserunning_challenger.py","discord.py","distribution.py","distribution_tuning.py",
    "environment_physics_challenger.py","execution_market.py","historical_distribution_shadow.py","historical_pit.py","historical_team_shadow.py","heteroskedastic_distribution_challenger.py","inning_simulator_challenger.py",
    "market_edge.py","market_lines.py","mlb_inputs.py","model.py","native_candidate.py","native_payload.py","parity_gate.py","park.py","phase.py","pipeline.py",
    "pitch_matchup_challenger.py","probability_calibration.py","production_runtime.py","provider_http.py","residual_challenger.py","run_decomposition_challenger.py","run_stack.py",
    "savant_run_value_builder.py","savant_run_value_pit.py","sharp_market.py","sharp_weight_challenger.py","starter_fallback.py","starter_integrity.py","starter_recent_usage.py","starter_usage_challenger.py",
    "statcast_base.py","statcast_daily.py","statcast_enrichment.py","statcast_pit_backfill.py","statcast_shadow.py",
    "structural.py","timezone_challenger.py","total_market.py","tracking.py","true_talent_challenger.py","uncertainty.py","uncertainty_fit.py","venue_geometry.py","venue_park_challenger.py","weather_climatology.py","weather_live_shadow.py",
    "calibration_methods_challenger.py",
)


class V14ImportBoundaryTests(unittest.TestCase):
    def test_native_v14_modules_do_not_import_v11(self):
        violations=[]; root=Path("v14")
        for filename in NATIVE_MODULES:
            path=root/filename; self.assertTrue(path.exists(),f"missing native V14 module: {path}"); tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    for alias in node.names:
                        if alias.name=="v11" or alias.name.startswith("v11."): violations.append(f"{path}:{node.lineno} import {alias.name}")
                elif isinstance(node,ast.ImportFrom):
                    module=node.module or ""
                    if module=="v11" or module.startswith("v11."): violations.append(f"{path}:{node.lineno} from {module} import ...")
        self.assertEqual(violations,[],"legacy imports leaked into native V14:\n"+"\n".join(violations))

    def test_native_candidate_is_non_publishing_and_parity_is_evidence_only(self):
        text=Path("v14/native_candidate.py").read_text(encoding="utf-8"); self.assertIn("CANDIDATE_NON_PUBLISHING",text); self.assertIn("cutover_authorized",text); self.assertIn("Historical evidence only",text)

    def test_production_runtime_has_no_legacy_cutover_gate(self):
        text=Path("v14/production_runtime.py").read_text(encoding="utf-8"); self.assertNotIn("NATIVE_CUTOVER_EVIDENCE",text); self.assertNotIn("_validate_cutover_evidence",text)

    def test_new_statistical_layers_are_fail_closed(self):
        certification=Path("v14/certification.py").read_text(encoding="utf-8"); decision=Path("v14/decision.py").read_text(encoding="utf-8"); residual=Path("v14/residual_challenger.py").read_text(encoding="utf-8")
        self.assertIn("RESEARCH_ONLY",certification); self.assertIn("betting_not_certified",decision); self.assertIn("CHALLENGER_ONLY",residual); self.assertIn("auto_activation",residual)

    def test_research_extensions_cannot_auto_activate(self):
        for filename in (
            "starter_usage_challenger.py","environment_physics_challenger.py","run_decomposition_challenger.py","timezone_challenger.py","pitch_matchup_challenger.py",
            "venue_park_challenger.py","true_talent_challenger.py","heteroskedastic_distribution_challenger.py","inning_simulator_challenger.py",
            "sharp_weight_challenger.py","calibration_methods_challenger.py",
        ):
            text=(Path("v14")/filename).read_text(encoding="utf-8")
            self.assertIn("CHALLENGER_ONLY",text)
            self.assertIn("auto_activation",text)

    def test_v146_advanced_inputs_are_explicit_and_generation_bound(self):
        defense=Path("v14/defense_baserunning_challenger.py").read_text(encoding="utf-8")
        weather=Path("v14/weather_live_shadow.py").read_text(encoding="utf-8")
        manifest=Path("v14/champion_manifest.py").read_text(encoding="utf-8")
        overlay=Path("v14/all_stats_context.py").read_text(encoding="utf-8")
        self.assertIn("PRODUCTION_ADVANCED_COMPONENT",defense)
        self.assertIn('"champion_impact":True',defense)
        self.assertIn("PRODUCTION_ADVANCED_INPUT",weather)
        self.assertIn('"champion_impact":True',weather)
        self.assertIn("market_probability_used_as_feature",defense)
        self.assertIn("market_probability_used_as_feature",weather)
        self.assertIn("defense_baserunning_challenger.py",manifest)
        self.assertIn("weather_live_shadow.py",manifest)
        self.assertIn("defense_baserunning",overlay)
        self.assertIn("environment_physics",overlay)

    def test_validated_native_shadows_remain_non_activating(self):
        for filename in ("historical_team_shadow.py","historical_distribution_shadow.py"):
            text=(Path("v14")/filename).read_text(encoding="utf-8")
            self.assertIn("SHADOW_ONLY",text)
            self.assertIn("auto_activation",text)
            self.assertIn("champion_impact",text)

    def test_historical_pit_contract_rejects_live_season_backfill(self):
        text=Path("v14/historical_pit.py").read_text(encoding="utf-8")
        self.assertIn("historical leakage",text)
        self.assertIn("mlb_stats_season_live",text)


if __name__ == "__main__":
    unittest.main()
