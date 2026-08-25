import unittest

from v14.champion_contract import validated_extra_innings_home_probability
from v14 import park


class V14ArtifactTests(unittest.TestCase):
    def test_extra_innings_prior_is_native_and_mature(self):
        probability,meta=validated_extra_innings_home_probability(); self.assertTrue(meta["active"]); self.assertGreaterEqual(meta["n"],200); self.assertGreaterEqual(probability,.45); self.assertLessEqual(probability,.55); self.assertIn("pulsar-v14",str(meta.get("evidence_schema")))
    def test_park_manifest_resolves_historical_evidence(self):
        artifact=park.load(); self.assertIsInstance(artifact,dict); self.assertTrue(artifact.get("seasons"))

if __name__=="__main__": unittest.main()
