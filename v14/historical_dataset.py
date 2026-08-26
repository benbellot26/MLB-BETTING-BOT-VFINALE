from __future__ import annotations

"""Strict historical point-in-time dataset loader for V14 research.

This module intentionally consumes only immutable, pre-existing V137 feature
rows and separately stored labels.  It never calls live MLB season endpoints
while reconstructing old games.
"""

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path("data/v137")
MANIFEST = Path("data/v138_dataset_manifest.json")
FORBIDDEN_LABEL_KEYS = frozenset({
    "home_score", "away_score", "home_win", "total_runs", "run_margin_home",
    "result", "winner", "label", "target",
})
REQUIRED_PROVENANCE_RULE = "strictly earlier officialDate only"


def _dt(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_gz(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                raise ValueError(f"invalid JSONL row {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"non-object JSONL row {path}:{line_number}")
            rows.append(row)
    return rows


def source_paths(base: Path = DATA_DIR) -> list[Path]:
    return sorted(base.glob("team_features_*.jsonl.gz")) + sorted(base.glob("team_labels_*.jsonl.gz"))


def verify_manifest(manifest_path: Path = MANIFEST, base: Path = DATA_DIR) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        str(item.get("path")): str(item.get("sha256"))
        for item in manifest.get("files") or []
        if str(item.get("path") or "").startswith("data/v137/team_")
    }
    actual_paths = source_paths(base)
    if len(actual_paths) != len(expected):
        raise ValueError(f"historical source-count mismatch actual={len(actual_paths)} expected={len(expected)}")
    checked = []
    for path in actual_paths:
        key = str(path).replace("\\", "/")
        if key not in expected:
            raise ValueError(f"historical source absent from manifest: {key}")
        digest = sha256_file(path)
        if digest != expected[key]:
            raise ValueError(f"historical source hash mismatch: {key}")
        checked.append({"path": key, "sha256": digest})
    return {
        "schema": "pulsar-v14-historical-source-integrity-v1",
        "verified": True,
        "dataset_content_sha256": manifest.get("dataset_content_sha256"),
        "feature_contract_sha256": manifest.get("feature_contract_sha256"),
        "source_files": checked,
        "source_file_count": len(checked),
    }


def _forbidden_paths(value: Any, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_LABEL_KEYS:
                hits.append(path)
            hits.extend(_forbidden_paths(child, path))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            hits.extend(_forbidden_paths(child, f"{prefix}[{i}]"))
    return hits


def _feature_provenance_ok(row: dict[str, Any]) -> bool:
    provenance = row.get("provenance") or {}
    prior = provenance.get("mlb_prior_results") or {}
    return (
        str(prior.get("point_in_time_rule") or "") == REQUIRED_PROVENANCE_RULE
        and prior.get("same_day_games_excluded") is True
    )


def _season(row: dict[str, Any]) -> int:
    raw = row.get("season") or str(row.get("official_date") or row.get("game_date") or "")[:4]
    return int(raw)


def load_raw(base: Path = DATA_DIR) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    features: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    for path in sorted(base.glob("team_features_*.jsonl.gz")):
        features.extend(_read_gz(path))
    for path in sorted(base.glob("team_labels_*.jsonl.gz")):
        labels.extend(_read_gz(path))
    return features, labels


def audit(features: list[dict[str, Any]], labels: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    feature_ids: set[str] = set()
    label_ids: set[str] = set()
    seasons: set[int] = set()
    for row in features:
        gid = str(row.get("game_pk") or "")
        if not gid:
            failures.append("feature_missing_game_pk")
            continue
        if gid in feature_ids:
            failures.append(f"duplicate_feature_game_pk:{gid}")
        feature_ids.add(gid)
        try:
            seasons.add(_season(row))
            if not (_dt(row.get("as_of")) < _dt(row.get("game_date"))):
                failures.append(f"feature_not_strictly_pregame:{gid}")
        except Exception:
            failures.append(f"feature_bad_timestamp:{gid}")
        hits = _forbidden_paths(row.get("features") or {})
        if hits:
            failures.append(f"feature_contains_label:{gid}:{hits[0]}")
        if not _feature_provenance_ok(row):
            failures.append(f"feature_provenance_not_j1_safe:{gid}")
    for row in labels:
        gid = str(row.get("game_pk") or "")
        if not gid:
            failures.append("label_missing_game_pk")
            continue
        if gid in label_ids:
            failures.append(f"duplicate_label_game_pk:{gid}")
        label_ids.add(gid)
        if row.get("home_score") is None or row.get("away_score") is None:
            failures.append(f"label_missing_score:{gid}")
    missing_labels = sorted(feature_ids - label_ids)
    missing_features = sorted(label_ids - feature_ids)
    if missing_labels:
        failures.append(f"features_without_labels:{len(missing_labels)}")
    if missing_features:
        failures.append(f"labels_without_features:{len(missing_features)}")
    return {
        "schema": "pulsar-v14-historical-dataset-audit-v1",
        "passed": not failures,
        "feature_rows": len(features),
        "label_rows": len(labels),
        "unique_feature_games": len(feature_ids),
        "unique_label_games": len(label_ids),
        "seasons": sorted(seasons),
        "failures": failures[:100],
        "failure_count": len(failures),
        "policy": {
            "features_labels_physically_separate": True,
            "strictly_pregame_as_of_required": True,
            "same_day_results_excluded": True,
            "live_season_endpoint_backfill_forbidden": True,
        },
    }


def paired_rows(features: list[dict[str, Any]], labels: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    report = audit(features, labels)
    if not report["passed"]:
        raise ValueError(f"historical dataset audit failed: {report['failures'][:3]}")
    by_label = {str(row["game_pk"]): row for row in labels}
    pairs = [(row, by_label[str(row["game_pk"])]) for row in features]
    return sorted(pairs, key=lambda pair: (_dt(pair[0].get("game_date")), str(pair[0].get("game_pk"))))


def split_by_season(pairs: Iterable[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, list[tuple[dict[str, Any], dict[str, Any]]]]:
    out = {"tuning": [], "validation": [], "frozen_test": []}
    for pair in pairs:
        season = _season(pair[0])
        if season <= 2024:
            out["tuning"].append(pair)
        elif season == 2025:
            out["validation"].append(pair)
        elif season == 2026:
            out["frozen_test"].append(pair)
    return out


def load_verified(base: Path = DATA_DIR, manifest_path: Path = MANIFEST) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], dict[str, Any]]:
    integrity = verify_manifest(manifest_path, base)
    features, labels = load_raw(base)
    report = audit(features, labels)
    if not report["passed"]:
        raise ValueError(f"historical PIT audit failed: {report['failures'][:5]}")
    pairs = paired_rows(features, labels)
    return pairs, {"integrity": integrity, "audit": report}
