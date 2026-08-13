#!/usr/bin/env python3
"""V11.2 live shadow overlay.

Adds the historically selected V11.2 lineup-calibration probability to each
point-in-time baseball shadow row.  Official picks remain untouched.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bot as core
import v11_baseball_shadow_v115 as v115

base = v115.base
SHADOW_VERSION = "11.2-baseball-shadow-v1"
PARAM_REPORT = Path("data/v11_2_report.json")
FALLBACK = {
    "intercept": 0.045,
    "relative_lineup_coef": 0.05,
    "regular_overlap_coef": -0.25,
}
_old_analyze = base._analyze_game
_old_metrics = base._metrics


def _params():
    try:
        obj = json.loads(PARAM_REPORT.read_text(encoding="utf-8"))
        p = obj.get("selected_params") or {}
        return {
            "intercept": float(p["intercept"]),
            "relative_lineup_coef": float(p["relative_lineup_coef"]),
            "regular_overlap_coef": float(p["regular_overlap_coef"]),
        }
    except Exception:
        return dict(FALLBACK)


def _logit(p):
    p = core.clamp(core.num(p, .5), .001, .999)
    return math.log(p / (1-p))


def _lineup_terms(row):
    f = row.get("features") or {}
    h = f.get("home_lineup") or {}
    a = f.get("away_lineup") or {}
    if not (h.get("available") and a.get("available")):
        return 0.0, 0.0, False
    try:
        h_lu = float(h["lineup_ops"]); h_reg = float(h["regular_ops"])
        a_lu = float(a["lineup_ops"]); a_reg = float(a["regular_ops"])
    except Exception:
        return 0.0, 0.0, False
    rel = ((h_lu-h_reg) - (a_lu-a_reg)) / .08
    overlap = (h_reg-a_reg) / .08
    return rel, overlap, True


def _v12_probability(row):
    if row.get("base_p_home") is None:
        return None, {}
    p = _params()
    rel, overlap, available = _lineup_terms(row)
    z = _logit(row["base_p_home"])
    z += p["intercept"]
    z += p["relative_lineup_coef"] * rel
    z += p["regular_overlap_coef"] * overlap
    out = core.clamp(1/(1+math.exp(-max(-30, min(30, z)))), .001, .999)
    return out, {
        "relative_lineup_term": round(rel, 6),
        "regular_overlap_term": round(overlap, 6),
        "lineup_available": available,
        "params": p,
    }


def _analyze_game(game, history, recent):
    row = dict(_old_analyze(game, history, recent) or {})
    p, detail = _v12_probability(row)
    row["v11_2_p_home"] = round(p, 6) if p is not None else None
    row["v11_2"] = detail
    row["v11_2_official_effect"] = False
    return row


def _metrics(rows):
    out = dict(_old_metrics(rows) or {})
    usable = [r for r in rows if r.get("base_p_home") is not None and r.get("v11_2_p_home") is not None and r.get("y") in (0, 1)]
    if usable:
        base_losses = [(core.num(r["base_p_home"], .5)-r["y"])**2 for r in usable]
        new_losses = [(core.num(r["v11_2_p_home"], .5)-r["y"])**2 for r in usable]
        out["v11_2_n"] = len(usable)
        out["brier_v11_2_p_home"] = sum(new_losses)/len(new_losses)
        out["brier_gain_v11_2"] = sum(base_losses)/len(base_losses) - sum(new_losses)/len(new_losses)
        out["logloss_v11_2_p_home"] = sum(
            -(r["y"]*math.log(core.clamp(core.num(r["v11_2_p_home"], .5), .001, .999))
              +(1-r["y"])*math.log(1-core.clamp(core.num(r["v11_2_p_home"], .5), .001, .999)))
            for r in usable
        ) / len(usable)
        out["paired_gain_probability_v11_2"] = core.bootstrap_gain_prob(base_losses, new_losses, reps=1000)
    else:
        out.update({
            "v11_2_n": 0,
            "brier_v11_2_p_home": None,
            "brier_gain_v11_2": None,
            "logloss_v11_2_p_home": None,
            "paired_gain_probability_v11_2": None,
        })
    return out


def install():
    v115.install()
    base.SHADOW_VERSION = SHADOW_VERSION
    base._analyze_game = _analyze_game
    base._metrics = _metrics


def self_test():
    install()
    row = {
        "base_p_home": .5,
        "features": {
            "home_lineup": {"available": True, "lineup_ops": .800, "regular_ops": .740},
            "away_lineup": {"available": True, "lineup_ops": .700, "regular_ops": .720},
        },
    }
    p, detail = _v12_probability(row)
    assert p is not None and 0 < p < 1
    assert detail["lineup_available"] is True
    v115.self_test()
    print("SELF-TEST V11.2 LIVE SHADOW OK")


def main():
    install()
    base.main()


if __name__ == "__main__":
    main()
