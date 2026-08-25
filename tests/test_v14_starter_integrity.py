from __future__ import annotations

import unittest

from v14.starter_integrity import validate_starters_for_phase


def _game(home_id=10, home_name="Home SP", away_id=20, away_name="Away SP"):
    return {
        "gamePk": 123,
        "teams": {
            "home": {"probablePitcher": {"id": home_id, "fullName": home_name}},
            "away": {"probablePitcher": {"id": away_id, "fullName": away_name}},
        },
    }


def _getter(*, feed_home=10, feed_away=20, box_home=10, box_away=20):
    def get(url, params):
        if url.endswith("/feed/live"):
            return {
                "gameData": {
                    "probablePitchers": {
                        "home": {"id": feed_home, "fullName": f"P{feed_home}"},
                        "away": {"id": feed_away, "fullName": f"P{feed_away}"},
                    }
                }
            }
        if url.endswith("/boxscore"):
            return {
                "teams": {
                    "home": {"pitchers": [box_home], "players": {f"ID{box_home}": {"person": {"fullName": f"P{box_home}"}}}},
                    "away": {"pitchers": [box_away], "players": {f"ID{box_away}": {"person": {"fullName": f"P{box_away}"}}}},
                }
            }
        raise AssertionError(url)
    return get


class StarterIntegrityTests(unittest.TestCase):
    def test_final_accepts_three_way_consensus(self):
        evidence = validate_starters_for_phase(_game(), "FINAL", getter=_getter())
        self.assertTrue(evidence["eligible"])
        self.assertTrue(evidence["home"]["consensus"])
        self.assertTrue(evidence["away"]["consensus"])

    def test_final_rejects_schedule_vs_boxscore_conflict(self):
        with self.assertRaisesRegex(ValueError, "STARTER_CONFLICT"):
            validate_starters_for_phase(_game(away_id=20, away_name="Stale SP"), "FINAL", getter=_getter(box_away=99))

    def test_late_rejects_schedule_vs_feed_conflict(self):
        with self.assertRaisesRegex(ValueError, "STARTER_CONFLICT"):
            validate_starters_for_phase(_game(), "LATE", getter=_getter(feed_home=77))

    def test_late_rejects_missing_second_confirmation(self):
        def get(url, params):
            if url.endswith("/feed/live"):
                return {"gameData": {"probablePitchers": {}}}
            if url.endswith("/boxscore"):
                return {"teams": {"home": {}, "away": {}}}
            raise AssertionError(url)
        with self.assertRaisesRegex(ValueError, "starter_not_confirmed"):
            validate_starters_for_phase(_game(), "LATE", getter=get)

    def test_early_allows_provisional_identity(self):
        def get(url, params):
            return {}
        evidence = validate_starters_for_phase(_game(), "EARLY", getter=get)
        self.assertTrue(evidence["eligible"])


if __name__ == "__main__":
    unittest.main()
