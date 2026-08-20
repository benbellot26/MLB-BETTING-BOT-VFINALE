from __future__ import annotations

import unittest

from v11 import v13_champion_dashboard as dash
from v11.probability_contract_v13 import MODEL_GENERATION_FINGERPRINT, attach_contract


def _row(game_pk: str, *, day: str, home: str, away: str, hp: float, ap: float, hs: int, ass: int, p: float, result: str, dq: float = .9):
    away_result = "LOSS" if result == "WIN" else "WIN" if result == "LOSS" else "PUSH"
    row = {
        "game_pk": game_pk,
        "target_date": day,
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
            {"market": "ML", "name": home, "point": None, "is_canonical_line": True, "p_predictive_final": p, "p_baseball_calibrated": p, "p_effective": p, "result": result},
            {"market": "ML", "name": away, "point": None, "is_canonical_line": True, "p_predictive_final": 1-p, "p_baseball_calibrated": 1-p, "p_effective": 1-p, "result": away_result},
        ],
    }
    attach_contract(row)
    return row


class V1310ChampionDashboardTests(unittest.TestCase):
    def test_current_generation_only_and_run_metrics(self):
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
        self.assertEqual(report["cumulative"]["probability"]["by_market"]["ML"]["n"], 2)

    def test_markdown_is_diagnostic_only(self):
        report = dash.build([_row("1", day="2026-08-18", home="A", away="B", hp=5, ap=4, hs=5, ass=4, p=.55, result="WIN")])
        text = dash.render_markdown(report)
        self.assertIn("V13.10 Champion Diagnostic Dashboard", text)
        self.assertIn("Diagnostic only", text)
        self.assertFalse(report["safety"]["changes_predictions"])


if __name__ == "__main__":
    unittest.main()
