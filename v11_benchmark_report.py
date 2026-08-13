#!/usr/bin/env python3
"""Stable router for the V11 benchmark and V11.1.2 baseball shadow."""
from __future__ import annotations

import sys
import v11_benchmark_report_legacy as legacy

# Public helpers retained for the dedicated shadow modules.
_latest_snapshot = legacy._latest_snapshot
_snapshot_model_home = legacy._snapshot_model_home
historical_sharp = legacy.historical_sharp
collect = legacy.collect
benchmark_main = legacy.benchmark_main


def main():
    if "--baseball-shadow" in sys.argv:
        import v11_baseball_shadow_v112 as shadow
        shadow.main()
    elif "--shadow-self-test" in sys.argv:
        import v11_baseball_shadow_v112 as shadow
        shadow.self_test()
    else:
        legacy.benchmark_main()


if __name__ == "__main__":
    main()
