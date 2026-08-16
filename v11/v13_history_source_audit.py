from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SOURCE = Path("data/mlb_backtest_2026.jsonl")


def _present(v: Any) -> bool:
    return v is not None and v != "" and v != [] and v != {}


def _flatten(prefix: str, value: Any, out: set[str], depth: int = 0) -> None:
    if depth > 3:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.add(key)
            _flatten(key, v, out, depth + 1)


def main() -> None:
    rows = []
    with SOURCE.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))

    keys = Counter()
    nested = Counter()
    types = defaultdict(Counter)
    dates = []
    examples = []
    for row in rows:
        paths: set[str] = set()
        _flatten("", row, paths)
        for p in paths:
            nested[p] += 1
        for k, v in row.items():
            if _present(v):
                keys[k] += 1
            types[k][type(v).__name__] += 1
        if row.get("game_date"):
            dates.append(str(row["game_date"]))
        if len(examples) < 3:
            examples.append({
                "game_pk": row.get("game_pk"),
                "game_date": row.get("game_date"),
                "home": row.get("home"),
                "away": row.get("away"),
                "top_level_keys": sorted(row.keys()),
                "starters": row.get("starters"),
                "v10_keys": sorted((row.get("v10") or {}).keys()),
                "rl_proxy": row.get("rl_proxy"),
            })

    critical = [
        "game_pk", "game_date", "home", "away", "home_score", "away_score",
        "starters", "starters.home_id", "starters.away_id", "starters.home_hand", "starters.away_hand",
        "v10", "v10.home_struct", "v10.away_struct", "v10.p_home", "v10.p_model",
        "rl_proxy", "total_proxy", "odds", "bookmakers", "lineups", "weather",
    ]
    critical_counts = {k: nested.get(k, keys.get(k, 0)) for k in critical}
    report = {
        "source": str(SOURCE),
        "rows": len(rows),
        "unique_games": len({str(r.get("game_pk")) for r in rows if r.get("game_pk") is not None}),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "top_level_presence": dict(keys.most_common()),
        "critical_presence": critical_counts,
        "nested_presence": dict(sorted(nested.items(), key=lambda kv: (-kv[1], kv[0]))[:160]),
        "types": {k: dict(v) for k, v in types.items()},
        "examples": examples,
        "audit_note": "Presence does not prove pregame provenance. Final scores are labels only; any current-game lineup/starter identity requires a separate provenance decision.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
