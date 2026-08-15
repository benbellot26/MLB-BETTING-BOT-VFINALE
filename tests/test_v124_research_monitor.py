from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import discord_v123
from v11 import v124_research_monitor as monitor


class V124ResearchMonitorTests(unittest.TestCase):
    def row(self, game_pk=1, analyzed_at="2026-08-15T10:00:00Z", base=.56, core=.61):
        official = [
            {"market": "ML", "name": "Home", "point": None, "result": "WIN"},
            {"market": "ML", "name": "Away", "point": None, "result": "LOSS"},
        ]
        variants = {
            "baseline_v1232": {"options": [
                {"market": "ML", "name": "Home", "point": None, "p_effective": base},
                {"market": "ML", "name": "Away", "point": None, "p_effective": 1-base},
            ]},
            "all_core": {"options": [
                {"market": "ML", "name": "Home", "point": None, "p_effective": core},
                {"market": "ML", "name": "Away", "point": None, "p_effective": 1-core},
            ]},
        }
        for name in monitor.MODULE_LABELS:
            variants[f"only_{name}"] = variants["baseline_v1232"]
        return {
            "run_id": "run-1", "game_pk": game_pk, "analyzed_at": analyzed_at,
            "game_date": "2026-08-16T00:00:00Z", "home": "Home", "away": "Away",
            "home_score": 5, "away_score": 3, "options": official,
            "shadow_v124": {"enabled": True, "variants": variants},
        }

    def report(self):
        variants = {
            "baseline_v1232": {"n": 2, "accuracy": .5, "brier": .24, "logloss": .67, "gt55_n": 1, "gt55_hit_rate": 1.0,
                                "by_market": {"ML": {"n": 2, "brier": .24, "logloss": .67}}},
            "all_core": {"n": 2, "accuracy": .5, "brier": .22, "logloss": .63, "gt55_n": 1, "gt55_hit_rate": 1.0,
                         "by_market": {"ML": {"n": 2, "brier": .22, "logloss": .63}}},
        }
        modules = {
            name: {"learned_weight": 0.0, "brier_improvement": .001, "logloss_improvement": .002,
                   "team_run_mae_improvement": .01, "paired_objective_improvement": .001,
                   "paired_objective_ci95": [-.001, .003], "verdict": "WATCH"}
            for name in monitor.MODULE_LABELS
        }
        return {
            "run_id": "run-1", "analyzed_at": "2026-08-15T12:00:00Z", "target_date": "2026-08-15",
            "production": {"engine": "V12.3.2"},
            "predictive_v124": {
                "settled_games": 1, "variants": variants,
                "weight_optimizer": {
                    "status": "COLLECTING", "stage": "COLLECT", "settled_games": 1,
                    "minimum_games": 75, "walk_forward_ready_games": 150, "mature_games": 250,
                    "weights": {name: 0.0 for name in monitor.MODULE_LABELS}, "modules": modules,
                    "walk_forward": {"status": "COLLECTING"}, "active_for_v124_shadow": False,
                    "promotion": {"automatic": False},
                },
            },
            "shadow_challenger": {
                "settled_games": 1,
                "overall": {"consensus_gt55": {"n": 1, "hit_rate_ex_push": 1.0},
                            "strong_disagreement": {"n": 0, "hit_rate_ex_push": None}},
                "activation": {"affects_v12_selection": False},
            },
        }

    def test_canonical_rows_count_duplicate_game_once_and_keep_latest(self):
        older = self.row(analyzed_at="2026-08-15T09:00:00Z", base=.52)
        latest = self.row(analyzed_at="2026-08-15T11:00:00Z", base=.58)
        rows = monitor.canonical_rows([latest, older])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["analyzed_at"], latest["analyzed_at"])

    def test_market_metrics_are_split_by_market(self):
        metrics = monitor._variant_market_metrics([self.row()])
        self.assertIn("ML", metrics["baseline_v1232"])
        self.assertEqual(metrics["baseline_v1232"]["ML"]["n"], 2)
        self.assertGreater(metrics["all_core"]["ML"]["gt55_n"], 0)

    def test_build_reports_progress_ablations_and_disagreements(self):
        built = monitor.build(self.report(), None, [self.row(base=.54, core=.61)])
        self.assertEqual(built["progress"]["settled_games"], 1)
        self.assertEqual(built["progress"]["remaining_to_minimum"], 74)
        self.assertFalse(built["affects_v12_selection"])
        self.assertEqual(len(built["ablations"]), 6)
        self.assertTrue(built["current_run_disagreements"])
        self.assertTrue(built["current_run_disagreements"][0]["crosses_55"])

    def test_discord_monitor_uses_one_non_recommendation_embed(self):
        built = monitor.build(self.report(), None, [self.row(base=.54, core=.61)])
        with patch.object(discord_v123.core, "send_embed", return_value=True) as send:
            self.assertTrue(discord_v123.send_research_monitor(built))
        self.assertEqual(send.call_count, 1)
        title = send.call_args.args[0]
        description = send.call_args.kwargs.get("description")
        self.assertIn("RESEARCH MONITOR", title)
        self.assertIn("n'est pas une recommandation", description)

    def test_monitor_failure_does_not_block_official_summary(self):
        from v11 import v123_entry
        report = {"ledger_settled_this_run": 0, "research_monitor_v124": self.report()}
        with patch.object(v123_entry.discord_v123, "send_research_monitor", return_value=False):
            self.assertTrue(v123_entry._summary_v123(report))

    def test_deferred_payload_is_refreshed_with_enriched_report(self):
        from v11 import v123_entry
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"discord_payload.json"
            path.write_text(json.dumps({"results": [], "report": {"run_id": "old"}}), encoding="utf-8")
            enriched = {"run_id": "new", "research_monitor_v124": {"research_only": True}}
            with patch.object(v123_entry.runner, "DISCORD_PAYLOAD", path):
                self.assertTrue(v123_entry._refresh_deferred_payload(enriched))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["report"]["run_id"], "new")
            self.assertTrue(payload["report"]["research_monitor_v124"]["research_only"])

    def test_empty_results_can_still_publish_nonblocking_summary(self):
        from v11 import v123_entry
        report = {"ledger_settled_this_run": 0, "research_monitor_v124": self.report()}
        with patch.object(v123_entry.core, "discord_test", return_value=True), \
             patch.object(v123_entry, "_summary_v123", return_value=True) as summary:
            self.assertTrue(v123_entry._send_v123([], {}, [], {}, {}, report))
        summary.assert_called_once_with(report)


if __name__ == "__main__":
    unittest.main()
