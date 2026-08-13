#!/usr/bin/env python3
"""V11.1.4 OPS normalization fix for the baseball shadow layer.

Run #39 proved that many MLB stat payloads contain plate appearances, OBP and
SLG without a directly usable OPS field. The legacy helper defaulted OPS to
0.720 before attempting OBP+SLG, which made good hitter data look league
average. This wrapper preserves the V11.1.3 quality gate while fixing that
normalization bug.
"""
from __future__ import annotations

import bot as core
import v11_baseball_shadow_v113 as v113

base = v113.base
SHADOW_VERSION = "11.1.4-baseball-shadow-v5"


def _ops(st):
    st = v113._normalize_stat_payload(st)
    pa = core.num(st.get("plateAppearances"), 0)

    raw = core.num(st.get("ops"), 0)
    if not .2 <= raw <= 1.5:
        obp = core.num(st.get("onBasePercentage"), 0)
        slg = core.num(st.get("sluggingPercentage"), 0)
        combined = obp + slg
        raw = combined if .2 <= combined <= 1.5 else .720

    w = pa / (pa + 80)
    return .720 + w * (raw - .720), pa


def install():
    v113.install()
    base.SHADOW_VERSION = SHADOW_VERSION
    base._ops = _ops


def self_test():
    install()
    p, pa = _ops({
        "plateAppearances": 400,
        "onBasePercentage": ".390",
        "sluggingPercentage": ".610",
    })
    assert pa == 400
    assert p > .90, p

    p2, _ = _ops({"plateAppearances": 400, "ops": ".950"})
    assert p2 > .90, p2

    p3, _ = _ops({"plateAppearances": 0})
    assert abs(p3 - .720) < 1e-9

    v113.self_test()
    print("SELF-TEST V11.1.4 OPS NORMALIZATION OK")


def main():
    install()
    base.main()


if __name__ == "__main__":
    main()
