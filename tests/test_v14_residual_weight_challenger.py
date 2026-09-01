from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from v14.residual_weight_challenger import build


class V14ResidualWeightChallengerTests(unittest.TestCase):
    def test_empty_evidence_collects_without_network_or_champion_impact(self)->None:
        with TemporaryDirectory() as tmp:
            out=build(Path(tmp)/"missing.jsonl")
            self.assertEqual(out["status"],"COLLECTING")
            self.assertEqual(out["network_calls"],0)
            self.assertFalse(out["champion_impact"])
            self.assertFalse(out["auto_activation"])
            self.assertFalse(out["market_probability_used_as_feature"])


if __name__=="__main__":unittest.main()
