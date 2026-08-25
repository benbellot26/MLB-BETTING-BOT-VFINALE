from __future__ import annotations

import ast
from pathlib import Path
import unittest


# Compatibility modules may understand legacy-shaped data, but the native
# production path must never import or execute V11/V13 code.
NATIVE_MODULES = (
    "acquisition.py",
    "context_overlay.py",
    "discord.py",
    "distribution.py",
    "market_lines.py",
    "mlb_inputs.py",
    "model.py",
    "native_candidate.py",
    "native_payload.py",
    "parity_gate.py",
    "park.py",
    "pipeline.py",
    "production_runtime.py",
    "run_stack.py",
    "structural.py",
)


class V14ImportBoundaryTests(unittest.TestCase):
    def test_native_v14_modules_do_not_import_v11(self):
        violations = []
        root = Path("v14")
        for filename in NATIVE_MODULES:
            path = root / filename
            self.assertTrue(path.exists(), f"missing native V14 module: {path}")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "v11" or alias.name.startswith("v11."):
                            violations.append(f"{path}:{node.lineno} import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "v11" or module.startswith("v11."):
                        violations.append(f"{path}:{node.lineno} from {module} import ...")
        self.assertEqual(violations, [], "legacy imports leaked into native V14:\n" + "\n".join(violations))

    def test_native_candidate_is_explicitly_non_publishing(self):
        text = Path("v14/native_candidate.py").read_text(encoding="utf-8")
        self.assertIn('"role": "CANDIDATE_NON_PUBLISHING"', text)
        self.assertIn('"cutover_authorized": False', text)


if __name__ == "__main__":
    unittest.main()
