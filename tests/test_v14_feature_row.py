import json
from pathlib import Path
import tempfile
import unittest

from v14.feature_row import feature_row_is_usable, load_latest_feature_row


class FeatureRowTests(unittest.TestCase):
    def _row(self, as_of, eligible=True):
        return {"schema": "v13-pit-feature-store-v1", "game_pk": "123", "as_of": as_of, "point_in_time": True, "point_in_time_validation_reasons": [], "data_quality": {"eligible": eligible}}

    def test_latest_row_never_crosses_prediction_cutoff(self):
        rows = [self._row("2026-08-24T10:00:00+00:00"), self._row("2026-08-24T11:00:00+00:00"), self._row("2026-08-24T12:00:00+00:00")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "features.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            selected = load_latest_feature_row(path, game_pk="123", as_of="2026-08-24T11:30:00+00:00")
        self.assertEqual(selected["as_of"], "2026-08-24T11:00:00+00:00")

    def test_invalid_pit_row_is_skipped(self):
        row = self._row("2026-08-24T10:00:00+00:00", eligible=False)
        self.assertFalse(feature_row_is_usable(row, game_pk="123", as_of="2026-08-24T11:00:00+00:00"))


if __name__ == "__main__":
    unittest.main()
