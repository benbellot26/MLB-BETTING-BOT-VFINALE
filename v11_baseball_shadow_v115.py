#!/usr/bin/env python3
"""V11.1.5: prevent rejected lineups from affecting L/R matchup shadow."""
from __future__ import annotations

import bot as core
import v11_baseball_shadow_v114 as v114

base = v114.base
SHADOW_VERSION = "11.1.5-baseball-shadow-v6"
_old_matchup = base._matchup


def _matchup(lineup, feed, starter):
    out = dict(_old_matchup(lineup, feed, starter) or {})
    quality_ok = bool(lineup.get("available"))
    out["lineup_quality_gate"] = quality_ok
    if not quality_ok:
        out["available"] = False
        out["score"] = 0.0
    return out


def install():
    v114.install()
    base.SHADOW_VERSION = SHADOW_VERSION
    base._matchup = _matchup


def self_test():
    install()
    rejected = _matchup({
        "available": False,
        "hitters": [{"ops": .900, "bat_side": "L", "order": 1}],
    }, {"gameData": {"players": {"ID999": {"pitchHand": {"code": "R"}}}}}, 999)
    assert rejected.get("available") is False
    assert abs(core.num(rejected.get("score"), 0)) < 1e-12
    assert rejected.get("lineup_quality_gate") is False
    v114.self_test()
    print("SELF-TEST V11.1.5 MATCHUP QUALITY OK")


def main():
    install()
    base.main()


if __name__ == "__main__":
    main()
