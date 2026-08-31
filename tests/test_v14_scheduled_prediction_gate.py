from datetime import datetime, timedelta, timezone
import unittest

from v14.scheduled_prediction_gate import due_games


class V14ScheduledPredictionGateTests(unittest.TestCase):
    def _game(self, detailed_state: str, *, abstract_state: str = "Preview") -> dict:
        now = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)
        return {
            "gamePk": 123,
            "gameDate": (now + timedelta(minutes=30)).isoformat(),
            "status": {
                "abstractGameState": abstract_state,
                "detailedState": detailed_state,
            },
            "teams": {
                "home": {"team": {"name": "Home"}},
                "away": {"team": {"name": "Away"}},
            },
        }

    def test_normal_preview_inside_final_window_is_due(self) -> None:
        now = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)
        out = due_games([self._game("Scheduled")], [], now=now)
        self.assertEqual([row["game_pk"] for row in out], ["123"])

    def test_postponed_cancelled_suspended_or_delayed_games_never_spend_prediction_budget(self) -> None:
        now = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)
        for state in ("Postponed", "Cancelled", "Canceled", "Suspended", "Delayed Start"):
            with self.subTest(state=state):
                self.assertEqual(due_games([self._game(state)], [], now=now), [])

    def test_live_and_final_games_are_not_due_even_if_clock_is_inside_window(self) -> None:
        now = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)
        self.assertEqual(due_games([self._game("In Progress", abstract_state="Live")], [], now=now), [])
        self.assertEqual(due_games([self._game("Final", abstract_state="Final")], [], now=now), [])


if __name__ == "__main__":
    unittest.main()
