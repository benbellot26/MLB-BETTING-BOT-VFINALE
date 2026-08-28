from __future__ import annotations

"""Frozen legacy/reference-data preflight still used by V14 data foundations.

The old V13 production/recommendation architecture is no longer an active
contract. This preflight intentionally keeps only provider, PIT, reconstructed
historical-data and evidence-integrity tests that remain relevant to artifacts
consumed by V14.
"""

import argparse
import importlib
import unittest

CRITICAL_TEST_MODULES = (
    "tests.test_v137_free_data",
    "tests.test_v138_audit_closure",
    "tests.test_v138_inning_history",
    "tests.test_v138_native_evidence",
    "tests.test_v139_provider_hardening",
    "tests.test_v1310_pit_weather_hotfix",
    "tests.test_v1310_max_audit_hardening",
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
    parser = argparse.ArgumentParser(description="Run frozen V13/V137 reference-data safety tests still consumed by V14")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not run(verbosity=2 if args.verbose else 1):
        raise SystemExit(1)
    print("V14 legacy/reference-data preflight OK")


if __name__ == "__main__":
    main()
