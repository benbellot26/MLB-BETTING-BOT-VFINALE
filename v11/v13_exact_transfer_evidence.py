from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract

REPLAY_FILE = Path("data/v13_historical_backfill.jsonl")
NATIVE_FEATURE_FILE = Path("data/v13_feature_store.jsonl")
NATIVE_LABEL_FILE = Path("data/v13_label_store.jsonl")
SCHEMA = "v13-exact-transfer-evidence-v1"
PRE_CANDIDATE_BASELINE_SOURCE = "v123-compose-runtime-pre-v13-candidate"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out and abs(out) != float("inf") else default
    except Exception:
        return default


def _dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _season(row: dict[str, Any]) -> int:
    try:
        return int(row.get("season") or str(row.get("game_date") or "")[:4])
    except Exception:
        return 0


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _replay_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    if str(row.get("phase") or "").upper() != "FINAL":
        return None
    if not contract.row_is_predictively_compatible(row):
        return None
    if row.get("validation_baseline_model_generation") != contract.MODEL_GENERATION_FINGERPRINT:
        return None
    if row.get("point_in_time") is not True or row.get("features_from_postgame") is not False:
        return None
    if row.get("home_score") is None or row.get("away_score") is None:
        return None
    hmu = _num(row.get("validation_baseline_home_runs"), 0.0)
    amu = _num(row.get("validation_baseline_away_runs"), 0.0)
    dispersion = _num(row.get("validation_baseline_dispersion"), 0.0)
    if hmu <= 0 or amu <= 0 or dispersion <= 0:
        return None
    gid = str(row.get("game_pk") or "")
    if not gid:
        return None
    return {
        "schema": SCHEMA,
        "game_pk": row.get("game_pk"),
        "game_date": row.get("game_date"),
        "season": _season(row),
        "phase": "FINAL",
        "validation_baseline_home_runs": hmu,
        "validation_baseline_away_runs": amu,
        "validation_baseline_dispersion": dispersion,
        "validation_baseline_environment_sigma": _num(row.get("validation_baseline_environment_sigma"), 0.08),
        "validation_baseline_model_generation": contract.MODEL_GENERATION_FINGERPRINT,
        "home_score": int(row["home_score"]),
        "away_score": int(row["away_score"]),
        "point_in_time": True,
        "exact_evidence_source": "EXACT_REPLAY_CURRENT_GENERATION_FINAL",
        "exact_evidence_rank": str(row.get("analyzed_at") or row.get("as_of") or ""),
    }


def _label_index(path: Path) -> dict[str, dict[str, Any]]:
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in _jsonl(path):
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        gid = str(row.get("game_pk") or "")
        if not gid:
            continue
        rank = str(row.get("settled_at") or "")
        if gid not in best or rank > best[gid][0]:
            best[gid] = (rank, row)
    return {gid: item[1] for gid, item in best.items()}


def _native_candidate(row: dict[str, Any], label: dict[str, Any] | None) -> dict[str, Any] | None:
    if label is None:
        return None
    if str(row.get("phase") or "").upper() != "FINAL":
        return None
    if row.get("model_generation") != contract.MODEL_GENERATION_FINGERPRINT:
        return None
    if row.get("point_in_time") is not True:
        return None
    if row.get("point_in_time_validation_reasons"):
        return None
    # Feature rows must stay label-free; outcomes are joined only after settlement.
    if any(key in row for key in ("home_score", "away_score", "winner")):
        return None
    as_of = _dt(row.get("as_of"))
    game_date = _dt(row.get("game_date"))
    if as_of is None or game_date is None or not as_of < game_date:
        return None
    features = row.get("features") or {}
    run_prior = ((features.get("historical_bootstrap") or {}).get("run_prior") or {})
    if run_prior.get("v13_validation_model_generation") != contract.MODEL_GENERATION_FINGERPRINT:
        return None
    if run_prior.get("v13_validation_baseline_source") != PRE_CANDIDATE_BASELINE_SOURCE:
        return None
    hmu = _num(run_prior.get("v13_validation_baseline_home_mu"), 0.0)
    amu = _num(run_prior.get("v13_validation_baseline_away_mu"), 0.0)
    dispersion = _num(run_prior.get("v13_validation_baseline_dispersion"), 0.0)
    env_sigma = _num(run_prior.get("v13_validation_baseline_environment_sigma"), 0.0)
    if hmu <= 0 or amu <= 0 or dispersion <= 0 or env_sigma < 0:
        return None
    gid = str(row.get("game_pk") or "")
    if not gid or gid != str(label.get("game_pk") or ""):
        return None
    return {
        "schema": SCHEMA,
        "game_pk": row.get("game_pk"),
        "game_date": row.get("game_date"),
        "season": _season(row),
        "phase": "FINAL",
        "validation_baseline_home_runs": hmu,
        "validation_baseline_away_runs": amu,
        "validation_baseline_dispersion": dispersion,
        "validation_baseline_environment_sigma": env_sigma,
        "validation_baseline_model_generation": contract.MODEL_GENERATION_FINGERPRINT,
        "home_score": int(label["home_score"]),
        "away_score": int(label["away_score"]),
        "point_in_time": True,
        "exact_evidence_source": "NATIVE_CURRENT_GENERATION_FINAL",
        "exact_evidence_rank": str(row.get("as_of") or ""),
    }


def load_exact_final_rows(
    replay_path: Path = REPLAY_FILE,
    feature_path: Path = NATIVE_FEATURE_FILE,
    label_path: Path = NATIVE_LABEL_FILE,
    *,
    include_native: bool = True,
) -> list[dict[str, Any]]:
    """Return deduplicated independent FINAL transfer evidence.

    Archived exact replays and genuine native current-generation FINAL snapshots
    are both admissible only when they carry the frozen pre-candidate V13
    baseline. Reconstructed free history is deliberately not read here.
    Native evidence wins a duplicate because it is the genuine live PIT record.
    """
    best: dict[str, tuple[int, str, dict[str, Any]]] = {}

    for raw in _jsonl(replay_path):
        row = _replay_candidate(raw)
        if row is None:
            continue
        gid = str(row["game_pk"])
        rank = str(row.get("exact_evidence_rank") or "")
        candidate = (1, rank, row)
        if gid not in best or candidate[:2] > best[gid][:2]:
            best[gid] = candidate

    if include_native:
        labels = _label_index(label_path)
        for raw in _jsonl(feature_path):
            gid = str(raw.get("game_pk") or "")
            row = _native_candidate(raw, labels.get(gid))
            if row is None:
                continue
            rank = str(row.get("exact_evidence_rank") or "")
            candidate = (2, rank, row)
            if gid not in best or candidate[:2] > best[gid][:2]:
                best[gid] = candidate

    rows = [item[2] for item in best.values()]
    return sorted(rows, key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or "")))


def source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("exact_evidence_source") or "INJECTED_TEST_EVIDENCE") for row in rows)
    return dict(sorted(counts.items()))
