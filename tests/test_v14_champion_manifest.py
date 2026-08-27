from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION
from v14.champion_manifest import CHAMPION_SOURCE_BLOBS, MANIFEST_GENERATION, validate


class V14ChampionManifestTests(unittest.TestCase):
    def test_manifest_matches_current_generation_and_sources(self):
        self.assertEqual(MANIFEST_GENERATION,MODEL_GENERATION)
        out=validate(Path("."))
        self.assertTrue(out["valid"],out)

    def test_mutated_probability_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for relative in CHAMPION_SOURCE_BLOBS:
                target=root/relative; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text("mutated\n",encoding="utf-8")
            out=validate(root)
            self.assertFalse(out["valid"])
            self.assertTrue(out["mismatches"])


if __name__=="__main__": unittest.main()
