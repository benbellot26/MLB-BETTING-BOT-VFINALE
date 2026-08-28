from __future__ import annotations

import re
import unittest
from pathlib import Path


USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class GitHubActionsPinningTests(unittest.TestCase):
    def test_repository_actions_use_immutable_commit_shas(self) -> None:
        failures: list[str] = []
        workflow_dir = Path(".github/workflows")
        for path in sorted(workflow_dir.glob("*.y*ml")):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                match = USES_RE.match(line)
                if not match:
                    continue
                target = match.group(1)
                if target.startswith("./") or target.startswith("docker://"):
                    continue
                if "@" not in target:
                    failures.append(f"{path}:{line_no}: action has no ref: {target}")
                    continue
                action, ref = target.rsplit("@", 1)
                if not SHA_RE.fullmatch(ref):
                    failures.append(f"{path}:{line_no}: {action}@{ref} is not pinned to a 40-char commit SHA")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
