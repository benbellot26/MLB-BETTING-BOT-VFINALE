from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path("data")
OUT = ROOT / "v13_legacy_evidence_inventory.json"

TRACKED = (
    ROOT / "v13_historical_backfill.jsonl",
    ROOT / "v11_3_live.jsonl",
    ROOT / "mlb_backtest_2026.jsonl",
    ROOT / "mlb_run_seed_2026.jsonl",
)


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                pass
    except Exception:
        pass
    return out


def _gzip_json(path: Path) -> list[dict[str, Any]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        # Source replay containers generally carry per-request payloads, but for
        # inventory purposes the top-level metadata is enough to prove a replay exists.
        return [obj]
    return []


def _gid(row: dict[str, Any]) -> str:
    return str(row.get("game_pk") or row.get("gamePk") or row.get("game_id") or "")


def _has_baseball_probability(row: dict[str, Any]) -> bool:
    for opt in row.get("options") or []:
        if any(opt.get(k) is not None for k in ("p_baseball_raw", "p_learned")):
            return True
    return False


def classify(row: dict[str, Any], source: str) -> tuple[str, str]:
    schema = str(row.get("schema") or "")
    if source == "v13_historical_backfill.jsonl" or schema.startswith("v13-point-in-time-backfill"):
        if row.get("point_in_time") is True and row.get("features_from_postgame") is not True and _has_baseball_probability(row):
            return "A", "exact V13 point-in-time replay"
    if source == "v11_3_live.jsonl":
        if row.get("point_in_time") is True and row.get("features_from_postgame") is not True and _has_baseball_probability(row):
            if str(row.get("probability_contract_version") or "").startswith("13"):
                return "A", "native V13 pregame journal"
            return "B", "legacy pregame journal with baseball-only probability"
        if row.get("features_from_postgame") is True:
            return "D", "postgame-derived feature flag"
        if _has_baseball_probability(row):
            return "C", "probability retained but exact pregame provenance incomplete"
    if source == "mlb_backtest_2026.jsonl":
        return "C", "leakage-audited FINAL_RECONSTRUCTED cohort; transferable priors only"
    if source == "mlb_run_seed_2026.jsonl":
        return "C", "run-distribution research seed; not native V13 probability evidence"
    return "D", "unclassified/incomplete provenance"


def build() -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    source_counts: dict[str, Counter] = defaultdict(Counter)
    source_games: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for path in TRACKED:
        source = path.name
        for row in _jsonl(path):
            grade, reason = classify(row, source)
            gid = _gid(row)
            source_counts[source][grade] += 1
            if gid:
                source_games[source][grade].add(gid)
            observations.append({"source": source, "grade": grade, "game_pk": gid, "reason": reason})

    replay_files = sorted(Path("runtime/v13_legacy_replays").glob("*.json.gz")) + sorted(Path("runtime/v13_legacy_replays").glob("*.jsonl.gz"))
    replay_file_games: set[str] = set()
    for path in replay_files:
        # Existing durable source replays are grade A as source evidence, but a game
        # is only calibration-usable after V13 replay has produced a settled row.
        for row in _gzip_json(path):
            gid = _gid(row)
            if gid:
                replay_file_games.add(gid)

    unique_by_grade: dict[str, set[str]] = defaultdict(set)
    best_grade: dict[str, str] = {}
    rank = {"D": 0, "C": 1, "B": 2, "A": 3}
    for obs in observations:
        gid = obs["game_pk"]
        if not gid:
            continue
        g = obs["grade"]
        if gid not in best_grade or rank[g] > rank[best_grade[gid]]:
            best_grade[gid] = g
    for gid, grade in best_grade.items():
        unique_by_grade[grade].add(gid)

    exact_rows = [o for o in observations if o["grade"] == "A"]
    exact_games = unique_by_grade.get("A", set())
    migratable_games = exact_games | unique_by_grade.get("B", set())

    report = {
        "schema": "v13-legacy-evidence-inventory-v1",
        "policy": {
            "A": "exact/native point-in-time: admissible for V13 evidence after dedupe",
            "B": "pregame baseball-only legacy: migration candidate; requires compatibility audit",
            "C": "research/prior only; never counted as native calibration sample",
            "D": "rejected for probability uncertainty/calibration",
        },
        "sources": {},
        "unique_games_best_grade": {g: len(unique_by_grade.get(g, set())) for g in ("A", "B", "C", "D")},
        "exact_admissible_games": len(exact_games),
        "A_or_B_candidate_games": len(migratable_games),
        "durable_replay_files_found": len(replay_files),
        "durable_replay_game_ids_visible": len(replay_file_games),
        "notes": [
            "The 1,801 reconstructed games are not promoted to native V13 calibration evidence.",
            "A/B counts are deduplicated by game_pk before any downstream use.",
            "Durable replay archives prove source availability; settled V13 replay rows remain required for calibration.",
        ],
    }
    for source in sorted(source_counts):
        report["sources"][source] = {
            "rows_by_grade": {g: source_counts[source].get(g, 0) for g in ("A", "B", "C", "D")},
            "unique_games_by_grade": {g: len(source_games[source].get(g, set())) for g in ("A", "B", "C", "D")},
        }
    return report


def main() -> None:
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
