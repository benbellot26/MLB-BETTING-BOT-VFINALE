from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v11 import historical_bootstrap as hb


def _rows(n=180, home_bias=.35, away_bias=-.20):
    rows = []
    for i in range(n):
        hmu = 3.5 + (i % 9) * .22
        amu = 3.7 + ((i * 3) % 8) * .19
        # Deterministic pseudo-noise with zero-ish mean. The systematic bias is learnable,
        # while the future blocks still differ enough to exercise the chronological gates.
        hn = ((i * 7) % 11 - 5) * .12
        an = ((i * 5) % 13 - 6) * .11
        hs = max(0, int(round(hmu + home_bias + hn)))
        aws = max(0, int(round(amu + away_bias + an)))
        rows.append({
            "game_pk": 900000 + i,
            "game_date": f"2026-05-{1 + i // 20:02d}T{(i % 20):02d}:00:00Z",
            "home_score": hs,
            "away_score": aws,
            "v10": {"home_struct": hmu, "away_struct": amu},
        })
    return rows


class HistoricalBootstrapTests(unittest.TestCase):
    def test_chronological_split_is_disjoint(self):
        rows = _rows(180)
        train, validation, test = hb.chronological_split(rows)
        self.assertEqual((len(train), len(validation), len(test)), (120, 30, 30))
        ids = [set(str(r["game_pk"]) for r in x) for x in (train, validation, test)]
        self.assertTrue(ids[0].isdisjoint(ids[1]))
        self.assertTrue(ids[0].isdisjoint(ids[2]))
        self.assertTrue(ids[1].isdisjoint(ids[2]))
        self.assertLess(train[-1]["game_date"], validation[0]["game_date"])
        self.assertLess(validation[-1]["game_date"], test[0]["game_date"])

    def test_run_prior_applies_only_to_final_and_active_model(self):
        fit = hb.fit_run_correction(_rows(180))
        model = {"schema": hb.SCHEMA, "active": True, "run_correction": {**fit, "active": True}}
        h, a, info = hb.apply_final_run_prior(4.2, 4.1, model, "FINAL")
        self.assertTrue(info["active"])
        self.assertNotEqual((h, a), (4.2, 4.1))
        h2, a2, info2 = hb.apply_final_run_prior(4.2, 4.1, model, "EARLY")
        self.assertFalse(info2["active"])
        self.assertEqual((h2, a2), (4.2, 4.1))

    def test_model_keeps_frozen_test_and_evidence_boundary(self):
        model = hb.build_model(_rows(180), min_games=120, fingerprint="unit-test")
        self.assertEqual(model["metadata"]["split"], {"train": 120, "validation": 30, "test": 30})
        self.assertTrue(model["metadata"]["test_is_frozen"])
        self.assertFalse(model["metadata"]["historical_odds_used"])
        self.assertFalse(model["metadata"]["betting_profitability_claim"])
        self.assertEqual(model["phase_scope"], ["FINAL"])
        self.assertIn("Historical baseball bootstrap only", model["evidence_boundary"])

    def test_load_rows_deduplicates_games(self):
        rows = _rows(3)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.jsonl"
            import json
            p.write_text("\n".join(json.dumps(r) for r in (rows + [rows[1]])) + "\n", encoding="utf-8")
            got = hb.load_rows(p)
        self.assertEqual(len(got), 3)
        self.assertEqual(len({r["game_pk"] for r in got}), 3)


if __name__ == "__main__":
    unittest.main()
