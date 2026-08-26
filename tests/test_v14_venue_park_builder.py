import unittest

from v14.venue_park_builder import build
from v14.venue_park_challenger import resolve


def source(promotion=False, end=2025):
    return {
        "schema":"v13-7-prior-park-factors-store-v5",
        "promotion_eligible":promotion,
        "seasons":{
            "2026":{
                "ALL":{
                    "source_window_end_season":end,
                    "source_window_years":[2023,2024,2025],
                    "provider":"Baseball Savant Statcast Park Factors",
                    "promotion_eligible":promotion,
                    "rows":[{"venue_id":"22","venue":"Dodger Stadium","runs_index":96,"park_factor_index":98,"hr_index":110,"source_method":"Savant"}],
                },
                "L":{"rows":[{"venue_id":"22","venue":"Dodger Stadium","runs_index":94}]},
                "R":{"rows":[{"venue_id":"22","venue":"Dodger Stadium","runs_index":98}]},
            }
        },
    }


class V14VenueParkBuilderTests(unittest.TestCase):
    def test_builder_is_venue_keyed_and_strictly_previous_season(self):
        artifact=build(source(),target_season=2026)
        self.assertTrue(artifact["point_in_time"])
        self.assertEqual(artifact["cutoff_day"],"2025-12-31")
        self.assertEqual(artifact["source_window_end_season"],2025)
        self.assertAlmostEqual(artifact["venues"]["22"]["factor"],0.96,places=12)
        self.assertAlmostEqual(artifact["venues"]["22"]["handedness"]["L"]["factor"],0.94,places=12)

    def test_transformation_does_not_upgrade_source_promotion_status(self):
        artifact=build(source(promotion=False),target_season=2026)
        out=resolve(venue_id=22,venue_name="Dodger Stadium",target_date="2026-08-26",artifact=artifact)
        self.assertEqual(out["status"],"READY_SHADOW")
        self.assertAlmostEqual(out["factor"],0.96,places=12)
        self.assertFalse(out["promotion_ready"])
        self.assertIn("not promotion-eligible",out["promotion_blocker"])

    def test_strict_source_window_is_required(self):
        with self.assertRaisesRegex(ValueError,"strictly previous-season"):
            build(source(end=2026),target_season=2026)


if __name__=="__main__": unittest.main()
