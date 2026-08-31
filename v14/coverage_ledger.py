from __future__ import annotations

"""Persist why each scheduled game was or was not analyzable.

Consumes the already-built native candidate only; it never calls MLB/Odds APIs.
This makes eligibility/coverage selection bias measurable instead of invisible.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

LEDGER = Path("data/v14_coverage_ledger.jsonl")
REPORT = Path("data/v14_coverage_report.json")
SCHEMA = "pulsar-v14-coverage-record-v1"


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


def rows_from_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    target_date = str(candidate.get("target_date") or "")
    analyzed_at = str(candidate.get("analyzed_at") or "")
    results = candidate.get("results") or []
    skipped = candidate.get("skipped") or []
    rows: list[dict[str, Any]] = []
    for result in results:
        game_pk = str(result.get("game_pk") or "")
        market = result.get("market_snapshot") or {}; sharp = result.get("sharp_market") or {}; execution = result.get("execution_market") or {}
        rows.append({
            "schema": SCHEMA, "target_date": target_date, "analyzed_at": analyzed_at, "game_pk": game_pk,
            "home": result.get("home"), "away": result.get("away"), "scheduled": True,
            "odds_matched": True, "prediction_generated": True,
            "market_fresh": market.get("freshness_verified") is True,
            "sharp_available": sharp.get("freshness_verified") is True and bool(sharp.get("selections")),
            "execution_available": execution.get("freshness_verified") is not False and bool(execution.get("selections")),
            "eligible": True, "rejection_reason": None, "phase": result.get("phase"), "network_calls_added": 0,
        })
    for item in skipped:
        reason = str(item.get("reason") or "unknown")
        rows.append({
            "schema": SCHEMA, "target_date": target_date, "analyzed_at": analyzed_at,
            "game_pk": str(item.get("game_pk") or ""), "home": None, "away": None, "scheduled": True,
            "odds_matched": reason != "odds_event_unmatched", "prediction_generated": False,
            "market_fresh": False, "sharp_available": False, "execution_available": False,
            "eligible": False, "rejection_reason": reason, "phase": None, "network_calls_added": 0,
        })
    return rows


def record(candidate_path: Path | str, ledger_path: Path | str = LEDGER) -> int:
    candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    existing = _read(ledger_path); index = {(str(r.get("target_date")), str(r.get("analyzed_at")), str(r.get("game_pk"))): r for r in existing}
    before = len(index)
    for row in rows_from_candidate(candidate):
        index[(str(row.get("target_date")), str(row.get("analyzed_at")), str(row.get("game_pk")))] = row
    rows = sorted(index.values(), key=lambda r: (str(r.get("target_date")), str(r.get("analyzed_at")), str(r.get("game_pk"))))
    _write(rows, ledger_path); return len(index) - before


def build_report(ledger_path: Path | str = LEDGER) -> dict[str, Any]:
    rows = _read(ledger_path); reasons = Counter(str(r.get("rejection_reason") or "") for r in rows if not r.get("eligible"))
    scheduled = len(rows); predicted = sum(bool(r.get("prediction_generated")) for r in rows); sharp = sum(bool(r.get("sharp_available")) for r in rows)
    execution = sum(bool(r.get("execution_available")) for r in rows); eligible = sum(bool(r.get("eligible")) for r in rows)
    return {
        "schema": "pulsar-v14-coverage-report-v1", "network_calls": 0,
        "observations": scheduled, "predicted": predicted, "sharp_available": sharp,
        "execution_available": execution, "eligible": eligible,
        "prediction_coverage": predicted / scheduled if scheduled else 0.0,
        "sharp_coverage": sharp / scheduled if scheduled else 0.0,
        "execution_coverage": execution / scheduled if scheduled else 0.0,
        "rejection_reasons": dict(sorted(reasons.items())),
        "interpretation": "performance describes the Pulsar-eligible universe; rejection missingness must not be assumed random",
    }


def write_report(ledger_path: Path | str = LEDGER, output: Path | str = REPORT) -> dict[str, Any]:
    report = build_report(ledger_path); target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return report


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
