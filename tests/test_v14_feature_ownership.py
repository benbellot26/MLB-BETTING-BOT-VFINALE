from __future__ import annotations

import unittest

from v14.feature_ownership import FeatureClaim, assert_no_probability_feature_overlap, contract_payload, duplicate_feature_ids


class V14FeatureOwnershipTests(unittest.TestCase):
    def test_current_contract_has_no_duplicate_probability_feature_family(self)->None:
        assert_no_probability_feature_overlap()
        payload=contract_payload()
        self.assertEqual(payload["duplicate_feature_ids"],{})
        self.assertFalse(payload["market_probability_used_as_feature"])
        self.assertIn("STRUCTURAL",payload["owners"])
        self.assertIn("CONTEXT",payload["owners"])
        self.assertIn("ALL_STATS",payload["owners"])

    def test_duplicate_claim_fails_closed(self)->None:
        claims=(FeatureClaim("same","CONTEXT","a"),FeatureClaim("same","ALL_STATS","b"),FeatureClaim("structural","STRUCTURAL","c"))
        self.assertEqual(duplicate_feature_ids(claims),{"same":["CONTEXT","ALL_STATS"]})
        with self.assertRaisesRegex(RuntimeError,"ownership overlap"):
            assert_no_probability_feature_overlap(claims)


if __name__=="__main__":unittest.main()
