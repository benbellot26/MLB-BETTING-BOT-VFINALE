from __future__ import annotations

import unittest
from pathlib import Path

from v11 import calibration_baseball_v13 as cal
from v11 import data_quality, selector, uncertainty_v13, v13_rich_run_shadow, v13_train
from v11.probability_contract_v13 import attach_contract


class V135ProfessionalAuditTests(unittest.TestCase):
    def _row(self, game_pk=1, phase="FINAL", contract=True):
        row = {
            "game_pk": game_pk,
            "phase": phase,
            "analyzed_at": "2026-08-17T17:00:00+00:00",
            "game_date": "2026-08-17T18:00:00+00:00",
            "home_score": 5,
            "away_score": 3,
            "home": "Home",
            "away": "Away",
            "features_from_postgame": False,
            "options": [
                {"market": "ML", "name": "Home", "point": None, "is_canonical_line": True,
                 "p_baseball_raw": .58, "result": "WIN"},
                {"market": "ML", "name": "Away", "point": None, "is_canonical_line": True,
                 "p_baseball_raw": .42, "result": "LOSS"},
            ],
        }
        if contract:
            attach_contract(row)
        return row

    def test_native_calibration_rejects_legacy_row_without_contract(self):
        legacy = self._row(contract=False)
        accepted = self._row(game_pk=2, contract=True)
        rows = v13_train.eligible_probability_rows([legacy, accepted])
        self.assertEqual([r["game_pk"] for r in rows], [2])

    def test_exact_replay_tier_cannot_bypass_current_contract(self):
        exact = self._row(contract=False)
        exact["v13_evidence_tier"] = "A_EXACT_REPLAY"
        rows = v13_train.eligible_probability_rows([exact])
        self.assertEqual(len(rows), 0)

    def test_global_calibrator_is_never_runtime_fallback(self):
        model = {"calibrators": {
            "GLOBAL": {"active": True, "method": "platt", "a": 1.0, "b": .5, "n": 1000},
            "MARKET:ML": {"active": False, "n": 80},
            "PHASE:FINAL:ML": {"active": False, "n": 12},
        }}
        p, source, n = cal.calibrate(.60, "ML", "FINAL", model)
        self.assertAlmostEqual(p, .60)
        self.assertEqual(source, "identity")
        self.assertEqual(n, 12)

    def test_selector_uses_displayed_interval_low_for_prudent_probability(self):
        rec = {"p_effective": .61, "probability_interval_low": .53, "model_uncertainty": .01}
        self.assertAlmostEqual(selector.conservative_probability(rec), .53)
        rec["winamax_eval"] = {"price": 2.0}
        self.assertEqual(selector.value_gate(rec)["conservative_source"], "v13_interval_low")

    def test_market_disagreement_does_not_widen_baseball_interval(self):
        a = uncertainty_v13.empirical_interval(.57, calibration_n=80, phase_n=80, market_n=100,
                                                data_quality=.9, empirical_sigma=.03, sharp_dispersion=.0)
        b = uncertainty_v13.empirical_interval(.57, calibration_n=80, phase_n=80, market_n=100,
                                                data_quality=.9, empirical_sigma=.03, sharp_dispersion=.20)
        self.assertAlmostEqual(a["sigma"], b["sigma"], places=12)
        self.assertFalse(b["market_disagreement_affects_baseball_interval"])
        self.assertGreater(b["market_disagreement_sigma"], a["market_disagreement_sigma"])

    def test_final_selection_blocks_old_sharp_quote(self):
        result = {
            "phase": "FINAL",
            "ctx": {"home_sp": "HSP", "away_sp": "ASP",
                    "home_lineup": {"count": 9, "players": [{"ops": .7}]*9},
                    "away_lineup": {"count": 9, "players": [{"ops": .7}]*9},
                    "home_starter": {"current_stats_available": True},
                    "away_starter": {"current_stats_available": True}},
            "features": {"weather": {"available": True}, "bullpen": {"coverage": 1},
                         "source_quality": {"home_team_hitting": True, "away_team_hitting": True,
                                            "home_team_pitching": True, "away_team_pitching": True,
                                            "home_lineup_usable_ops": 9, "away_lineup_usable_ops": 9}},
            "model": {"artifact_status": "ABSENT"},
        }
        rec = {"refs": 2, "sharp_max_age_min": 30, "winamax_eval": {"price": 1.9}}
        q = data_quality.assess(result, rec)
        self.assertIn("sharp_stale_for_final", q["blockers"])
        self.assertFalse(q["eligible"])

    def test_rich_shadow_uses_live_v13_hmu_amu(self):
        result = {
            "phase": "FINAL", "hmu": 4.8, "amu": 4.1,
            "ctx": {"home": "Home"},
            "shadow_v124": {"modules": {"starter_ip": {"coverage": 1.0, "home_factor": 1.01, "away_factor": .99}}},
            "options": [{"market": "ML", "name": "Home", "point": None},
                        {"market": "ML", "name": "Away", "point": None}],
        }
        artifact = {"schema": "v13-rich-run-residual-v2", "shadow_enabled": True,
                    "status": "HISTORICALLY_VALIDATED_SHADOW", "model": {
                        "selected_modules": ["starter_ip"], "coefficients": [1.0], "max_adjustment": .45}}
        v13_rich_run_shadow.attach(result, artifact)
        shadow = result["shadow_v13_rich_runs"]
        self.assertEqual(shadow["status"], "ACTIVE_SHADOW")
        self.assertEqual(shadow["base_mean_source"], "v13_hmu_amu")
        self.assertFalse(shadow["affects_v13_probability"])

    def test_phase_collector_runs_v13_not_v123(self):
        text = Path(".github/workflows/v12-3-research-collector.yml").read_text(encoding="utf-8")
        self.assertIn("python -m v11.v13_entry", text)
        self.assertNotIn("python -m v11.v123_entry", text)
        self.assertIn("predictive contract", text.lower())


def load_tests(loader, tests, pattern):
    """Production already runs this audit module; aggregate every hardening layer here."""
    from tests.test_v1351_audit_fixes import V1351AuditFixesTest
    from tests.test_v1352_final_hardening import V1352FinalHardeningTests
    suite=unittest.TestSuite()
    suite.addTests(tests)
    suite.addTests(loader.loadTestsFromTestCase(V1351AuditFixesTest))
    suite.addTests(loader.loadTestsFromTestCase(V1352FinalHardeningTests))
    return suite


if __name__ == "__main__":
    unittest.main()
