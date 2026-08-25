from __future__ import annotations

import unittest

from v14.starter_fallback import degraded_sides_from_evidence, degradation_summary, neutralize_probable_pitchers


class V14StarterFallbackTests(unittest.TestCase):
    def _evidence(self, away_schedule="1", away_feed="1", away_box="1"):
        def side(schedule_id, feed_id, box_id):
            return {
                "sources": [
                    {"source": "schedule.probablePitcher", "id": schedule_id, "name": "S", "available": bool(schedule_id)},
                    {"source": "feed.gameData.probablePitchers", "id": feed_id, "name": "F", "available": bool(feed_id)},
                    {"source": "boxscore.pitchers[0]", "id": box_id, "name": "B", "available": bool(box_id)},
                ]
            }
        return {"away": side(away_schedule, away_feed, away_box), "home": side("2", "2", "2")}

    def test_early_never_neutralizes_provisional_starter(self):
        self.assertEqual(degraded_sides_from_evidence(self._evidence("1", "9", "9"), "EARLY"), [])

    def test_late_conflict_neutralizes_only_affected_side(self):
        sides=degraded_sides_from_evidence(self._evidence("1", "9", "9"), "LATE")
        self.assertEqual(sides,["away"])
        game={"teams":{"away":{"probablePitcher":{"id":1,"fullName":"Wrong"}},"home":{"probablePitcher":{"id":2,"fullName":"Right"}}}}
        sanitized=neutralize_probable_pitchers(game,sides)
        self.assertEqual(sanitized["teams"]["away"]["probablePitcher"],{})
        self.assertEqual(sanitized["teams"]["home"]["probablePitcher"]["id"],2)
        self.assertEqual(game["teams"]["away"]["probablePitcher"]["id"],1)

    def test_missing_feed_confirmation_uses_neutral_fallback(self):
        self.assertEqual(degraded_sides_from_evidence(self._evidence("1", None, None), "FINAL"),["away"])

    def test_consensus_does_not_degrade(self):
        self.assertEqual(degraded_sides_from_evidence(self._evidence(),"FINAL"),[])

    def test_summary_is_explicit(self):
        summary=degradation_summary(self._evidence("1","9","9"),["away"])
        self.assertTrue(summary["degraded"])
        self.assertEqual(summary["mode"],"NEUTRAL_STARTER_FALLBACK")
        self.assertEqual(summary["sides"],["away"])


if __name__=="__main__":
    unittest.main()
