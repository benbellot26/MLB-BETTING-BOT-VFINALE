from __future__ import annotations

"""Fail-closed reproducibility audit for V14 runtime dependencies.

The audit distinguishes true third-party dependencies from repository-local
compatibility/reference modules. Production import boundaries (including the
ban on V11 imports in the native V14 path) are enforced separately by the
existing import-boundary regression tests.
"""

import argparse
import ast
import json
from pathlib import Path
import sys
from typing import Any

DEFAULT_ROOT = Path("v14")
ALLOWED_LOCAL_TOP_LEVEL = {"v14", "v11"}


def imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def audit(root: Path | str = DEFAULT_ROOT) -> dict[str, Any]:
    root = Path(root)
    stdlib = set(sys.stdlib_module_names)
    external: dict[str, list[str]] = {}
    local_cross_imports: dict[str, list[str]] = {}
    files = sorted(root.glob("*.py"))
    for path in files:
        imports = imported_top_levels(path)
        local = sorted(name for name in imports if name in ALLOWED_LOCAL_TOP_LEVEL and name != "v14")
        if local:
            local_cross_imports[str(path)] = local
        unknown = sorted(
            name for name in imports
            if name not in stdlib and name not in ALLOWED_LOCAL_TOP_LEVEL
        )
        if unknown:
            external[str(path)] = unknown
    return {
        "schema": "pulsar-v14-reproducibility-audit-v2",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "files_scanned": len(files),
        "repository_local_cross_imports": local_cross_imports,
        "third_party_runtime_imports": external,
        "zero_third_party_runtime_dependencies": not external,
        "valid": not external,
        "policy": (
            "V14 uses only the Python standard library plus repository-local compatibility/reference modules. "
            "Any future third-party dependency must be explicitly declared and reproducibly pinned before merge; "
            "native-production legacy-import isolation is enforced by separate regression tests."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit V14 runtime dependency reproducibility")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--output")
    parser.add_argument("--fail-on-external", action="store_true")
    args = parser.parse_args()
    report = audit(args.root)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    if args.fail_on_external and not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
