from __future__ import annotations

import argparse
import unittest

CRITICAL_TEST_MODULES = (
    "tests.test_v14_foundation",
    "tests.test_v14_champion_parity",
    "tests.test_v14_evidence",
    "tests.test_v14_run_model",
)


def run(verbosity: int = 1) -> bool:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for name in CRITICAL_TEST_MODULES:
        module = __import__(name, fromlist=["*"])
        suite.addTests(loader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return result.wasSuccessful()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V14 champion-parity critical tests")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not run(verbosity=2 if args.verbose else 1):
        raise SystemExit(1)
    print("V14 champion-parity preflight OK")


if __name__ == "__main__":
    main()
