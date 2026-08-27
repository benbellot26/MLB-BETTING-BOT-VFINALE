from __future__ import annotations

import argparse
import unittest

CRITICAL_TEST_MODULES=(
    "tests.test_v14_acquisition",
    "tests.test_v14_artifacts",
    "tests.test_v14_certification_strict",
    "tests.test_v14_champion_manifest",
    "tests.test_v14_context_overlay",
    "tests.test_v14_discord",
    "tests.test_v14_distribution_extra_innings",
    "tests.test_v14_end_to_end_tracking",
    "tests.test_v14_feature_row",
    "tests.test_v14_historical_distribution_isolation",
    "tests.test_v14_historical_distribution_live_validation",
    "tests.test_v14_historical_distribution_shadow",
    "tests.test_v14_historical_identity_reconstruction",
    "tests.test_v14_historical_rich_validation",
    "tests.test_v14_historical_team_live_validation",
    "tests.test_v14_historical_team_shadow",
    "tests.test_v14_historical_validation",
    "tests.test_v14_import_boundaries",
    "tests.test_v14_ledgers",
    "tests.test_v14_market_edge",
    "tests.test_v14_market_lines",
    "tests.test_v14_mlb_inputs",
    "tests.test_v14_mlb_operational",
    "tests.test_v14_native_candidate",
    "tests.test_v14_native_payload",
    "tests.test_v14_parity_gate",
    "tests.test_v14_parity_workflow",
    "tests.test_v14_phase",
    "tests.test_v14_pipeline",
    "tests.test_v14_production_runtime",
    "tests.test_v14_professional_hardening",
    "tests.test_v14_research_extensions",
    "tests.test_v14_4_professional_data_model",
    "tests.test_v14_run_stack_parity",
    "tests.test_v14_savant_run_value_builder",
    "tests.test_v14_savant_run_value_pit",
    "tests.test_v14_statcast_daily",
    "tests.test_v14_statcast_enrichment",
    "tests.test_v14_statcast_pit_backfill",
    "tests.test_v14_staking",
    "tests.test_v14_starter_fallback",
    "tests.test_v14_starter_integrity",
    "tests.test_v14_starter_recent_usage",
    "tests.test_v14_structural_parity",
    "tests.test_v14_team_history_shadow",
    "tests.test_v14_tracking",
    "tests.test_v14_venue_park_builder",
    "tests.test_v14_weather_live_shadow",
    "tests.test_v14_weather_pit_backfill",
)

def run(verbosity:int=1)->bool:
    suite=unittest.TestSuite(); loader=unittest.defaultTestLoader
    for name in CRITICAL_TEST_MODULES:
        module=__import__(name,fromlist=["*"]); suite.addTests(loader.loadTestsFromModule(module))
    return unittest.TextTestRunner(verbosity=verbosity).run(suite).wasSuccessful()

def main()->None:
    parser=argparse.ArgumentParser(description="Run Pulsar V14 production and governance tests"); parser.add_argument("--verbose",action="store_true"); args=parser.parse_args()
    if not run(verbosity=2 if args.verbose else 1): raise SystemExit(1)
    print("Pulsar V14 production/governance preflight OK")

if __name__=="__main__": main()
