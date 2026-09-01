from __future__ import annotations

"""Preregistered prospective ablation scoreboard for V14."""

import argparse
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .ablation_shadow import build_from_tracking_row
from .certification_timing import first_certification_snapshots
from .research_diagnostics import MARKETS, _num, _outcome, _paired_summary, binary_metrics, current_settled
from .research_registry import eligible_observation, registrations

DEFAULT_PREDICTIONS = Path("data/v14_predictions.jsonl")
DEFAULT_REGISTRY = Path("data/v14_experiment_registry.jsonl")
DEFAULT_OUTPUT = Path("data/v14_ablation_report.json")
EXPERIMENT_ID = "V14-ABLATION-01"


def _read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def build_report(
    rows: list[dict[str, Any]],
    *,
    registry_path: Path | str = DEFAULT_REGISTRY,
    experiment_id: str = EXPERIMENT_ID,
) -> dict[str, Any]:
    settled = current_settled(rows)
    current_policy_raw = [
        row for row in rows
        if row.get("settled")
        and row.get("model_generation") == MODEL_GENERATION
        and (row.get("probability_policy_id") or (row.get("calibration") or {}).get("probability_policy_id")) == PROBABILITY_POLICY_ID
    ]
    certification_cohort = first_certification_snapshots(current_policy_raw)
    registration = registrations(registry_path).get(experiment_id)
    eligible = [
        row for row in certification_cohort
        if registration and eligible_observation(experiment_id, str(row.get("analyzed_at") or ""), registry_path)
    ]

    scores: dict[str, dict[str, dict[str, Any]]] = {}
    skipped = 0
    for row in eligible:
        shadow = build_from_tracking_row(row)
        if shadow.get("status") != "READY":
            skipped += 1
            continue
        for variant, payload in (shadow.get("variants") or {}).items():
            variant_scores = scores.setdefault(str(variant), {})
            for market, selection in MARKETS.items():
                y = _outcome(row, market)
                champion = _num((row.get("probabilities") or {}).get(selection))
                candidate = _num((payload.get("probabilities") or {}).get(selection))
                if y is None or champion is None or candidate is None:
                    continue
                bucket = variant_scores.setdefault(market, {"items": [], "pairs": []})
                bucket["items"].append((candidate, y))
                bucket["pairs"].append((candidate, champion, y))

    rendered: dict[str, Any] = {}
    for variant, markets in scores.items():
        rendered[variant] = {}
        for market, payload in markets.items():
            rendered[variant][market] = {
                "variant": binary_metrics(payload["items"]),
                "paired_vs_champion": _paired_summary(
                    payload["pairs"], f"{experiment_id}|{variant}|{market}"
                ),
            }

    return {
        "schema": "pulsar-v14-ablation-report-v1",
        "role": "RESEARCH_ONLY",
        "champion_impact": False,
        "experiment_id": experiment_id,
        "registered": registration is not None,
        "registration_timestamp": registration.get("registered_at") if registration else None,
        "prospective_only_for_promotion": True,
        "settled_current_policy_games": len(settled),
        "scheduled_final_certification_games": len(certification_cohort),
        "prospective_eligible_rows": len(eligible),
        "skipped_unavailable_rows": skipped,
        "variants": rendered,
        "interpretation": (
            "Only the first objective SCHEDULED_FINAL certification snapshot per game whose "
            "analyzed_at is on/after the sealed experiment registration enters paired ablation "
            "evidence. Earlier/manual rows are excluded even when their pregame features are reconstructible."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score preregistered V14 probability ablations")
    parser.add_argument("--predictions", default=str(DEFAULT_PREDICTIONS))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    report = build_report(_read_jsonl(args.predictions), registry_path=args.registry)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(target),
        "registered": report["registered"],
        "prospective_eligible_rows": report["prospective_eligible_rows"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
