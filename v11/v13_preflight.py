from __future__ import annotations

import argparse
import importlib
import unittest

CRITICAL_TEST_MODULES = (
    "tests.test_v13_probability_contract",
    "tests.test_v13_historical_migration",
    "tests.test_v13_probability_invariants",
    "tests.test_v13_historical_backfill_regression",
    "tests.test_v13_daily_postmortem",
    "tests.test_v13_posterior_policy",
    "tests.test_v13_research_gate",
    "tests.test_v13_analytics_only",
    "tests.test_v135_professional_audit",
    "tests.test_v1351_audit_fixes",
    "tests.test_v1352_final_hardening",
    "tests.test_v1352_runtime_hook",
    "tests.test_v1352_audit_hardening",
    "tests.test_v13_rich_native_train",
    "tests.test_v136_evidence_hardening",
    "tests.test_v137_free_data",
)


def run(modules: tuple[str, ...] = CRITICAL_TEST_MODULES, verbosity: int = 1) -> bool:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for name in modules:
        module = importlib.import_module(name)
        suite.addTests(loader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return result.wasSuccessful()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the shared V13.7 critical preflight suite")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not run(verbosity=2 if args.verbose else 1):
        raise SystemExit(1)
    print("V13.7 shared critical preflight OK")


if __name__ == "__main__":
    main()
