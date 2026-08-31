from __future__ import annotations

"""Prospective cohort accounting tied to preregistered experiments.

Only observations captured at or after an experiment registration timestamp are
eligible for that experiment's promotion evidence. This module is API-free and
never alters champion predictions.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .research_registry import REGISTRY, registrations

PREDICTIONS = Path("data/v14_predictions.jsonl")
OUTPUT = Path("data/v14_prospective_cohorts.json")


def _dt(value: Any) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if out.tzinfo is None: out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def _read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists(): return []
    out: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row = json.loads(line)
        except Exception: continue
        if isinstance(row, dict): out.append(row)
    return out


def _strictly_pregame(row: dict[str, Any]) -> bool:
    analyzed = _dt(row.get("analyzed_at")); game = _dt(row.get("game_date"))
    return bool(analyzed and game and analyzed < game)


def build(predictions: Path | str = PREDICTIONS, registry: Path | str = REGISTRY) -> dict[str, Any]:
    rows = [r for r in _read_jsonl(predictions) if _strictly_pregame(r)]
    experiments: dict[str, Any] = {}
    for experiment_id, registration in registrations(registry).items():
        start = _dt(registration.get("registered_at")); eligible: list[dict[str, Any]] = []
        if start is not None:
            for row in rows:
                analyzed = _dt(row.get("analyzed_at"))
                if analyzed is not None and analyzed >= start:
                    eligible.append(row)
        by_phase = {phase: sum(str(r.get("phase") or "").upper() == phase for r in eligible) for phase in ("EARLY", "LATE", "FINAL")}
        experiments[experiment_id] = {
            "registered_at": registration.get("registered_at"),
            "code_commit_sha": registration.get("code_commit_sha"),
            "primary_metric": registration.get("primary_metric"),
            "success_rule": registration.get("success_rule"),
            "prospective_rows": len(eligible),
            "prospective_games": len({str(r.get("game_pk") or "") for r in eligible if r.get("game_pk")}),
            "settled_games": len({str(r.get("game_pk") or "") for r in eligible if r.get("settled") and r.get("game_pk")}),
            "phase_rows": by_phase,
            "first_observation_at": min((str(r.get("analyzed_at")) for r in eligible), default=None),
            "latest_observation_at": max((str(r.get("analyzed_at")) for r in eligible), default=None),
            "promotion_evidence_rule": "only observations at/after registered_at may count",
        }
    return {
        "schema": "pulsar-v14-prospective-cohort-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network_calls": 0,
        "historical_roles": {
            "2021-2024": "DEVELOPMENT",
            "2025": "VALIDATION_REUSED_NOT_BLIND",
            "2026": "ROLLING_AUDIT_NOT_FROZEN",
            "post_registration": "SEALED_PROSPECTIVE_PROMOTION_EVIDENCE",
        },
        "experiments": experiments,
    }


def write(predictions: Path | str = PREDICTIONS, registry: Path | str = REGISTRY, output: Path | str = OUTPUT) -> dict[str, Any]:
    report = build(predictions, registry); target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sealed prospective cohort accounting")
    parser.add_argument("--predictions", default=str(PREDICTIONS)); parser.add_argument("--registry", default=str(REGISTRY)); parser.add_argument("--output", default=str(OUTPUT)); args = parser.parse_args()
    out = write(args.predictions, args.registry, args.output)
    print(json.dumps({"experiments": len(out["experiments"]), "network_calls": 0, "historical_2026": "ROLLING_AUDIT_NOT_FROZEN"}, sort_keys=True))


if __name__ == "__main__": main()
