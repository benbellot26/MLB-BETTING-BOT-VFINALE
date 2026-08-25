import unittest

from v14.phase import infer_phase


class V14PhaseTests(unittest.TestCase):
    def test_early_run_is_not_final(self):
        phase = infer_phase(
            analyzed_at="2026-08-25T13:00:00Z",
            game_date="2026-08-25T23:00:00Z",
            context={"home_lineup": {"count": 0}, "away_lineup": {"count": 0}},
        )
        self.assertEqual(phase, "EARLY")

    def test_late_when_close_to_first_pitch_without_complete_lineups(self):
        phase = infer_phase(
            analyzed_at="2026-08-25T20:00:00Z",
            game_date="2026-08-25T23:00:00Z",
            context={"home_lineup": {"count": 0}, "away_lineup": {"count": 0}},
        )
        self.assertEqual(phase, "LATE")

    def test_final_requires_both_complete_lineups_and_close_game(self):
        context = {"home_lineup": {"count": 9}, "away_lineup": {"count": 9}}
        phase = infer_phase(
            analyzed_at="2026-08-25T21:30:00Z",
            game_date="2026-08-25T23:00:00Z",
            context=context,
        )
        self.assertEqual(phase, "FINAL")

    def test_complete_lineups_far_from_game_do_not_force_final(self):
        context = {"home_lineup": {"count": 9}, "away_lineup": {"count": 9}}
        phase = infer_phase(
            analyzed_at="2026-08-25T15:00:00Z",
            game_date="2026-08-25T23:00:00Z",
            context=context,
        )
        self.assertEqual(phase, "LATE")


if __name__ == "__main__":
    unittest.main()
