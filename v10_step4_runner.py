#!/usr/bin/env python3
"""V10 step-4 validation runner: professional confidence layer.

Builds on step 3 without touching main or the production workflow. The final
V10 will fold these validated blocks back into one bot.py.
"""
import sys

import v10_runner as base
from v10_confidence import (
    confidence_diagnostics,
    confidence_v10,
    refs_cap,
    self_test as confidence_self_test,
)

core = base.core

core.VERSION = "10.0.0-step4"
core.RECOMMENDATION_VERSION = "model-first-mainline-confidence-v4"

# Same signature as V9, so ML, RL and TOTAL recommendations all receive the new
# reliability score. Large model-market disagreement no longer adds confidence.
core.model_signal_confidence = confidence_v10


def self_test():
    # Keep all previous integration tests. Step 3 asserts its own version string,
    # so expose it only while that historical test executes.
    saved_version = core.RECOMMENDATION_VERSION
    core.RECOMMENDATION_VERSION = base.V10_RECOMMENDATION_VERSION
    try:
        base.self_test()
    finally:
        core.RECOMMENDATION_VERSION = saved_version

    confidence_self_test()

    assert core.model_signal_confidence is confidence_v10
    assert core.RECOMMENDATION_VERSION == "model-first-mainline-confidence-v4"

    # Audit-critical hard caps.
    assert core.model_signal_confidence(.68, .95, .55, 1) <= 6.0
    assert core.model_signal_confidence(.68, .95, .55, 2) <= 7.5

    # A large disagreement is uncertainty, not free confidence.
    aligned = core.model_signal_confidence(.66, .90, .64, 4)
    contrarian = core.model_signal_confidence(.66, .90, .48, 4)
    assert aligned > contrarian, (aligned, contrarian)

    print("SELF-TEST V10 STEP4 INTEGRATION OK", {
        "aligned": aligned,
        "contrarian": contrarian,
        "one_ref_cap": refs_cap(1),
        "two_ref_cap": refs_cap(2),
        "audit": confidence_diagnostics(.68, .95, .55, 1),
    })


def main():
    core.logging.info(
        "V10 step4 actif | base=%s | phases=%s | lignes=%s | confiance=%s",
        "advanced-baseball-v10",
        "EARLY/LATE/FINAL isolés",
        "RL/TOTAL main-line consensus uniquement",
        "reliability-v10 + hard refs caps",
    )
    base.main()


if __name__ == "__main__":
    try:
        if "--self-test" in sys.argv:
            self_test()
        else:
            main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        core.logging.exception("ERREUR FATALE V10 STEP4")
        raise
