import unittest

from v14.venue_geometry import fetch, parse


class VenueGeometryTests(unittest.TestCase):
    def test_parses_mlb_azimuth_and_coordinates(self):
        payload={"venues":[{"id":22,"name":"Dodger Stadium","location":{"azimuthAngle":26,"elevation":515,"defaultCoordinates":{"latitude":34.0739,"longitude":-118.2400}}}]}
        out=parse(payload,22)
        self.assertEqual(out["status"],"READY_SHADOW")
        self.assertEqual(out["outfield_bearing_deg"],26.0)
        self.assertEqual(out["latitude"],34.0739)
        self.assertEqual(out["longitude"],-118.24)
        self.assertFalse(out["champion_impact"])
        self.assertTrue(out["no_imputation"])

    def test_missing_azimuth_fails_soft_without_imputation(self):
        out=parse({"venues":[{"id":999,"name":"Unknown","location":{"defaultCoordinates":{"latitude":1,"longitude":2}}}]},999)
        self.assertEqual(out["status"],"COLLECTING")
        self.assertNotIn("outfield_bearing_deg",out)

    def test_invalid_azimuth_is_rejected(self):
        out=parse({"venues":[{"id":999,"location":{"azimuthAngle":361}}]},999)
        self.assertEqual(out["status"],"UNAVAILABLE")
        self.assertNotIn("outfield_bearing_deg",out)

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


if __name__=="__main__":
    unittest.main()
