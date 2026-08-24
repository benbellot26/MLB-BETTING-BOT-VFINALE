import unittest
from unittest.mock import patch

from v11 import v13_champion_dashboard as dashboard
from v11 import v13_daily_tracking as tracking
from v11 import v13_probability_diagnostics as diagnostics
from v11.probability_contract_v13 import MODEL_GENERATION_FINGERPRINT, attach_contract


class V1310PrefreezeHardeningTests(unittest.TestCase):
    def _state(self, market, pick, point, p_model, p_market, *, phase="FINAL", at="2026-08-23T18:00:00Z", canonical=False, result="WIN", game_pk=1, target_date="2026-08-23"):
        row = {
            "game_pk": game_pk,
            "game_date": f"{target_date}T20:00:00Z",
            "target_date": target_date,
            "market": market,
            "pick": pick,
            "point": point,
            "home": "Home",
            "away": "Away",
            "p_model": p_model,
            "p_market": p_market,
            "settled_result": result,
            "model_generation": MODEL_GENERATION_FINGERPRINT,
            "phase": phase,
            "observation_phase": phase,
            "observation_at": at,
            "canonical": canonical,
        }
        attach_contract(row)
        return row

    def test_unmarked_unambiguous_runline_and_total_are_scoreable(self):
        states = [
            self._state("RUNLINE", "Home", 1.5, .61, .58),
            self._state("RUNLINE", "Away", -1.5, .39, .42, result="LOSS"),
            self._state("TOTAL", "Over", 8.5, .54, .51, game_pk=2),
            self._state("TOTAL", "Under", 8.5, .46, .49, game_pk=2, result="LOSS"),
        ]
        report = diagnostics.build(states)
        self.assertEqual(report["by_market"]["RUNLINE"]["n"], 1)
        self.assertEqual(report["by_market"]["TOTAL"]["n"], 1)
        audit = report["selection_audit"]["by_market"]
        self.assertEqual(audit["RUNLINE"]["selected_via_unambiguous_real_market_fallback"], 1)
        self.assertEqual(audit["TOTAL"]["selected_via_unambiguous_real_market_fallback"], 1)

    def test_ambiguous_unmarked_total_lines_fail_closed(self):
        states = [
            self._state("TOTAL", "Over", 8.5, .54, .51, game_pk=3),
            self._state("TOTAL", "Under", 8.5, .46, .49, game_pk=3, result="LOSS"),
            self._state("TOTAL", "Over", 9.5, .47, .44, game_pk=3),
            self._state("TOTAL", "Under", 9.5, .53, .56, game_pk=3, result="LOSS"),
        ]
        report = diagnostics.build(states)
        self.assertEqual(report["by_market"]["TOTAL"]["n"], 0)
        self.assertEqual(report["selection_audit"]["reasons"]["AMBIGUOUS_REAL_LINES"], 1)

    def test_latest_scoreable_phase_is_used_without_double_counting(self):
        early = self._state("ML", "Home", None, .58, .55, phase="EARLY", at="2026-08-23T10:00:00Z")
        late = self._state("ML", "Home", None, .63, .57, phase="LATE", at="2026-08-23T17:00:00Z")
        rows = diagnostics.independent_states([early, late], current_generation_only=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phase"], "LATE")
        self.assertEqual(rows[0]["p_model"], .63)

    def test_repository_tracking_now_has_real_rl_and_total_comparison_targets(self):
        report = diagnostics.build()
        self.assertGreater(report["by_market"]["RUNLINE"]["n"], 0)
        self.assertGreater(report["by_market"]["TOTAL"]["n"], 0)
        self.assertGreater(report["tracking_availability"]["by_market"]["RUNLINE"]["current_generation_independent_scoreable"], 0)
        self.assertGreater(report["tracking_availability"]["by_market"]["TOTAL"]["current_generation_independent_scoreable"], 0)

    def test_dashboard_exposes_market_and_run_projection_dates_separately(self):
        game = {
            "game_pk": 10,
            "target_date": "2026-08-22",
            "game_date": "2026-08-22T20:00:00Z",
            "analyzed_at": "2026-08-22T18:00:00Z",
            "result_status": "FINAL",
            "phase": "FINAL",
            "home": "Home",
            "away": "Away",
            "home_score": 5,
            "away_score": 3,
            "projected_home_runs": 4.4,
            "projected_away_runs": 3.8,
            "options": [],
            "model_generation": MODEL_GENERATION_FINGERPRINT,
        }
        attach_contract(game)
        newer_market = self._state("ML", "Home", None, .60, .56, game_pk=11, target_date="2026-08-23")
        with patch("v11.v13_champion_dashboard.journal.load_rows", return_value=[game]), \
             patch("v11.v13_champion_dashboard.tracking.fold", return_value={"k": newer_market}):
            report = dashboard.build()
        self.assertEqual(report["latest_date"], "2026-08-23")
        self.assertEqual(report["latest_run_projection_date"], "2026-08-22")
        self.assertEqual(report["latest_market_tracking_date"], "2026-08-23")
        self.assertEqual(report["sample_counts"]["latest_tracked_unique_games"], 1)
        rendered = dashboard.render_markdown(report)
        self.assertIn("Run-projection games", rendered)
        self.assertIn("Market-tracking sample settled through", rendered)

    def test_winamax_parser_supports_real_runline_and_total_without_imputation(self):
        event = {
            "bookmakers": [{
                "key": tracking.core.WINAMAX_KEY,
                "markets": [
                    {"key": "spreads", "outcomes": [
                        {"name": "Home", "point": -1.5, "price": 2.05},
                        {"name": "Away", "point": 1.5, "price": 1.75},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "point": 8.5, "price": 1.91},
                        {"name": "Under", "point": 8.5, "price": 1.89},
                    ]},
                ],
            }]
        }
        self.assertEqual(tracking._winamax_price_from_event(event, {"market": "RUNLINE", "pick": "Home", "point": -1.5}), 2.05)
        self.assertEqual(tracking._winamax_price_from_event(event, {"market": "TOTAL", "pick": "Over", "point": 8.5}), 1.91)
        self.assertIsNone(tracking._winamax_price_from_event(event, {"market": "TOTAL", "pick": "Over", "point": 9.5}))


if __name__ == "__main__":
    unittest.main()
