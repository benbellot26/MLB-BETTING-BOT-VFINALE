from __future__ import annotations

import json
from pathlib import Path
import unittest

from v14.benchmark import CHAMPION_GENERATION
from v14 import run_stack


class V14RunStackParityTests(unittest.TestCase):
    def _snapshot(self):
        return {
            "game_pk": 1,
            "game_date": "2026-08-20T23:00:00Z",
            "game": {"gamePk": 1, "gameDate": "2026-08-20T23:00:00Z", "venue": {"name": "Unknown Test Park"}},
            "model_generation": CHAMPION_GENERATION,
            "features": {
                "structural_home_mu": 4.8,
                "structural_away_mu": 4.1,
                "home_mu": 4.8,
                "away_mu": 4.1,
                "park_factor_runtime": {"static_factor": 1.0, "venue": "Unknown Test Park", "active": False},
                "historical_bootstrap": {"run_prior": {"active": False}},
                "learned_run_adjustment": {"active": False, "home_delta": 0.0, "away_delta": 0.0},
            },
        }

    def test_static_fallback_preserves_structural_means(self):
        result = run_stack.reproduce_from_champion_result(self._snapshot())
        self.assertAlmostEqual(result["home_mu"], 4.8, places=15)
        self.assertAlmostEqual(result["away_mu"], 4.1, places=15)
        self.assertIn("STATIC_PARK_FALLBACK", result["active_layers"])

    def test_newly_active_unported_layer_fails_closed(self):
        row = self._snapshot()
        row["features"]["learned_run_adjustment"] = {"active": True, "home_delta": .1, "away_delta": -.1}
        with self.assertRaisesRegex(ValueError, "V13_CHAMPION_RESIDUAL_ACTIVE"):
            run_stack.reproduce_from_champion_result(row)

    def test_real_champion_snapshots_reproduce_exact_run_means(self):
        path = Path("data/v11_3_live.jsonl")
        if not path.exists():
            self.skipTest("persisted champion journal not available")
        checked = 0
        worst = 0.0
        detail = None
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("model_generation") != CHAMPION_GENERATION:
                continue
            if str(row.get("phase") or "").upper() != "FINAL":
                continue
            features = row.get("features") or {}
            target_home = features.get("home_mu")
            target_away = features.get("away_mu")
            if target_home is None or target_away is None:
                continue
            try:
                candidate = run_stack.reproduce_from_champion_result(row)
            except ValueError:
                continue
            gap = max(abs(float(candidate["home_mu"]) - float(target_home)),
                      abs(float(candidate["away_mu"]) - float(target_away)))
            if gap > worst:
                worst = gap
                detail = {
                    "game_pk": row.get("game_pk"),
                    "gap": gap,
                    "candidate_home": candidate["home_mu"],
                    "target_home": target_home,
                    "candidate_away": candidate["away_mu"],
                    "target_away": target_away,
                    "park": candidate["park"],
                    "persisted_park": features.get("park_factor_runtime"),
                }
            checked += 1
            if checked >= 30:
                break
        self.assertGreater(checked, 0, "no current-generation FINAL snapshot eligible for run-stack parity")
        self.assertLessEqual(worst, 1e-10, f"worst run-stack parity detail: {detail}")


if __name__ == "__main__":
    unittest.main()
