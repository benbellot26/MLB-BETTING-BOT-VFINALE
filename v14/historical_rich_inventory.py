from __future__ import annotations

"""Schema/coverage inventory for the 1,801-game rich 2026 reconstruction.

This never treats postgame labels as features. It only inventories key paths so
V14 challengers can declare which historical components are actually testable.
"""

from collections import Counter
import argparse
import json
from pathlib import Path
from typing import Any

SOURCE = Path("data/mlb_backtest_2026.jsonl")
INTEREST = ("starter", "pitcher", "bullpen", "lineup", "platoon", "statcast", "weather", "innings", "pitch_count", "rest", "travel", "park")
LABEL_PATHS = {"home_score", "away_score", "result", "winner"}


def _walk(value: Any, prefix: str = "", depth: int = 0):
    if depth > 5:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, child
            yield from _walk(child, path, depth + 1)
    elif isinstance(value, list) and value:
        path = f"{prefix}[]"
        yield path, value[0]
        yield from _walk(value[0], path, depth + 1)


def build(path: Path | str = SOURCE) -> dict[str, Any]:
    source = Path(path)
    rows = 0
    path_counts: Counter[str] = Counter()
    top_counts: Counter[str] = Counter()
    valid_baseline = 0
    with source.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line); rows += 1
            if isinstance(row, dict):
                for key in row:
                    top_counts[str(key)] += 1
                v10 = row.get("v10") or {}
                if isinstance(v10, dict) and v10.get("home_struct") is not None and v10.get("away_struct") is not None:
                    valid_baseline += 1
                for key, child in _walk(row):
                    low = key.lower()
                    if any(token in low for token in INTEREST) and not any(part in LABEL_PATHS for part in low.split(".")):
                        if child is not None:
                            path_counts[key] += 1
    paths = [{"path": key, "n": count, "coverage": count / rows if rows else 0.0} for key, count in path_counts.most_common(160)]
    return {
        "schema": "pulsar-v14-rich-historical-inventory-v1",
        "role": "DATA_INVENTORY_ONLY",
        "source": str(source),
        "rows": rows,
        "v10_structural_baseline_rows": valid_baseline,
        "top_level_keys": sorted(top_counts),
        "interesting_paths": paths,
        "labels_never_declared_features": True,
        "note": "Coverage inventory only; each candidate still needs an explicit PIT provenance contract before historical use.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--source", default=str(SOURCE)); parser.add_argument("--output"); args = parser.parse_args(); out = build(args.source)
    if args.output:
        Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
