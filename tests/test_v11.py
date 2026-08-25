import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from v11 import core, market, selector, storage, data_quality, pro_model, context, journal, backtest, config
from v11 import engine_v12 as engine


def iso(dt): return dt.astimezone(timezone.utc).isoformat()
def now(): return datetime.now(timezone.utc)


class V122Tests(unittest.TestCase):
    def test_joint_distribution_dynamic_and_normalized(self):
        j = engine.joint_score_matrix(7.2, 6.5, dispersion=2.5, env_sigma=.15)
        self.assertGreaterEqual(len(j), config.MAX_RUNS_MATRIX+1)
        self.assertAlmostEqual(sum(sum(r) for r in j), 1.0, places=9)

    def test_shared_environment_changes_total_probability(self):
        a = engine.prob_total_parts(5.2, 4.8, "over", 10.5, 7.5, 0.0)[0]
        b = engine.prob_total_parts(5.2, 4.8, "over", 10.5, 7.5, .18)[0]
        self.assertNotAlmostEqual(a, b, places=5)

    def test_dispersion_is_effective(self):
        a = engine.prob_total_parts(4.6, 4.1, "over", 9.0, 3.0, .08)[0]
        b = engine.prob_total_parts(4.6, 4.1, "over", 9.0, 15.0, .08)[0]
        self.assertNotAlmostEqual(a, b, places=5)

    def test_push_complements(self):
        hw, hp = engine.prob_cover_parts(4.5, 4, "home", -1.0)
        aw, ap = engine.prob_cover_parts(4.5, 4, "away", 1.0)
        self.assertAlmostEqual(hp, ap, places=8)
        self.assertAlmostEqual(hw+aw+hp, 1.0, places=6)

    def test_phase_calibration_preserves_complements(self):
        model = {"active": True, "phase_models": {"FINAL": {"calibration": {"ML": {
            "side": {"active": True, "a": .25, "b": .8}, "push": {"active": False}}}}}}
        a, b, push, src = pro_model.calibrate_triplet("ML", .61, .39, 0, model, "FINAL")
        self.assertEqual(src, "champion")
        self.assertAlmostEqual(a+b, 1.0, places=12)
        self.assertEqual(push, 0)

    def test_push_calibration_is_third_outcome(self):
        model = {"active": True, "phase_models": {"FINAL": {"calibration": {"TOTAL": {
            "side": {"active": False}, "push": {"active": True, "a": -.2, "b": .9}}}}}}
        a, b, push, _ = pro_model.calibrate_triplet("TOTAL", .55, .45, .08, model, "FINAL")
        self.assertAlmostEqual(a+b, 1.0, places=12)
        self.assertGreater(push, 0)
        self.assertLess(push, 1)

    def test_missing_feature_imputation_uses_train_mean(self):
        rows = [{"features": {"home_ops": .7}}, {"features": {"home_ops": .8}}, {"features": {}}]
        means, _, observed = pro_model._feature_stats(rows)
        self.assertAlmostEqual(means["home_ops"], .75)
        self.assertEqual(observed["home_ops"], 2)
        self.assertAlmostEqual(pro_model.vector(rows[2], means)[0], .75)

    def _settled(self, gid=1, phase="FINAL", at="2026-08-14T18:00:00+00:00"):
        return {"schema": config.SCHEMA_VERSION, "engine_version": config.VERSION,
                "feature_schema": config.FEATURE_SCHEMA_VERSION, "game_pk": gid, "phase": phase,
                "game_date": "2026-08-14T20:00:00+00:00", "analyzed_at": at,
                "result_status": "FINAL", "home_score": 5, "away_score": 4,
                "features": {"home_ops": .72}, "structural_home_runs": 4.5, "structural_away_runs": 4.2,
                "home": "H", "away": "A", "options": []}

    def test_phase_snapshots_are_kept_without_cross_phase_leakage(self):
        a = self._settled(1, "EARLY", "2026-08-14T10:00:00+00:00")
        b = self._settled(1, "LATE", "2026-08-14T17:00:00+00:00")
        c = self._settled(1, "FINAL", "2026-08-14T18:00:00+00:00")
        d = self._settled(1, "FINAL", "2026-08-14T19:00:00+00:00")
        rows = pro_model.canonical_phase_rows([a, b, c, d], compatible_only=True)
        self.assertEqual(len(rows), 3)
        self.assertEqual(pro_model.canonical_settled_rows(rows)[0]["analyzed_at"], d["analyzed_at"])

    def test_old_model_generation_is_excluded_from_training(self):
        old = self._settled(); old["engine_version"] = "11.5"
        self.assertEqual(pro_model.canonical_phase_rows([old], compatible_only=True), [])

    def test_fixed_canonical_line_marker_wins(self):
        row = {"home": "H", "away": "A", "options": [
            {"market": "TOTAL", "name": "Over", "point": 7.5}, {"market": "TOTAL", "name": "Under", "point": 7.5},
            {"market": "TOTAL", "name": "Over", "point": 9.5, "is_canonical_line": True},
            {"market": "TOTAL", "name": "Under", "point": 9.5, "is_canonical_line": True}]}
        self.assertEqual(pro_model.canonical_market_option(row, "TOTAL")["point"], 9.5)

    def test_invalid_champion_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"model.json"
            p.write_text(json.dumps({"active": True, "version": "bad", "metadata": {"feature_schema_hash": "bad"}}))
            m = pro_model.load_model(p)
            self.assertEqual(m["artifact_status"], "INCOMPATIBLE")
            self.assertFalse(m["active"])

    def _result(self):
        players = [{"ops": .7} for _ in range(9)]
        return {"game_pk": 1, "phase": "FINAL", "model": {"artifact_status": "ABSENT"},
                "ctx": {"home_sp": "HS", "away_sp": "AS", "home_lineup": {"count": 9, "players": players},
                        "away_lineup": {"count": 9, "players": players},
                        "home_starter": {"current_stats_available": True}, "away_starter": {"current_stats_available": True}},
                "features": {"weather": {"available": True}, "bullpen": {"coverage": 1},
                             "source_quality": {"home_team_hitting": True, "away_team_hitting": True,
                                                "home_team_pitching": True, "away_team_pitching": True,
                                                "home_lineup_usable_ops": 9, "away_lineup_usable_ops": 9}},
                "con": {"n": 3, "max_age_min": 1}}

    def test_data_quality_complete(self):
        q = data_quality.assess(self._result(), {"refs": 3, "sharp_max_age_min": 1, "winamax_eval": {"price": 2}})
        self.assertTrue(q["eligible"])

    def test_data_quality_blocks_lineup_without_usable_stats(self):
        r = self._result(); r["features"]["source_quality"]["home_lineup_usable_ops"] = 0; r["features"]["source_quality"]["away_lineup_usable_ops"] = 0
        q = data_quality.assess(r, {"refs": 3, "sharp_max_age_min": 1, "winamax_eval": {"price": 2}})
        self.assertIn("final_lineup_stats_incomplete", q["blockers"])

    def test_data_quality_blocks_invalid_model_artifact(self):
        r = self._result(); r["model"] = {"artifact_status": "INVALID", "artifact_error": "json"}
        q = data_quality.assess(r, {"refs": 3, "sharp_max_age_min": 1, "winamax_eval": {"price": 2}})
        self.assertIn("model_artifact_invalid", q["blockers"])

    def test_market_freshness_uses_explicit_asof(self):
        asof = datetime(2026, 8, 14, 18, tzinfo=timezone.utc)
        event = {"bookmakers": [{"key": "pinnacle", "last_update": iso(asof-timedelta(minutes=20)),
                                  "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 2}, {"name": "A", "price": 2}]}]}]}
        old = set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS = {"pinnacle"}
            self.assertEqual(market.sharp_consensus(event, "ML", "H", as_of=iso(asof))["n"], 1)
            self.assertEqual(market.sharp_consensus(event, "ML", "H", as_of=iso(asof+timedelta(hours=2)))["n"], 0)
        finally: core.SHARP_BOOKS = old

    def test_kelly_below_minimum_is_skipped(self):
        rec = {"p_effective": .5001, "p_win": .5001, "p_push": 0, "model_uncertainty": 0, "winamax_eval": {"price": 2}}
        units, _, raw = selector.stake_units(rec, {"price": 2, "p_win": .5001, "p_push": 0}, .5, 10)
        self.assertLess(raw, config.MIN_STAKE_UNITS); self.assertEqual(units, 0)

    def test_official_combos_are_disabled(self):
        self.assertFalse(config.ENABLE_OFFICIAL_COMBOS)

    def test_ledger_lifecycle_is_explicit(self):
        old = storage.BET_LEDGER_FILE
        with tempfile.TemporaryDirectory() as td:
            storage.BET_LEDGER_FILE = Path(td)/"ledger.jsonl"
            result = {"game_pk": 11, "game": {"gameDate": iso(now()+timedelta(hours=1))}, "ctx": {"home": "H", "away": "A"}}
            rec = {"market": "ML", "name": "H", "point": None, "p_effective": .6, "p_win": .6, "p_push": 0,
                   "p_market": .58, "model_uncertainty": .02, "data_quality": {"score": 1},
                   "winamax_eval": {"official_selected": True, "official_units": 1, "stake_eur": .5, "price": 1.9}}
            c = {"result": result, "rec": rec}
            storage.record_selected_bets([c], None, "r1", iso(now()), "2026-08-14")
            state = next(iter(storage.fold_ledger().values())); self.assertEqual(state["status"], "PROPOSED")
            storage.mark_run_published("r1"); state = next(iter(storage.fold_ledger().values())); self.assertEqual(state["status"], "PUBLISHED")
            storage.confirm_placed(state["bet_key"], 1.91); state = next(iter(storage.fold_ledger().values())); self.assertEqual(state["status"], "CONFIRMED_PLACED")
        storage.BET_LEDGER_FILE = old

    def test_clv_requires_published_recommendation(self):
        old = storage.BET_LEDGER_FILE
        with tempfile.TemporaryDirectory() as td:
            storage.BET_LEDGER_FILE = Path(td)/"ledger.jsonl"; at = now()
            result = {"game_pk": 11, "game": {"gameDate": iso(at+timedelta(minutes=5))}, "ctx": {"home": "H", "away": "A"}}
            rec = {"market": "ML", "name": "H", "point": None, "p_effective": .6, "p_win": .6, "p_push": 0, "p_market": .59,
                   "model_uncertainty": .02, "data_quality": {"score": 1}, "winamax_eval": {"official_selected": True, "official_units": 1, "stake_eur": .5, "price": 1.9}}
            storage.record_selected_bets([{"result": result, "rec": rec}], None, "r1", iso(at), "2026-08-14")
            storage.update_clv([dict(result, options=[rec])], iso(at)); self.assertNotIn("close_candidate_price", next(iter(storage.fold_ledger().values())))
            storage.mark_run_published("r1"); storage.update_clv([dict(result, options=[rec])], iso(at))
            self.assertEqual(next(iter(storage.fold_ledger().values()))["close_candidate_price"], 1.9)
        storage.BET_LEDGER_FILE = old

    def test_http_replay_returns_recorded_response_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"r.gz"; url = "https://example.test/a?apiKey=secret&x=1"; key = core._request_key(url)
            with gzip.open(path, "wt", encoding="utf-8") as f: json.dump({"analyzed_at": "2026-08-14T10:00:00+00:00", "calls": [{"request_key": key, "response": {"ok": 1}}]}, f)
            core.load_http_replay(path)
            try: self.assertEqual(core.http_json(url), {"ok": 1})
            finally: core.clear_http_replay()

    def test_multiclass_backtest_keeps_push(self):
        r = self._settled(); r["options"] = [
            {"market": "TOTAL", "name": "Over", "point": 9, "is_canonical_line": True, "result": "PUSH", "p_effective": .55, "p_win": .45, "p_push": .18, "p_push_model": .15, "p_model": .54, "p_market": .53},
            {"market": "TOTAL", "name": "Under", "point": 9, "is_canonical_line": True, "result": "PUSH", "p_effective": .45, "p_win": .37, "p_push": .18, "p_push_model": .15, "p_model": .46, "p_market": .47}]
        m = backtest._market([r], "TOTAL")
        self.assertEqual(m["n"], 1); self.assertGreater(m["model"]["multiclass_logloss"], 0)

    def test_integration_analyze_preserves_pair_and_fixed_line(self):
        ctx = {"home": "H", "away": "A", "home_id": 1, "away_id": 2, "home_sp": "HS", "away_sp": "AS",
               "home_lineup": {"count": 9}, "away_lineup": {"count": 9}, "home_starter": {}, "away_starter": {}}
        event = {"bookmakers": [{"key": core.WINAMAX_KEY, "markets": [
            {"key": "spreads", "outcomes": [{"name": "H", "point": -1.5, "price": 2}, {"name": "A", "point": 1.5, "price": 1.8}]},
            {"key": "totals", "outcomes": [{"name": "Over", "point": 8.5, "price": 1.9}, {"name": "Under", "point": 8.5, "price": 1.9}]}]}]}
        projected = (4.5, 4.1, 4.7, 4.0, ctx, {"weather": {}, "bullpen": {"coverage": 1}}, {"active": False}, 7.5, .08)
        with patch.object(engine, "_project", return_value=projected), patch.object(core, "phase_for_game", return_value="FINAL"), \
             patch.object(market, "sharp_consensus", return_value={"p": None, "n": 0, "books": [], "robustness": 0, "effective_n": 0, "max_age_min": None, "dispersion": None}), \
             patch.object(core, "winamax_price", return_value=1.9):
            r = engine.analyze({"gamePk": 1}, event, as_of=iso(now()))
        ml = [o for o in r["options"] if o["market"] == "ML"]
        self.assertAlmostEqual(sum(o["p_effective"] for o in ml), 1, places=6)
        self.assertTrue(any(o["is_canonical_line"] for o in r["options"] if o["market"] == "TOTAL"))

    def test_sharp_fallback_analyzes_runline_total_without_winamax(self):
        at = now()
        ctx = {"home": "H", "away": "A", "home_id": 1, "away_id": 2, "home_sp": "HS", "away_sp": "AS",
               "home_lineup": {"count": 0}, "away_lineup": {"count": 0}, "home_starter": {}, "away_starter": {}}
        event = {"bookmakers": [{"key": "pinnacle", "last_update": iso(at-timedelta(minutes=1)), "markets": [
            {"key": "h2h", "outcomes": [{"name": "H", "price": 1.9}, {"name": "A", "price": 2.0}]},
            {"key": "spreads", "outcomes": [{"name": "H", "point": -1.5, "price": 2.2}, {"name": "A", "point": 1.5, "price": 1.72}]},
            {"key": "totals", "outcomes": [{"name": "Over", "point": 8.5, "price": 1.91}, {"name": "Under", "point": 8.5, "price": 1.91}]}]}]}
        projected = (4.5, 4.1, 4.5, 4.1, ctx, {"weather": {}, "bullpen": {"coverage": 1}}, {"active": False}, 7.5, .08)
        with patch.object(engine, "_project", return_value=projected), patch.object(core, "phase_for_game", return_value="EARLY"):
            r = engine.analyze({"gamePk": 1}, event, as_of=iso(at))
        rl = [o for o in r["options"] if o["market"] == "RUNLINE"]
        totals = [o for o in r["options"] if o["market"] == "TOTAL"]
        self.assertEqual(r["analysis_lines"]["RUNLINE"]["source"], "sharp")
        self.assertEqual(r["analysis_lines"]["TOTAL"]["source"], "sharp")
        self.assertEqual({o["point"] for o in rl}, {-1.5, 1.5})
        self.assertEqual({o["point"] for o in totals}, {8.5})
        self.assertTrue(all(o["winamax_eval"]["price"] is None for o in rl+totals))
        self.assertTrue(all(not o["execution_available"] for o in rl+totals))
        self.assertTrue(all(not selector.value_gate(o)["ok"] for o in rl+totals))
        self.assertIsNone(r["canonical_lines"]["RUNLINE"])
        self.assertIsNone(r["canonical_lines"]["TOTAL"])

    def test_production_evidence_gate_collects_before_claim(self):
        g = pro_model.production_evidence_gate({"settled_singles": 0, "settled_combos": 0, "close_candidate_clv_n": 0})
        self.assertFalse(g["passes"]); self.assertEqual(g["status"], "COLLECTING")

    def test_workflow_orders_v14_build_validate_publish(self):
        text = Path(".github/workflows/mlb-bot.yml").read_text(encoding="utf-8")
        self.assertLess(text.index("Acquire pregame state without Discord"), text.index("Build Pulsar V14 production payload"))
        self.assertLess(text.index("Build Pulsar V14 production payload"), text.index("Validate Pulsar V14 publication state"))
        self.assertLess(text.index("Validate Pulsar V14 publication state"), text.index("Publish Pulsar V14 Discord analytics"))
        self.assertTrue(Path(".github/workflows/market-snapshot.yml").exists())


if __name__ == "__main__": unittest.main()