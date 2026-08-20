from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from v11 import probability_contract_v13 as contract
from v11 import v13_daily_tracking as tracking
from v11 import v13_posterior_policy as posterior
from v11 import v13_probability_diagnostics as diagnostics
from v11 import v13_train


def _provenance(as_of="2026-08-19T18:00:00Z", attested=True):
    return {
        "team_stats": {
            "source": "durable-test",
            "as_of": as_of,
            "observed_at": as_of,
            "timestamp_basis": "durable_snapshot_capture",
            "source_timestamp_attested": attested,
            "point_in_time": True,
            "snapshot": True,
            "cutoff_capable": False,
            "season_aggregate": False,
            "postgame_identity": False,
        }
    }


def _calibration_row(attested=True):
    row = {
        "game_pk": 1,
        "game_date": "2026-08-19T19:00:00Z",
        "analyzed_at": "2026-08-19T18:00:00Z",
        "phase": "FINAL",
        "home": "Home",
        "away": "Away",
        "home_score": 5,
        "away_score": 3,
        "features_from_postgame": False,
        "feature_provenance": _provenance(attested=attested),
        "options": [
            {"market": "ML", "name": "Home", "result": "WIN", "p_baseball_raw": .58, "is_canonical_line": True},
            {"market": "RUNLINE", "name": "Home", "point": -1.5, "result": "WIN", "p_baseball_raw": .41, "is_canonical_line": True},
            {"market": "TOTAL", "name": "Over", "point": 8.5, "result": "LOSS", "p_baseball_raw": .54, "is_canonical_line": True},
        ],
    }
    contract.attach_contract(row)
    return row


def _tracking_state(game, market="ML", *, current=True, p_market=.50):
    state = {
        "game_pk": game,
        "game_date": f"2026-08-{(game % 20) + 1:02d}T19:00:00Z",
        "phase": "FINAL",
        "observation_at": f"2026-08-{(game % 20) + 1:02d}T18:00:00Z",
        "home": "Home",
        "away": "Away",
        "market": market,
        "pick": "Home" if market != "TOTAL" else "Over",
        "point": -1.5 if market == "RUNLINE" else 8.5 if market == "TOTAL" else None,
        "canonical": True,
        "settled_result": "WIN" if game % 2 else "LOSS",
        "p_model": .57 if game % 2 else .43,
        "p_baseball_calibrated": .57 if game % 2 else .43,
        "p_market": p_market,
        "predictive_final_status": "BASEBALL_ONLY_CHAMPION",
    }
    if current:
        state["model_generation"] = contract.MODEL_GENERATION_FINGERPRINT
        state["predictive_contract"] = asdict(contract.CONTRACT)
    else:
        state["model_generation"] = "legacy-generation"
        state["predictive_contract"] = {}
    return state


class V1310MaxAuditHardeningTests(unittest.TestCase):
    def test_tracking_persists_generation_and_predictive_contract(self):
        with tempfile.TemporaryDirectory() as td:
            old_track, old_report = tracking.TRACK_FILE, tracking.REPORT_FILE
            try:
                tracking.TRACK_FILE = Path(td) / "tracking.jsonl"
                tracking.REPORT_FILE = Path(td) / "report.json"
                result = {
                    "game_pk": 7,
                    "game": {"gameDate": "2026-08-19T19:00:00Z"},
                    "as_of": "2026-08-19T18:00:00Z",
                    "phase": "FINAL",
                    "model_generation": contract.MODEL_GENERATION_FINGERPRINT,
                    "predictive_contract": asdict(contract.CONTRACT),
                    "ctx": {"home": "Home", "away": "Away"},
                    "options": [{"market":"ML","name":"Home","p_baseball_raw":.56,"p_baseball_calibrated":.57,
                                 "p_market":.52,"is_canonical_line":True,"probability_product":"calibrated-baseball-only",
                                 "winamax_eval":{"official_selected":False}}],
                }
                self.assertEqual(tracking.capture_results([result]), 1)
                state = next(iter(tracking.fold().values()))
                self.assertEqual(state["model_generation"], contract.MODEL_GENERATION_FINGERPRINT)
                self.assertTrue(contract.CONTRACT.compatible_with(state["predictive_contract"]))
                self.assertEqual(state["probability_product"], "calibrated-baseball-only")
            finally:
                tracking.TRACK_FILE, tracking.REPORT_FILE = old_track, old_report

    def test_diagnostics_top_level_is_current_generation_only(self):
        current = _tracking_state(1)
        legacy = _tracking_state(2, current=False)
        report = diagnostics.build([current, legacy])
        self.assertEqual(report["scope"], "current-generation-only")
        self.assertEqual(report["independent_targets"], 1)
        self.assertEqual(report["by_market"]["ML"]["n"], 1)
        self.assertEqual(report["all_generations_historical"]["independent_targets"], 2)

    def test_diagnostics_exposes_missing_runline_and_total_market_probability(self):
        rl = _tracking_state(3, "RUNLINE", p_market=None)
        total = _tracking_state(5, "TOTAL", p_market=None)
        report = diagnostics.build([rl, total])
        self.assertEqual(report["by_market"]["RUNLINE"]["n"], 0)
        self.assertEqual(report["by_market"]["TOTAL"]["n"], 0)
        self.assertEqual(report["tracking_availability"]["by_market"]["RUNLINE"]["missing_market_probability"], 1)
        self.assertEqual(report["tracking_availability"]["by_market"]["TOTAL"]["missing_market_probability"], 1)

    def test_posterior_live_evidence_rejects_legacy_generation(self):
        states = {"current": _tracking_state(1), "legacy": _tracking_state(2, current=False)}
        with patch("v11.v13_daily_tracking.fold", return_value=states):
            rows = posterior._live_observations()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_pk"], 1)
        self.assertEqual(rows[0]["evidence_origin"], "native-live-current-generation-attested")

    def test_native_calibration_requires_promotion_grade_pit(self):
        good = _calibration_row(attested=True)
        weak = _calibration_row(attested=False)
        weak["game_pk"] = 2
        self.assertEqual(len(v13_train.eligible_probability_rows([good])), 1)
        self.assertEqual(v13_train.eligible_probability_rows([weak]), [])


if __name__ == "__main__":
    unittest.main()
