from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest


class V1310ChampionOnlyTests(unittest.TestCase):
    def _run(self, *, v115: str | None, v124: str | None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for name, value in (
            ("V1232_ENABLE_V115_SHADOW", v115),
            ("V124_ENABLE_SHADOW", v124),
        ):
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        code = textwrap.dedent(
            """
            import os
            import v11.v13_entry  # installs V13.10 defaults before v123_entry
            from v11 import predictive_v124, shadow_v115
            print(int(shadow_v115.enabled()), int(predictive_v124.enabled()))
            """
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_legacy_shadows_are_off_by_default_for_v1310(self):
        proc = self._run(v115=None, v124=None)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip().splitlines()[-1], "0 0")

    def test_research_can_opt_in_explicitly(self):
        proc = self._run(v115="1", v124="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip().splitlines()[-1], "1 1")


if __name__ == "__main__":
    unittest.main()
