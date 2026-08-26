import unittest

from v14.venue_geometry import SECONDARY_CARDINAL_ORIENTATION, fetch, fetch_nearest, parse


class VenueGeometryTests(unittest.TestCase):
    def test_parses_mlb_azimuth_and_coordinates(self):
        payload={"venues":[{"id":22,"name":"Dodger Stadium","location":{"azimuthAngle":26,"elevation":515,"defaultCoordinates":{"latitude":34.0739,"longitude":-118.2400}}}]}
        out=parse(payload,22)
        self.assertEqual(out["status"],"READY_SHADOW")
        self.assertEqual(out["outfield_bearing_deg"],26.0)
        self.assertEqual(out["latitude"],34.0739)
        self.assertEqual(out["longitude"],-118.24)
        self.assertEqual(out["source_tier"],"OFFICIAL_MLB")
        self.assertTrue(out["promotion_ready"])
        self.assertFalse(out["champion_impact"])
        self.assertTrue(out["no_imputation"])

    def test_unknown_missing_azimuth_fails_soft_without_imputation(self):
        out=parse({"venues":[{"id":999,"name":"Unknown","location":{"defaultCoordinates":{"latitude":1,"longitude":2}}}]},999)
        self.assertEqual(out["status"],"COLLECTING")
        self.assertNotIn("outfield_bearing_deg",out)

    def test_invalid_azimuth_is_rejected(self):
        out=parse({"venues":[{"id":999,"location":{"azimuthAngle":361}}]},999)
        self.assertEqual(out["status"],"UNAVAILABLE")
        self.assertNotIn("outfield_bearing_deg",out)

    def test_all_known_2026_gaps_have_sourced_cardinal_fallback(self):
        expected={"2735":45.0,"5340":135.0,"5355":45.0,"5445":45.0}
        self.assertEqual(set(SECONDARY_CARDINAL_ORIENTATION),set(expected))
        for venue_id,bearing in expected.items():
            out=parse({"venues":[{"id":int(venue_id),"name":"Special Park","location":{"defaultCoordinates":{}}}]},venue_id)
            self.assertEqual(out["status"],"READY_SHADOW",venue_id)
            self.assertEqual(out["outfield_bearing_deg"],bearing,venue_id)
            self.assertEqual(out["bearing_precision"],"CARDINAL",venue_id)
            self.assertEqual(out["bearing_uncertainty_deg"],22.5,venue_id)
            self.assertEqual(out["source_tier"],"SECONDARY_PUBLISHED_REFERENCE",venue_id)
            self.assertTrue(out["source_url"],venue_id)
            self.assertTrue(out["source_evidence"],venue_id)
            self.assertFalse(out["promotion_ready"],venue_id)
            self.assertFalse(out["champion_impact"],venue_id)
            self.assertTrue(out["no_imputation"],venue_id)

    def test_harp_helu_fallback_supplies_pitch_coordinates_missing_from_mlb(self):
        out=parse({"venues":[{"id":5340,"name":"Estadio Alfredo Harp Helu","location":{}}]},5340)
        self.assertAlmostEqual(out["latitude"],19.40333)
        self.assertAlmostEqual(out["longitude"],-99.08510)
        self.assertIn("828705073",out["coordinate_source_evidence"])

    def test_fetch_uses_mlb_venue_location_hydration(self):
        calls=[]
        def getter(url,params):
            calls.append((url,dict(params)))
            return {"venues":[{"id":10,"name":"Test Park","location":{"azimuthAngle":58,"defaultCoordinates":{"latitude":38.58,"longitude":-121.51}}}]}
        out=fetch(10,getter=getter,retrieved_at="2026-08-26T17:00:00+00:00")
        self.assertTrue(calls[0][0].endswith("/venues/10"))
        self.assertEqual(calls[0][1],{"hydrate":"location"})
        self.assertEqual(out["outfield_bearing_deg"],58.0)
        self.assertEqual(out["retrieved_at"],"2026-08-26T17:00:00+00:00")

    def test_nearest_resolution_keys_to_place_not_team_name(self):
        calls=[]
        def getter(url,params):
            calls.append((url,dict(params)))
            return {"venues":[
                {"id":1,"name":"Old Park","location":{"azimuthAngle":55,"defaultCoordinates":{"latitude":37.75,"longitude":-122.20}}},
                {"id":2,"name":"Temporary Home","location":{"azimuthAngle":20,"defaultCoordinates":{"latitude":38.5806,"longitude":-121.5130}}},
            ]}
        out=fetch_nearest(38.5806,-121.5130,season=2026,getter=getter,retrieved_at="2026-08-26T17:00:00+00:00")
        self.assertEqual(out["venue_id"],"2")
        self.assertEqual(out["outfield_bearing_deg"],20.0)
        self.assertLess(out["nearest_distance_km"],0.01)
        self.assertEqual(calls[0][1]["sportIds"],1)
        self.assertEqual(calls[0][1]["season"],2026)
        self.assertEqual(calls[0][1]["hydrate"],"location")


if __name__=="__main__":
    unittest.main()
