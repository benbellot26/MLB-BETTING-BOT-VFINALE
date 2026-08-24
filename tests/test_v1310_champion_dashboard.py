from __future__ import annotations

import unittest

from v11 import v13_champion_dashboard as dash
from v11.probability_contract_v13 import MODEL_GENERATION_FINGERPRINT, attach_contract


def _opposite(result: str) -> str:
    return "LOSS" if result == "WIN" else "WIN" if result == "LOSS" else "PUSH"


def _row(game_pk: str, *, day: str, home: str, away: str, hp: float, ap: float, hs: int, ass: int, p: float, result: str, dq: float = .9):
    away_result = _opposite(result)
    home_rl_result = "WIN" if hs - ass - 1.5 > 0 else "LOSS" if hs - ass - 1.5 < 0 else "PUSH"
    away_rl_result = _opposite(home_rl_result)
    total_delta = hs + ass - 8.5
    over_result = "WIN" if total_delta > 0 else "LOSS" if total_delta < 0 else "PUSH"
    under_result = _opposite(over_result)
    row = {
        "game_pk": game_pk,
        "target_date": day,
        "game_date": f"{day}T23:00:00+00:00",
        "analyzed_at": f"{day}T18:00:00+00:00",
        "phase": "FINAL",
        "result_status": "FINAL",
        "home": home,
        "away": away,
        "home_score": hs,
        "away_score": ass,
        "projected_home_runs": hp,
        "projected_away_runs": ap,
        "model_generation": MODEL_GENERATION_FINGERPRINT,
        "data_quality": {"model_input_score": dq, "components": {"starter_identity": 1.0, "lineup_stats": dq}, "blockers": []},
        "features": {"park_factor_runtime": {"venue": "Test Park"}},
        "canonical_lines": {"RUNLINE": -1.5, "TOTAL": 8.5},
        "options": [
            {"market": "ML", "name": home, "point": None, "is_canonical_line": True, "p_predictive_final": p, "p_baseball_calibrated": p, "p_posterior": min(.99, p+.01), "p_effective": p, "result": result},
            {"market": "ML", "name": away, "point": None, "is_canonical_line": True, "p_predictive_final": 1-p, "p_baseball_calibrated": 1-p, "p_posterior": max(.01, 1-p-.01), "p_effective": 1-p, "result": away_result},
            {"market": "RUNLINE", "name": home, "point": -1.5, "is_canonical_line": True, "p_predictive_final": .56, "p_baseball_calibrated": .56, "p_posterior": .55, "p_effective": .56, "result": home_rl_result},
            {"market": "RUNLINE", "name": away, "point": +1.5, "is_canonical_line": True, "p_predictive_final": .44, "p_baseball_calibrated": .44, "p_posterior": .45, "p_effective": .44, "result": away_rl_result},
            {"market": "TOTAL", "name": "Over", "point": 8.5, "is_canonical_line": True, "p_predictive_final": .57, "p_baseball_calibrated": .57, "p_posterior": .56, "p_effective": .57, "result": over_result},
            {"market": "TOTAL", "name": "Under", "point": 8.5, "is_canonical_line": True, "p_predictive_final": .43, "p_baseball_calibrated": .43, "p_posterior": .44, "p_effective": .43, "result": under_result},
        ],
    }
    attach_contract(row)
    return row


class V1310ChampionDashboardTests(unittest.TestCase):
    def test_current_generation_only_and_all_market_metrics(self):
        good1 = _row("1", day="2026-08-18", home="A", away="B", hp=5.0, ap=4.0, hs=6, ass=3, p=.65, result="WIN")
        good2 = _row("2", day="2026-08-19", home="C", away="D", hp=4.0, ap=4.5, hs=2, ass=5, p=.60, result="LOSS", dq=.7)
        legacy = dict(_row("3", day="2026-08-19", home="E", away="F", hp=4, ap=4, hs=10, ass=0, p=.9, result="WIN"))
        legacy["model_generation"] = "legacy"
        legacy["model_generation_fingerprint"] = "legacy"

        report = dash.build([good1, good2, legacy])
        self.assertEqual(report["cumulative"]["games"], 2)
        self.assertEqual(report["latest_day"]["games"], 1)
        self.assertEqual(report["latest_date"], "2026-08-19")
        self.assertAlmostEqual(report["cumulative"]["runs"]["home_mae_runs"], 1.5)
        self.assertAlmostEqual(report["cumulative"]["runs"]["away_mae_runs"], .75)
        by_market = report["cumulative"]["probability"]["by_market"]
        self.assertEqual(by_market["ML"]["n"], 2)
        self.assertEqual(by_market["RUNLINE"]["n"], 2)
        self.assertEqual(by_market["TOTAL"]["n"], 2)
        self.assertEqual(report["market_diagnostics"]["checkpoint_100"]["unique_games"], 2)

    def test_runline_total_diagnostics_and_dq_are_populated(self):
        rows = [
            _row("1", day="2026-08-18", home="A", away="B", hp=5.0, ap=4.0, hs=6, ass=3, p=.65, result="WIN", dq=.95),
            _row("2", day="2026-08-19", home="C", away="D", hp=4.0, ap=4.5, hs=2, ass=5, p=.60, result="LOSS", dq=.70),
        ]
        report = dash.build(rows)
        diag = report["market_diagnostics"]
        self.assertEqual(diag["runline"]["projected_margin"]["n"], 2)
        self.assertEqual(diag["total"]["projection"]["n"], 2)
        self.assertIn(">=0.90", diag["by_data_quality"]["ML"])
        self.assertIn("0.60-0.75", diag["by_data_quality"]["TOTAL"])
        self.assertFalse(diag["changes_predictions"])

    def test_team_and_venue_biases_are_shrunk(self):
        rows = [
            _row(str(i), day="2026-08-18", home="A", away=f"B{i}", hp=4.0, ap=4.0, hs=6, ass=3, p=.6, result="WIN")
            for i in range(1, 4)
        ]
        report = dash.build(rows)
        team = report["by_team"]["A"]
        self.assertLess(abs(team["shrunk_run_bias"]), abs(team["run_bias"]))
        self.assertLess(team["reliability"], 1.0)
        venue = report["by_venue"]["Test Park"]
        self.assertIn("shrinkage", venue)
        self.assertLess(venue["shrinkage"]["reliability"], 1.0)

    def test_markdown_is_diagnostic_only_and_complete(self):
        report = dash.build([_row("1", day="2026-08-18", home="A", away="B", hp=5, ap=4, hs=5, ass=4, p=.55, result="WIN")])
        text = dash.render_markdown(report)
        self.assertIn("V13.10 Champion Diagnostic Dashboard", text)
        self.assertIn("Run Line diagnostic", text)
        self.assertIn("Total / Over-Under diagnostic", text)
        self.assertIn("100-game checkpoint", text)
        self.assertIn("Diagnostic only", text)
        self.assertFalse(report["safety"]["changes_predictions"])


if __name__ == "__main__":
    unittest.main()
