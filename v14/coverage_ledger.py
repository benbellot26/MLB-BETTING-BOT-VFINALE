from __future__ import annotations

"""Persist why each production game observation was or was not analyzable.

Consumes the already-built native candidate only; it never calls MLB/Odds APIs.
Coverage is audit-only and cannot authorize a bet. Raw snapshot counts are kept
for compatibility, while unique-game first-observation views make repeated runs,
run-trigger selection and model-generation boundaries visible instead of silently
inflating or mixing coverage.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

LEDGER = Path("data/v14_coverage_ledger.jsonl")
REPORT = Path("data/v14_coverage_report.json")
SCHEMA = "pulsar-v14-coverage-record-v1"
LEGACY_TRIGGER = "LEGACY_UNSPECIFIED"
LEGACY_GENERATION = "LEGACY_UNSPECIFIED"


def _read(path: Path | str = LEDGER) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists(): return []
    out: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row = json.loads(line)
        except Exception: continue
        if isinstance(row, dict) and row.get("schema") == SCHEMA: out.append(row)
    return out


def _write(rows: list[dict[str, Any]], path: Path | str = LEDGER) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")


def _trigger(value: Any) -> str:
    return str(value or LEGACY_TRIGGER).strip().upper() or LEGACY_TRIGGER


def _generation(value: Any) -> str:
    return str(value or LEGACY_GENERATION).strip() or LEGACY_GENERATION


def _phase(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper() or "UNKNOWN"


def _game_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("target_date") or ""), str(row.get("game_pk") or "")


def _parsed_time(value: Any) -> datetime:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if out.tzinfo is None: out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return datetime.max.replace(tzinfo=timezone.utc)


def _first_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First observed row per target-date x game within an already-scoped cohort."""
    first: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = _game_key(row)
        if not key[1]: continue
        incumbent = first.get(key)
        if incumbent is None or (_parsed_time(row.get("analyzed_at")), str(row.get("analyzed_at") or "")) < (_parsed_time(incumbent.get("analyzed_at")), str(incumbent.get("analyzed_at") or "")):
            first[key] = row
    return sorted(first.values(), key=lambda r: (_parsed_time(r.get("analyzed_at")), _game_key(r)))


def rows_from_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    target_date = str(candidate.get("target_date") or "")
    analyzed_at = str(candidate.get("analyzed_at") or "")
    candidate_trigger = _trigger(candidate.get("run_trigger"))
    candidate_generation = _generation(candidate.get("model_generation") or MODEL_GENERATION)
    results = candidate.get("results") or []
    skipped = candidate.get("skipped") or []
    rows: list[dict[str, Any]] = []
    for result in results:
        game_pk = str(result.get("game_pk") or "")
        market = result.get("market_snapshot") or {}; sharp = result.get("sharp_market") or {}; execution = result.get("execution_market") or {}
        market_fresh = market.get("freshness_verified") is True
        sharp_available = sharp.get("freshness_verified") is True and bool(sharp.get("selections"))
        execution_available = execution.get("freshness_verified") is True and bool(execution.get("selections"))
        rows.append({
            "schema": SCHEMA, "model_generation": _generation(result.get("model_generation") or candidate_generation),
            "target_date": target_date, "analyzed_at": str(result.get("analyzed_at") or analyzed_at), "game_pk": game_pk,
            "game_date": result.get("game_date"), "home": result.get("home"), "away": result.get("away"), "scheduled": True,
            "run_trigger": _trigger(result.get("run_trigger") or candidate_trigger), "phase": result.get("phase"),
            "odds_matched": True, "prediction_generated": True,
            "market_fresh": market_fresh, "sharp_available": sharp_available,
            "execution_available": execution_available,
            "fully_market_observable": bool(market_fresh and sharp_available and execution_available),
            "eligible": True, "rejection_reason": None, "network_calls_added": 0,
        })
    for item in skipped:
        reason = str(item.get("reason") or "unknown")
        rows.append({
            "schema": SCHEMA, "model_generation": _generation(item.get("model_generation") or candidate_generation),
            "target_date": target_date, "analyzed_at": str(item.get("analyzed_at") or analyzed_at),
            "game_pk": str(item.get("game_pk") or ""), "game_date": item.get("game_date"), "home": item.get("home"), "away": item.get("away"), "scheduled": True,
            "run_trigger": _trigger(item.get("run_trigger") or candidate_trigger), "phase": item.get("phase"),
            "odds_matched": reason != "odds_event_unmatched", "prediction_generated": False,
            "market_fresh": False, "sharp_available": False, "execution_available": False,
            "fully_market_observable": False,
            "eligible": False, "rejection_reason": reason, "network_calls_added": 0,
        })
    return rows


def record(candidate_path: Path | str, ledger_path: Path | str = LEDGER) -> int:
    candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    existing = _read(ledger_path)
    index = {
        (_generation(r.get("model_generation")), str(r.get("target_date")), str(r.get("analyzed_at")), str(r.get("game_pk")), _trigger(r.get("run_trigger"))): r
        for r in existing
    }
    before = len(index)
    for row in rows_from_candidate(candidate):
        index[(_generation(row.get("model_generation")), str(row.get("target_date")), str(row.get("analyzed_at")), str(row.get("game_pk")), _trigger(row.get("run_trigger")))] = row
    rows = sorted(index.values(), key=lambda r: (_generation(r.get("model_generation")), str(r.get("target_date")), str(r.get("analyzed_at")), str(r.get("game_pk")), _trigger(r.get("run_trigger"))))
    _write(rows, ledger_path); return len(index) - before


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    canonical = _first_observations(rows)
    reasons = Counter(str(r.get("rejection_reason") or "") for r in canonical if not r.get("eligible"))
    raw_reasons = Counter(str(r.get("rejection_reason") or "") for r in rows if not r.get("eligible"))

    def counts(items: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "observations": len(items),
            "predicted": sum(bool(r.get("prediction_generated")) for r in items),
            "market_fresh": sum(bool(r.get("market_fresh")) for r in items),
            "sharp_available": sum(bool(r.get("sharp_available")) for r in items),
            "execution_available": sum(bool(r.get("execution_available")) for r in items),
            "fully_market_observable": sum(bool(r.get("fully_market_observable")) for r in items),
            "eligible": sum(bool(r.get("eligible")) for r in items),
        }

    raw = counts(rows); first = counts(canonical); denominator = first["observations"]
    return {
        "raw": {**raw, "rejection_reasons": dict(sorted(raw_reasons.items()))},
        "first_observation_unique_games": {
            **first,
            "prediction_coverage": first["predicted"] / denominator if denominator else 0.0,
            "market_fresh_coverage": first["market_fresh"] / denominator if denominator else 0.0,
            "sharp_coverage": first["sharp_available"] / denominator if denominator else 0.0,
            "execution_coverage": first["execution_available"] / denominator if denominator else 0.0,
            "fully_market_observable_coverage": first["fully_market_observable"] / denominator if denominator else 0.0,
            "eligible_coverage": first["eligible"] / denominator if denominator else 0.0,
            "rejection_reasons": dict(sorted(reasons.items())),
        },
    }


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    all_normalized = [dict(r, model_generation=_generation(r.get("model_generation")), run_trigger=_trigger(r.get("run_trigger")), phase=_phase(r.get("phase"))) for r in rows]
    generation_counts = Counter(str(r.get("model_generation")) for r in all_normalized)
    normalized = [r for r in all_normalized if r.get("model_generation") == MODEL_GENERATION]
    excluded = len(all_normalized) - len(normalized)
    overall = _summary(normalized)
    raw = overall["raw"]
    triggers = sorted({_trigger(r.get("run_trigger")) for r in normalized})
    phases = sorted({_phase(r.get("phase")) for r in normalized})
    by_trigger = {trigger: _summary([r for r in normalized if _trigger(r.get("run_trigger")) == trigger]) for trigger in triggers}
    by_phase = {phase: _summary([r for r in normalized if _phase(r.get("phase")) == phase]) for phase in phases}
    scheduled_final = by_trigger.get("SCHEDULED_FINAL", _summary([]))
    return {
        "schema": "pulsar-v14-coverage-report-v1", "network_calls": 0, "model_generation": MODEL_GENERATION,
        "excluded_other_generation_observations": excluded,
        "raw_observations_by_model_generation": dict(sorted(generation_counts.items())),
        # Compatibility fields now describe current-generation raw snapshot observations only.
        "observations": raw["observations"], "predicted": raw["predicted"], "sharp_available": raw["sharp_available"],
        "execution_available": raw["execution_available"], "eligible": raw["eligible"],
        "prediction_coverage": raw["predicted"] / raw["observations"] if raw["observations"] else 0.0,
        "sharp_coverage": raw["sharp_available"] / raw["observations"] if raw["observations"] else 0.0,
        "execution_coverage": raw["execution_available"] / raw["observations"] if raw["observations"] else 0.0,
        "rejection_reasons": raw["rejection_reasons"],
        "raw_snapshot_observations": overall["raw"],
        "first_observation_unique_games": overall["first_observation_unique_games"],
        "by_run_trigger": by_trigger,
        "by_phase": by_phase,
        "scheduled_final_trigger": scheduled_final,
        "canonical_policy": "within each current-generation reported cohort, first observed row per target_date x game_pk; later successful snapshots cannot replace an earlier failure",
        "semantics": {
            "eligible": "native prediction generated; this is analyzability, not betting authorization",
            "fully_market_observable": "prediction generated with verified-fresh canonical market, sharp market selections, and execution market selections",
            "execution_available_requires_freshness_verified_true": True,
            "scheduled_final_trigger_is_not_exact_final_phase_cohort": True,
            "current_model_generation_only": True,
            "legacy_missing_model_generation": LEGACY_GENERATION,
            "legacy_missing_run_trigger": LEGACY_TRIGGER,
            "audit_only": True,
            "can_authorize_bet": False,
        },
        "interpretation": "performance describes a selected analyzable universe; inspect current-generation first-observation unique-game and trigger/phase slices before assuming rejection missingness is random",
    }


def build_report(ledger_path: Path | str = LEDGER) -> dict[str, Any]:
    return report(_read(ledger_path))


def write_report(ledger_path: Path | str = LEDGER, output: Path | str = REPORT) -> dict[str, Any]:
    out = build_report(ledger_path); target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Pulsar coverage/rejection ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("record"); r.add_argument("--candidate", required=True); r.add_argument("--ledger", default=str(LEDGER))
    p = sub.add_parser("report"); p.add_argument("--ledger", default=str(LEDGER)); p.add_argument("--output", default=str(REPORT))
    args = parser.parse_args()
    if args.command == "record": out = {"recorded": record(args.candidate, args.ledger), "network_calls": 0}
    else: out = write_report(args.ledger, args.output)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__": main()
