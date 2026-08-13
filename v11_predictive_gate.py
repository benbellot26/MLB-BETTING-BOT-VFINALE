#!/usr/bin/env python3
"""Evidence gate for an optional V11 Moneyline model+sharp blend.

The gate is deliberately separate from `bot_v11.py`: the sharp benchmark can
run immediately, while the blend can only affect ML effective probabilities if
its weight was selected on chronological training data and it then beat the
independent effective model on a sufficiently large recent holdout.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import bot as core
import bot_v11 as v11

REPORT_FILE = Path(os.getenv("V11_BENCHMARK_REPORT", "data/v11_benchmark_report.json"))
ENABLED = os.getenv("V11_AUTO_BLEND_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
MIN_HOLDOUT = max(20, int(os.getenv("V11_AUTO_BLEND_MIN_HOLDOUT", "40") or 40))
MIN_BRIER_GAIN = max(.0005, float(os.getenv("V11_AUTO_BLEND_MIN_BRIER_GAIN", "0.0015") or .0015))
MIN_MULTIREF_PCT = core.clamp(float(os.getenv("V11_AUTO_BLEND_MIN_MULTIREF_PCT", "0.60") or .60), .40, .95)

_ORIGINAL_APPLY_EFFECTIVE = core.v1011_apply_effective
_STATE = None
_INSTALLED = False


def blend_state() -> dict:
    global _STATE
    if _STATE is not None:
        return _STATE
    out = {"active": False, "weight": None, "reason": "disabled", "holdout_n": 0, "brier_gain": None, "multiref_pct": None}
    if not ENABLED:
        out["reason"] = "auto blend disabled"; _STATE = out; return out
    if not REPORT_FILE.exists():
        out["reason"] = "benchmark report absent"; _STATE = out; return out
    try:
        report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
        if report.get("benchmark_version") != v11.BENCHMARK_VERSION:
            out["reason"] = "benchmark version mismatch"; _STATE = out; return out
        hold = report.get("holdout") or {}; cov = report.get("coverage") or {}
        n = int(core.num(report.get("holdout_n", hold.get("n", 0)), 0)); weight = report.get("blend_model_weight_selected_on_train")
        model_brier = hold.get("brier_model"); blend_brier = hold.get("brier_blend")
        model_ll = hold.get("logloss_model"); blend_ll = hold.get("logloss_blend")
        multiref_pct = cov.get("holdout_multiref_pct")
        if multiref_pct is None:
            matched = max(1, int(core.num(cov.get("matched_model_and_sharp"), 0)))
            multiref_pct = int(core.num(cov.get("two_or_more_sharp_refs"), 0)) / matched
        gain = (core.num(model_brier) - core.num(blend_brier)) if model_brier is not None and blend_brier is not None else None
        out.update({
            "weight": core.num(weight, 0) if weight is not None else None,
            "holdout_n": n,
            "brier_gain": gain,
            "multiref_pct": core.num(multiref_pct, 0),
            "brier_model": model_brier,
            "brier_blend": blend_brier,
            "logloss_model": model_ll,
            "logloss_blend": blend_ll,
        })
        checks = [
            n >= MIN_HOLDOUT,
            weight is not None and .25 <= core.num(weight) <= .80,
            gain is not None and gain >= MIN_BRIER_GAIN,
            model_ll is not None and blend_ll is not None and core.num(blend_ll) <= core.num(model_ll),
            core.num(multiref_pct, 0) >= MIN_MULTIREF_PCT,
        ]
        if all(checks):
            out["active"] = True; out["reason"] = "validated chronological holdout"
        else:
            out["reason"] = "holdout evidence insufficient"
    except Exception as exc:
        out["reason"] = f"benchmark report unreadable: {exc}"
    _STATE = out
    return out


def apply_effective(rec, result):
    rec = _ORIGINAL_APPLY_EFFECTIVE(rec, result)
    if not rec or rec.get("market") != "ML":
        return rec

    state = blend_state()
    independent = core.clamp(core.num(rec.get("p_effective"), .5), .001, .999)
    rec["p_effective_independent"] = independent
    rec["predictive_blend_active"] = False
    rec["predictive_blend_state"] = dict(state)
    sharp = rec.get("p_market")
    if not state.get("active") or sharp is None or state.get("weight") is None:
        return rec

    w = core.clamp(core.num(state.get("weight"), .55), .25, .80)
    sharp = core.clamp(core.num(sharp, .5), .001, .999)
    blended = core.clamp(w * independent + (1-w) * sharp, .001, .999)
    pp = core.clamp(core.num(rec.get("p_push"), 0), 0, .95); mass = 1-pp
    pw = mass * blended; pl = mass * (1-blended)
    rec.update({
        "p_effective": blended,
        "p_effective_win": pw,
        "p_effective_loss": pl,
        "fair_effective": (1-pp)/pw if pw > 0 else 99,
        "min_price_effective": core.min_acceptable_price(pw, pp, pl),
        "predictive_blend_active": True,
        "predictive_blend_weight": w,
        "predictive_sharp_probability": sharp,
    })
    e = rec.get("winamax_eval")
    if isinstance(e, dict):
        price = core.num(e.get("price"), 0); np = pw+pl; pcond = pw/np if np else .5
        e.update({
            "p_win": pw, "p_push": pp, "p_loss": pl, "p_cond": pcond,
            "fair": rec["fair_effective"], "min_price": rec["min_price_effective"],
            "effective_probability": blended,
            "effective_probability_source": "validated-model-sharp-blend",
            "effective_min_price": rec["min_price_effective"],
            "edge": pcond-1/price if price > 1 else None,
            "ev": pw*price+pp-1 if price > 1 else None,
        })
    return rec


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    v11.install_v11()
    core.v1011_apply_effective = apply_effective

    base_snapshot = core.build_snapshot
    def snapshot_with_gate(result, rec):
        snap = base_snapshot(result, rec); snap["predictive_blend_state"] = blend_state(); return snap
    core.build_snapshot = snapshot_with_gate

    base_rows = core.v1010_make_run_rows
    def rows_with_gate(results, run_id=None, analyzed_at=None):
        rows = base_rows(results, run_id, analyzed_at)
        for row in rows: row["predictive_blend_state"] = blend_state()
        return rows
    core.v1010_make_run_rows = rows_with_gate

    state = blend_state()
    logging.info(
        "V11 PREDICTIVE GATE | active=%s weight=%s holdout=%d gain=%s multiRef=%s reason=%s",
        state.get("active"), f"{core.num(state.get('weight')):.2f}" if state.get("weight") is not None else "-",
        int(core.num(state.get("holdout_n"), 0)),
        f"{core.num(state.get('brier_gain')):+.4f}" if state.get("brier_gain") is not None else "-",
        f"{100*core.num(state.get('multiref_pct')):.0f}%" if state.get("multiref_pct") is not None else "-",
        state.get("reason"),
    )
    _INSTALLED = True


def self_test() -> None:
    global _STATE
    old = _STATE
    try:
        _STATE = {"active": True, "weight": .60, "reason": "test", "holdout_n": 100, "brier_gain": .002, "multiref_pct": .8}
        rec = {"market": "ML", "p_effective": .62, "p_market": .58, "p_push": 0, "winamax_eval": {"price": 1.80}}
        out = apply_effective(rec, {})
        assert out["predictive_blend_active"]
        assert abs(out["p_effective"] - .604) < 1e-12
        assert abs(out["p_effective_independent"] - .62) < 1e-12
        _STATE = {"active": False, "weight": .60, "reason": "test off", "holdout_n": 10, "brier_gain": 0, "multiref_pct": .8}
        rec2 = {"market": "ML", "p_effective": .62, "p_market": .58, "p_push": 0, "winamax_eval": {}}
        out2 = apply_effective(rec2, {})
        assert not out2["predictive_blend_active"] and abs(out2["p_effective"]-.62) < 1e-12
    finally:
        _STATE = old
    print("SELF-TEST V11 PREDICTIVE GATE OK")


def main() -> None:
    install(); core.main()


if __name__ == "__main__":
    try:
        if "--self-test" in sys.argv:
            core.v10_self_test(); v11.install_v11(); v11.v11_self_test(); self_test()
        else:
            main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        logging.exception("ERREUR FATALE V11 PREDICTIVE GATE")
        raise
