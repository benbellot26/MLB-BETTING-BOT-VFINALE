import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from v11 import core, market, selector, storage, data_quality, pro_model, context, journal, backtest, config
from v11 import engine_v12 as engine


def fresh():
    return datetime.now(timezone.utc).isoformat()


def future(minutes=60):
    return (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()


class V12Tests(unittest.TestCase):
    def test_score_distribution_and_dispersion_is_effective(self):
        hp, ap = engine.score_matrix(4.6, 4.1, dispersion=3.0)
        hp2, _ = engine.score_matrix(4.6, 4.1, dispersion=15.0)
        self.assertAlmostEqual(sum(hp), 1, places=9)
        self.assertAlmostEqual(sum(ap), 1, places=9)
        self.assertGreater(sum(abs(a-b) for a, b in zip(hp, hp2)), 1e-4)
        self.assertNotAlmostEqual(
            engine.prob_total_parts(4.6, 4.1, "over", 9.0, 3.0)[0],
            engine.prob_total_parts(4.6, 4.1, "over", 9.0, 15.0)[0],
            places=5,
        )

    def test_push_complements(self):
        hw, hp = engine.prob_cover_parts(4.5, 4, "home", -1.0)
        aw, ap = engine.prob_cover_parts(4.5, 4, "away", 1.0)
        self.assertAlmostEqual(hw+aw+hp, 1, places=6)
        self.assertAlmostEqual(hp, ap, places=9)
        ow, op = engine.prob_total_parts(4.5, 4, "over", 9)
        uw, up = engine.prob_total_parts(4.5, 4, "under", 9)
        self.assertAlmostEqual(ow+uw+op, 1, places=6)
        self.assertAlmostEqual(op, up, places=9)

    def test_pair_calibration_preserves_complements_with_intercept(self):
        model = {
            "active": True,
            "calibration": {"ML": {"active": True, "a": .25, "b": .8, "holdout_n": 40, "holdout_brier": .22}},
        }
        a, b, _, src = pro_model.calibrate_pair("ML", .61, .39, model)
        self.assertEqual(src, "champion")
        self.assertAlmostEqual(a+b, 1.0, places=12)

    def test_dispersion_requires_its_own_active_gate(self):
        inactive = {"active": True, "dispersion": {"active": False, "value": 3.0}}
        active = {"active": True, "dispersion": {"active": True, "value": 3.0}}
        self.assertEqual(pro_model.model_dispersion(inactive)[0], config.RUN_DISPERSION)
        self.assertEqual(pro_model.model_dispersion(active)[0], 3.0)

    def test_uncertainty_raises_required_price(self):
        a = {"p_effective": .62, "p_win": .62, "p_push": 0, "model_uncertainty": .005, "winamax_eval": {"price": 2}}
        b = dict(a)
        b["model_uncertainty"] = .05
        self.assertGreater(selector.required_price(b), selector.required_price(a))

    def test_push_aware_kelly(self):
        rec = {"p_effective": .60, "p_win": .54, "p_push": .10, "model_uncertainty": 0, "winamax_eval": {"price": 2}}
        g = selector.value_gate(rec)
        self.assertGreaterEqual(g["p_push"], .10)
        self.assertGreaterEqual(selector.full_kelly(rec, g), 0)

    def test_kelly_below_minimum_is_skipped_not_rounded_up(self):
        rec = {"p_effective": .5001, "p_win": .5001, "p_push": 0, "model_uncertainty": 0, "winamax_eval": {"price": 2}}
        gate = {"price": 2, "p_win": .5001, "p_push": 0}
        units, _, raw = selector.stake_units(rec, gate, .5, 10)
        self.assertLess(raw, config.MIN_STAKE_UNITS)
        self.assertEqual(units, 0)

    def test_missing_sharp_timestamp_is_excluded(self):
        event = {"bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 2}, {"name": "A", "price": 2}]}]}]}
        old = set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS = {"pinnacle"}
            c = market.sharp_consensus(event, "ML", "H")
            self.assertEqual(c["n"], 0)
            self.assertEqual(c["excluded"][0]["reason"], "timestamp_missing")
        finally:
            core.SHARP_BOOKS = old

    def test_stale_sharp_is_excluded(self):
        stale = (datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        event = {"bookmakers": [{"key": "pinnacle", "last_update": stale, "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 2}, {"name": "A", "price": 2}]}]}]}
        old = set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS = {"pinnacle"}
            c = market.sharp_consensus(event, "ML", "H")
            self.assertEqual(c["n"], 0)
            self.assertEqual(c["excluded"][0]["reason"], "stale")
        finally:
            core.SHARP_BOOKS = old

    def test_fresh_devig(self):
        event = {"bookmakers": [{"key": "pinnacle", "last_update": fresh(), "markets": [{"key": "spreads", "outcomes": [
            {"name": "H", "point": -1.5, "price": 2}, {"name": "A", "point": 1.5, "price": 1.9}
        ]}]}]}
        old = set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS = {"pinnacle"}
            h = market.sharp_consensus(event, "RUNLINE", "H", -1.5)
            a = market.sharp_consensus(event, "RUNLINE", "A", 1.5)
            self.assertEqual(h["n"], 1)
            self.assertAlmostEqual(h["p"]+a["p"], 1, places=9)
        finally:
            core.SHARP_BOOKS = old

    def _result(self, phase="FINAL"):
        return {
            "game_pk": 1, "phase": phase,
            "ctx": {
                "home_sp": "HS", "away_sp": "AS", "home_lineup": {"count": 9}, "away_lineup": {"count": 9},
                "home_starter": {"sample_weight": 1}, "away_starter": {"sample_weight": 1},
            },
            "features": {"weather": {"available": True}, "bullpen": {"coverage": 1}},
            "con": {"n": 3, "max_age_min": 1},
        }

    def test_data_quality_final_blocker(self):
        r = self._result()
        r["ctx"]["away_lineup"]["count"] = 2
        rec = {"refs": 3, "sharp_max_age_min": 1, "winamax_eval": {"price": 2}}
        q = data_quality.assess(r, rec)
        self.assertFalse(q["eligible"])
        self.assertIn("final_lineup_incomplete", q["blockers"])

    def test_data_quality_complete(self):
        q = data_quality.assess(self._result(), {"refs": 3, "sharp_max_age_min": 1, "winamax_eval": {"price": 2}})
        self.assertTrue(q["eligible"])

    def test_bullpen_rest_days_are_known_not_missing(self):
        context._BP_CACHE.clear()
        with patch.object(core, "mlb_schedule", return_value=[]):
            state = context.bullpen_state(1, "2026-08-14")
        self.assertEqual(state["coverage"], 1.0)
        self.assertEqual(state["rest_days_observed"], 3)

    def test_bullpen_boxscore_failure_reduces_coverage(self):
        context._BP_CACHE.clear()
        game = {"gamePk": 10, "status": {"abstractGameState": "Final"}}
        with patch.object(core, "mlb_schedule", return_value=[game]), patch.object(core, "mlb", side_effect=RuntimeError("boom")):
            state = context.bullpen_state(2, "2026-08-14")
        self.assertEqual(state["boxscores_expected"], 3)
        self.assertEqual(state["boxscores_ok"], 0)
        self.assertEqual(state["coverage"], 0.0)

    def test_canonical_settled_rows_deduplicates_same_game(self):
        base_row = {
            "game_pk": 10, "game_date": "2026-08-14T20:00:00+00:00", "result_status": "FINAL",
            "home_score": 5, "away_score": 4, "features": {"home_ops": .7},
            "structural_home_runs": 4.5, "structural_away_runs": 4.2, "model": {"active": False},
        }
        a = dict(base_row, analyzed_at="2026-08-14T10:00:00+00:00")
        b = dict(base_row, analyzed_at="2026-08-14T18:00:00+00:00")
        c = dict(base_row, analyzed_at="2026-08-14T21:00:00+00:00")
        rows = pro_model.canonical_settled_rows([a, b, c])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["analyzed_at"], b["analyzed_at"])

    def test_challenger_uses_structural_not_previous_champion_projection(self):
        row = {
            "structural_home_runs": 4.1, "structural_away_runs": 3.9,
            "projected_home_runs": 5.0, "projected_away_runs": 4.8,
            "model": {"active": True},
        }
        self.assertEqual(pro_model.base_runs(row), (4.1, 3.9))

    def test_canonical_market_line_avoids_easy_alt_line(self):
        row = {
            "home": "H", "away": "A",
            "options": [
                {"market": "RUNLINE", "name": "H", "point": 4.5, "p_model": .90},
                {"market": "RUNLINE", "name": "A", "point": -4.5, "p_model": .10},
                {"market": "RUNLINE", "name": "H", "point": -1.5, "p_model": .51},
                {"market": "RUNLINE", "name": "A", "point": 1.5, "p_model": .49},
            ],
        }
        self.assertEqual(pro_model.canonical_market_option(row, "RUNLINE")["point"], -1.5)

    def test_journal_metrics_use_canonical_line(self):
        row = {
            "game_pk": 1, "result_status": "FINAL", "home": "H", "away": "A", "analyzed_at": "2026-08-14T12:00:00Z",
            "options": [
                {"market": "RUNLINE", "name": "H", "point": 4.5, "p_model": .90, "p_effective": .90, "result": "WIN", "brier": .01, "logloss": .1},
                {"market": "RUNLINE", "name": "A", "point": -4.5, "p_model": .10, "p_effective": .10, "result": "LOSS", "brier": .01, "logloss": .1},
                {"market": "RUNLINE", "name": "H", "point": -1.5, "p_model": .51, "p_effective": .51, "result": "LOSS", "brier": .2601, "logloss": .713},
                {"market": "RUNLINE", "name": "A", "point": 1.5, "p_model": .49, "p_effective": .49, "result": "WIN", "brier": .2601, "logloss": .713},
            ],
        }
        m = journal.metrics([row])["by_market"]["RUNLINE"]
        self.assertEqual(m["wins"], 0)
        self.assertAlmostEqual(m["brier"], .2601)

    def test_persistent_daily_cap_counts_existing_runs(self):
        result = {
            "game_pk": 99, "phase": "FINAL",
            "ctx": {"home_sp": "HSP", "away_sp": "ASP", "home_lineup": {"count": 9}, "away_lineup": {"count": 9},
                    "home_starter": {"sample_weight": 1}, "away_starter": {"sample_weight": 1}},
            "features": {"weather": {"available": True}, "bullpen": {"coverage": 1}},
            "con": {"n": 3, "max_age_min": 1},
            "options": [{"market": "ML", "name": "H", "point": None, "p_effective": .70, "p_win": .70, "p_push": 0,
                         "refs": 3, "sharp_max_age_min": 1, "model_uncertainty": 0,
                         "winamax_eval": {"price": 2.0}}],
        }
        existing = {
            "old": {"status": "PLACED", "target_date": "2026-08-14", "game_pk": 1, "market": "ML", "units": config.MAX_DAILY_UNITS}
        }
        _, chosen, combo, _ = selector.allocate([result], .5, 10, existing, "2026-08-14")
        self.assertEqual(chosen, [])
        self.assertFalse(combo.get("official"))

    def test_ledger_idempotency(self):
        old = storage.BET_LEDGER_FILE
        with tempfile.TemporaryDirectory() as td:
            storage.BET_LEDGER_FILE = Path(td)/"ledger.jsonl"
            result = {"game_pk": 11, "game": {"gameDate": future()}, "ctx": {"home": "H", "away": "A"}}
            rec = {"market": "ML", "name": "H", "point": None, "p_effective": .6, "p_win": .6, "p_push": 0,
                   "p_market": .58, "model_uncertainty": .01, "data_quality": {"score": 1},
                   "winamax_eval": {"official_selected": True, "official_units": 1, "stake_eur": .5, "price": 1.9}}
            c = {"result": result, "rec": rec}
            self.assertEqual(storage.record_selected_bets([c], None, "r1", fresh(), "2026-08-14"), 1)
            self.assertEqual(storage.record_selected_bets([c], None, "r2", fresh(), "2026-08-14"), 0)
        storage.BET_LEDGER_FILE = old

    def test_clv_is_close_candidate_not_false_true_close(self):
        old = storage.BET_LEDGER_FILE
        with tempfile.TemporaryDirectory() as td:
            storage.BET_LEDGER_FILE = Path(td)/"ledger.jsonl"
            at = datetime.now(timezone.utc)
            result = {"game_pk": 11, "game": {"gameDate": (at+timedelta(minutes=5)).isoformat()}, "ctx": {"home": "H", "away": "A"}}
            rec = {"market": "ML", "name": "H", "point": None, "p_effective": .6, "p_win": .6, "p_push": 0, "p_market": .59,
                   "model_uncertainty": .01, "data_quality": {"score": 1},
                   "winamax_eval": {"official_selected": True, "official_units": 1, "stake_eur": .5, "price": 1.9}}
            c = {"result": result, "rec": rec}
            storage.record_selected_bets([c], None, "r1", at.isoformat(), "2026-08-14")
            storage.update_clv([dict(result, options=[rec])], at.isoformat())
            state = next(iter(storage.fold_ledger().values()))
            self.assertEqual(state["close_candidate_price"], 1.9)
            self.assertNotIn("closing_price", state)
        storage.BET_LEDGER_FILE = old

    def test_snapshot_is_gzipped_for_durable_archive(self):
        old = storage.SNAPSHOT_DIR
        with tempfile.TemporaryDirectory() as td:
            storage.SNAPSHOT_DIR = Path(td)
            p = storage.snapshot_run([{"gamePk": 1}], [{"id": "e"}], "r", fresh(), "2026-08-14")
            self.assertEqual(p.suffix, ".gz")
            with gzip.open(p, "rt", encoding="utf-8") as f:
                d = json.load(f)
            self.assertEqual(d["games"][0]["gamePk"], 1)
        storage.SNAPSHOT_DIR = old

    def test_settlement_push(self):
        row = {"result_status": "FINAL", "home": "H", "away": "A", "home_score": 4, "away_score": 3}
        opt = {"market": "RUNLINE", "name": "A", "point": 1, "p_effective": .55}
        journal.settle_option(opt, row)
        self.assertEqual(opt["result"], "PUSH")

    def test_integration_analyze_preserves_pairs(self):
        ctx = {
            "home": "H", "away": "A", "home_id": 1, "away_id": 2, "home_sp": "HS", "away_sp": "AS",
            "home_lineup": {"count": 9}, "away_lineup": {"count": 9},
            "home_starter": {}, "away_starter": {},
        }
        event = {"bookmakers": [{"key": core.WINAMAX_KEY, "markets": [
            {"key": "spreads", "outcomes": [{"name": "H", "point": -1.5, "price": 2}, {"name": "A", "point": 1.5, "price": 1.8}]},
            {"key": "totals", "outcomes": [{"name": "Over", "point": 8.5, "price": 1.9}, {"name": "Under", "point": 8.5, "price": 1.9}]},
        ]}]}
        projected = (4.5, 4.1, 4.7, 4.0, ctx, {"weather": {}, "bullpen": {"coverage": 1}}, {"active": False}, 7.5)
        with patch.object(engine, "_project", return_value=projected), \
             patch.object(core, "phase_for_game", return_value="FINAL"), \
             patch.object(market, "sharp_consensus", return_value={"p": None, "n": 0, "books": [], "robustness": 0, "effective_n": 0, "max_age_min": None}), \
             patch.object(core, "winamax_price", return_value=1.9):
            r = engine.analyze({"gamePk": 1}, event)
        ml = [o for o in r["options"] if o["market"] == "ML"]
        self.assertAlmostEqual(sum(o["p_effective"] for o in ml), 1, places=6)
        total = [o for o in r["options"] if o["market"] == "TOTAL"]
        self.assertAlmostEqual(sum(o["p_effective"] for o in total), 1, places=6)

    def test_workflow_defers_discord_until_after_durable_state(self):
        text = Path(".github/workflows/mlb-bot.yml").read_text(encoding="utf-8")
        self.assertIn("V12_DEFER_DISCORD: '1'", text)
        self.assertLess(text.index("Persist official execution state"), text.index("Send Discord after persistence"))
        self.assertIn("v12-data-archive", text)


if __name__ == "__main__":
    unittest.main()
