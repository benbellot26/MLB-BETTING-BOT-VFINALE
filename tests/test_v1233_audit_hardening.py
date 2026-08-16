from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import config
from v11 import v1233_audit_hardening as hard


class AuditHardeningTests(unittest.TestCase):
    def test_dq_no_longer_requires_winamax_execution_price(self):
        def original(result, rec):
            return {
                "score": .70,
                "components": {"starter_identity": 1, "starter_stats": 1, "lineup_identity": 1, "lineup_stats": 1,
                               "team_stats": 1, "weather": 1, "bullpen": 1, "sharp_coverage": 1, "sharp_recency": 1,
                               "execution_price": 0},
                "blockers": ["execution_price_missing"], "eligible": False,
            }
        out = hard._dq_without_execution_dependency({}, {"market": "ML"}, original, config)
        self.assertTrue(out["eligible"])
        self.assertNotIn("execution_price_missing", out["blockers"])
        self.assertFalse(out["execution_price_required_for_selection"])

    def test_large_sharp_gap_requires_extra_ev(self):
        rec = {"p_effective": .64}
        base = lambda r: {"ok": True, "ev_at_price": .035, "sharp_disagreement": .14,
                          "reference_quote_count": 3, "min_confidence": .58}
        out = hard._gate_hardening(rec, base, config)
        self.assertFalse(out["ok"])
        self.assertFalse(out["sharp_gap_ok"])

    def test_single_quote_requires_extra_ev_and_confidence(self):
        rec = {"p_effective": .59}
        base = lambda r: {"ok": True, "ev_at_price": .04, "sharp_disagreement": .02,
                          "reference_quote_count": 1, "min_confidence": .58}
        out = hard._gate_hardening(rec, base, config)
        self.assertFalse(out["ok"])
        self.assertTrue(out["single_sharp_quote"])
        self.assertFalse(out["reference_depth_ok"])

    def test_posthoc_lineup_and_platoon_are_not_trainable(self):
        modules = {"lineup_player": {"coverage": 1, "status": "ACTIVE"},
                   "platoon": {"coverage": .8, "status": "ACTIVE"},
                   "starter_ip": {"coverage": 1, "status": "ACTIVE"}}
        out = hard.neutralize_posthoc_identity_modules(modules)
        self.assertEqual(out["lineup_player"]["coverage"], 0)
        self.assertEqual(out["platoon"]["coverage"], 0)
        self.assertEqual(out["starter_ip"]["coverage"], 1)

    def test_day_walkforward_never_splits_same_calendar_day(self):
        class Opt:
            MIN_GAMES = 3
            WF_TEST_GAMES = 2
            MODULES = ("x",)
            @staticmethod
            def fit_weights(train): return {"x": 0}
            @staticmethod
            def evaluate(exs, weights):
                n=len(exs)
                return {"games": n, "options": n, "brier": .25, "logloss": .69,
                        "team_run_mae": 2.0, "total_run_mae": 3.0}
        exs = [
            {"sort_key":"2026-06-01T10:00:00Z"}, {"sort_key":"2026-06-01T20:00:00Z"},
            {"sort_key":"2026-06-02T10:00:00Z"}, {"sort_key":"2026-06-02T20:00:00Z"},
            {"sort_key":"2026-06-03T10:00:00Z"}, {"sort_key":"2026-06-03T20:00:00Z"},
        ]
        out = hard.day_block_walk_forward(exs, Opt)
        self.assertEqual(out["boundary"], "calendar_day")
        for w in out.get("windows_detail", []):
            self.assertNotIn(w.get("train_through"), w.get("test_days") or [])

    def test_portfolio_haircut_never_increases_units(self):
        class C:
            MIN_STAKE_UNITS=.25; MAX_DAILY_UNITS=4
        def c(m,u):
            return {"rec":{"market":m,"winamax_eval":{"official_units":u,"units":u,"stake_eur":u*.5}}}
        chosen=[c("ML",1.0), c("ML",1.0), c("TOTAL",1.0)]
        p={"existing_allocated":0}
        out, chosen=hard._portfolio_haircut(p, chosen, .5, 10.0, C)
        vals=[x["rec"]["winamax_eval"]["official_units"] for x in chosen]
        self.assertLessEqual(vals[1], vals[0])
        self.assertTrue(all(v <= 1.0 for v in vals))
        self.assertLessEqual(out["new_official_units"], 3.0)

    def test_delivery_checkpoint_skips_already_sent_blocks(self):
        calls=[]
        class Core:
            @staticmethod
            def discord_test(): return True
        class D:
            @staticmethod
            def send_game(r,p): calls.append("game"); return True
            @staticmethod
            def send_top(r): calls.append("top"); return True
            @staticmethod
            def send_plan(*a): calls.append("plan"); return True
            @staticmethod
            def send_health(h): calls.append("health"); return True
        class R:
            core=Core; discord=D
            @staticmethod
            def _summary(r): calls.append("summary"); return True
        with tempfile.TemporaryDirectory() as tmp:
            old=hard.DELIVERY_FILE
            hard.DELIVERY_FILE=Path(tmp)/"delivery.json"
            try:
                hard._install_delivery_checkpoint(R)
                payload=[{"game_pk":1}]
                self.assertTrue(R._send(payload,{},[],{}, {}, {"run_id":"abc"}))
                first=list(calls)
                self.assertTrue(R._send(payload,{},[],{}, {}, {"run_id":"abc"}))
                self.assertEqual(calls, first)
                saved=json.loads(hard.DELIVERY_FILE.read_text())
                self.assertIn("summary", saved["abc"]["sent"])
            finally:
                hard.DELIVERY_FILE=old


if __name__ == "__main__":
    unittest.main()
