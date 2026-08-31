from __future__ import annotations

"""Prospective cohort accounting tied to preregistered experiments.

Promotion-capable evidence is intentionally narrower than generic post-registration
research. Only the first current-generation/current-policy SCHEDULED_FINAL snapshot
per game inside the shared certification timing window may enter the sealed
promotion cohort. Broader post-registration observations remain descriptive only.
This module is API-free and never alters champion predictions.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .certification_timing import CERTIFICATION_PHASE, CERTIFICATION_RUN_TRIGGER, first_certification_snapshots
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


def _row_policy(row: dict[str, Any]) -> str | None:
    direct = row.get("probability_policy_id")
    if direct: return str(direct)
    nested = (row.get("calibration") or {}).get("probability_policy_id")
    return str(nested) if nested else None


def _current_policy(row: dict[str, Any]) -> bool:
    return row.get("model_generation") == MODEL_GENERATION and _row_policy(row) == PROBABILITY_POLICY_ID


def _post_registration(rows: list[dict[str, Any]], start: datetime | None) -> list[dict[str, Any]]:
    if start is None: return []
    out=[]
    for row in rows:
        analyzed=_dt(row.get("analyzed_at"))
        if analyzed is not None and analyzed >= start: out.append(row)
    return out


def build(predictions: Path | str = PREDICTIONS, registry: Path | str = REGISTRY) -> dict[str, Any]:
    all_rows = _read_jsonl(predictions)
    pregame_rows = [r for r in all_rows if _strictly_pregame(r)]
    current_rows = [r for r in pregame_rows if _current_policy(r)]
    certification_rows = first_certification_snapshots(current_rows)
    experiments: dict[str, Any] = {}
    for experiment_id, registration in registrations(registry).items():
        start = _dt(registration.get("registered_at"))
        descriptive = _post_registration(current_rows, start)
        eligible = _post_registration(certification_rows, start)
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
            "descriptive_post_registration_rows": len(descriptive),
            "descriptive_post_registration_games": len({str(r.get("game_pk") or "") for r in descriptive if r.get("game_pk")}),
            "promotion_evidence_rule": "post-registration + exact current generation/policy + first observed SCHEDULED_FINAL snapshot per game inside shared certification window",
            "promotion_cohort_policy": "FIRST_SCHEDULED_FINAL_CURRENT_POLICY_PER_GAME",
            "promotion_phase": CERTIFICATION_PHASE,
            "promotion_run_trigger": CERTIFICATION_RUN_TRIGGER,
            "model_generation": MODEL_GENERATION,
            "probability_policy_id": PROBABILITY_POLICY_ID,
        }
    return {
        "schema": "pulsar-v14-prospective-cohort-report-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network_calls": 0,
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "promotion_phase": CERTIFICATION_PHASE,
        "promotion_run_trigger": CERTIFICATION_RUN_TRIGGER,
        "promotion_cohort_policy": "FIRST_SCHEDULED_FINAL_CURRENT_POLICY_PER_GAME",
        "input_rows_total": len(all_rows),
        "strictly_pregame_rows": len(pregame_rows),
        "strictly_pregame_current_policy_rows": len(current_rows),
        "certification_rows_total": len(certification_rows),
        "historical_roles": {
            "2021-2024": "DEVELOPMENT",
            "2025": "VALIDATION_REUSED_NOT_BLIND",
            "2026": "ROLLING_AUDIT_NOT_FROZEN",
            "generic_post_registration": "DESCRIPTIVE_ONLY",
            "post_registration_scheduled_final": "SEALED_PROSPECTIVE_PROMOTION_EVIDENCE",
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
    print(json.dumps({"experiments": len(out["experiments"]), "network_calls": 0, "historical_2026": "ROLLING_AUDIT_NOT_FROZEN", "promotion_cohort_policy": out["promotion_cohort_policy"]}, sort_keys=True))


if __name__ == "__main__": main()
