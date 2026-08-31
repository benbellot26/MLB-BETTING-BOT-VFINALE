from __future__ import annotations

"""Canonical timing policy over ALREADY-PERSISTED V14 snapshots.

No network access exists in this module. It normalizes heterogeneous manual run
zeiten without multiplying Odds/MLB API calls. Missing canonical windows stay
missing rather than being reconstructed retrospectively.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

PREDICTIONS = Path("data/v14_predictions.jsonl")
OUTPUT = Path("data/v14_snapshot_policy_report.json")

WINDOWS = {
    "EARLY": {"min_minutes": 360.0, "max_minutes": 720.0, "target_minutes": 540.0},
    "LATE": {"min_minutes": 120.0, "max_minutes": 240.0, "target_minutes": 180.0},
    "FINAL": {"min_minutes": 10.0, "max_minutes": 60.0, "target_minutes": 30.0},
}


def _dt(value: Any) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if out.tzinfo is None: out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def _read(path: Path | str = PREDICTIONS) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists(): return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row = json.loads(line)
        except Exception: continue
        if isinstance(row, dict): rows.append(row)
    return rows


def minutes_to_game(row: dict[str, Any]) -> float | None:
    game = _dt(row.get("game_date")); analyzed = _dt(row.get("analyzed_at"))
    if game is None or analyzed is None: return None
    return (game - analyzed).total_seconds() / 60.0


def canonical_bucket(row: dict[str, Any]) -> str | None:
    minutes = minutes_to_game(row)
    if minutes is None: return None
    for phase, spec in WINDOWS.items():
        if spec["min_minutes"] <= minutes <= spec["max_minutes"]:
            return phase
    return None


def select_canonical(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        game_pk = str(row.get("game_pk") or "")
        phase = canonical_bucket(row)
        if game_pk and phase:
            grouped[game_pk][phase].append(row)
    output: dict[str, dict[str, dict[str, Any]]] = {}
    for game_pk, phases in grouped.items():
        output[game_pk] = {}
        for phase, candidates in phases.items():
            target = WINDOWS[phase]["target_minutes"]
            chosen = min(
                candidates,
                key=lambda row: (
                    abs((minutes_to_game(row) or 0.0) - target),
                    str(row.get("analyzed_at") or ""),
                ),
            )
            output[game_pk][phase] = chosen
    return output


def canonical_rows(rows: list[dict[str, Any]], phase: str | None = None) -> list[dict[str, Any]]:
    selected = select_canonical(rows); out: list[dict[str, Any]] = []
    wanted = str(phase).upper() if phase else None
    for game_pk in sorted(selected):
        for name in ("EARLY", "LATE", "FINAL"):
            if wanted and name != wanted: continue
            row = selected[game_pk].get(name)
            if row is not None: out.append(row)
    return out


def build_report(path: Path | str = PREDICTIONS) -> dict[str, Any]:
    rows = _read(path); selected = select_canonical(rows)
    all_games = sorted({str(r.get("game_pk") or "") for r in rows if r.get("game_pk")})
    counts = {phase: sum(phase in phases for phases in selected.values()) for phase in WINDOWS}
    missing = {phase: [g for g in all_games if phase not in selected.get(g, {})] for phase in WINDOWS}
    return {
        "schema": "pulsar-v14-canonical-snapshot-policy-v1",
        "acquisition_policy": "OBSERVED_ONLY_ZERO_ADDITIONAL_API_CALLS",
        "network_calls": 0,
        "rows_observed": len(rows),
        "games_observed": len(all_games),
        "canonical_counts": counts,
        "coverage_rate": {phase: (counts[phase] / len(all_games) if all_games else 0.0) for phase in WINDOWS},
        "missing_games": missing,
        "windows_minutes_to_game": WINDOWS,
        "selection_rule": "closest persisted snapshot to fixed target inside window; no retrospective reconstruction",
    }


def write_report(predictions: Path | str = PREDICTIONS, output: Path | str = OUTPUT) -> dict[str, Any]:
    report = build_report(predictions); target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build zero-API canonical snapshot timing report")
    parser.add_argument("--predictions", default=str(PREDICTIONS)); parser.add_argument("--output", default=str(OUTPUT)); args = parser.parse_args()
    report = write_report(args.predictions, args.output)
    print(json.dumps({"games": report["games_observed"], "canonical_counts": report["canonical_counts"], "network_calls": 0}, sort_keys=True))


if __name__ == "__main__": main()
