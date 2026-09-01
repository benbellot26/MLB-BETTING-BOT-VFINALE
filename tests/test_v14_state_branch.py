from __future__ import annotations

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from v14.state_branch import hydrate, persist


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class V14StateBranchTests(unittest.TestCase):
    def test_file_and_directory_round_trip_on_dedicated_state_branch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            work = root / "work"
            run("git", "init", "--bare", str(remote), cwd=root)
            run("git", "clone", str(remote), str(work), cwd=root)
            run("git", "config", "user.name", "test", cwd=work)
            run("git", "config", "user.email", "test@example.com", cwd=work)

            (work / "README.md").write_text("code\n", encoding="utf-8")
            run("git", "add", "README.md", cwd=work)
            run("git", "commit", "-m", "main", cwd=work)
            run("git", "branch", "-M", "main", cwd=work)
            run("git", "push", "-u", "origin", "main", cwd=work)

            run("git", "checkout", "-b", "runtime-data", cwd=work)
            (work / "data" / "tree").mkdir(parents=True)
            (work / "data" / "one.txt").write_text("one\n", encoding="utf-8")
            (work / "data" / "tree" / "two.txt").write_text("two\n", encoding="utf-8")
            run("git", "add", "data", cwd=work)
            run("git", "commit", "-m", "state", cwd=work)
            run("git", "push", "-u", "origin", "runtime-data", cwd=work)
            run("git", "checkout", "main", cwd=work)

            old = Path.cwd()
            try:
                os.chdir(work)
                out = hydrate(["data/one.txt", "data/tree"], branch="runtime-data")
                self.assertEqual(out["hydrated"], 2)
                self.assertEqual(Path("data/one.txt").read_text(encoding="utf-8"), "one\n")
                self.assertEqual(Path("data/tree/two.txt").read_text(encoding="utf-8"), "two\n")

                Path("data/one.txt").write_text("changed\n", encoding="utf-8")
                Path("data/tree/three.txt").write_text("three\n", encoding="utf-8")
                saved = persist(["data/one.txt", "data/tree"], message="update state", branch="runtime-data")
                self.assertTrue(saved["changed"])

                run("git", "fetch", "origin", "runtime-data", cwd=work)
                one = run("git", "show", "origin/runtime-data:data/one.txt", cwd=work).stdout.decode()
                three = run("git", "show", "origin/runtime-data:data/tree/three.txt", cwd=work).stdout.decode()
                self.assertEqual(one, "changed\n")
                self.assertEqual(three, "three\n")
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
