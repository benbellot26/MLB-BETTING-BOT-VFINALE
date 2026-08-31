from __future__ import annotations

"""Primary/secondary sharp benchmark suite using persisted snapshots only.

Primary benchmark: Pinnacle no-vig fair probability when present in the existing
sharp contributors. Secondary benchmark: Pulsar's existing multi-book sharp
consensus. Exchange proxies never become the primary benchmark here.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .paired_inference import block_bootstrap_mean_ci, bootstrap_mean_ci, paired_score_differences
from .snapshot_policy import select_canonical

PREDICTIONS = Path("data/v14_predictions.jsonl")
OUTPUT = Path("data/v14_sharp_benchmark_report.json")
MARKETS = {
    "ML": "home_ml",
    "RL_HOME_-1.5": "home_minus_1_5",
    "RL_AWAY_-1.5": "away_minus_1_5",
    "TOTAL_OVER": "over",
}


def _num(value: Any) -> float | None:
    try: out = float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _read(path: Path | str = PREDICTIONS) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists(): return []
    out: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row = json.loads(line)
        except Exception: continue
        if isinstance(row, dict): out.append(row)
    return out


def pinnacle_probability(row: dict[str, Any], selection: str) -> float | None:
    sharp = row.get("sharp_market") or {}; selected = ((sharp.get("selections") or {}).get(selection) or {})
    for contributor in selected.get("contributors") or []:
        if str(contributor.get("bookmaker") or "").lower() != "pinnacle": continue
        if str(contributor.get("source_type") or "").upper() != "SPORTSBOOK": continue
        p = _num(contributor.get("fair_probability"))
        if p is not None and 0 < p < 1: return p
    return None


def consensus_probability(row: dict[str, Any], selection: str) -> float | None:
    p = _num(((((row.get("sharp_market") or {}).get("selections") or {}).get(selection) or {}).get("fair_probability")))
    return p if p is not None and 0 < p < 1 else None


def _outcome(row: dict[str, Any], market: str) -> int | None:
    if not row.get("settled"): return None
    hs = _num(row.get("home_score")); aws = _num(row.get("away_score"))
    if hs is None or aws is None: return None
    if market == "ML": return int(hs > aws)
    if market == "RL_HOME_-1.5": return int(hs - aws >= 2)
    if market == "RL_AWAY_-1.5": return int(aws - hs >= 2)
    line = _num(row.get("total_line"))
    if line is None or abs((hs + aws) - line) < 1e-9: return None
    return int(hs + aws > line)


def _logloss(p: float, y: int) -> float:
    q = max(1e-12, min(1 - 1e-12, float(p)))
    return -(y * math.log(q) + (1 - y) * math.log(1 - q))


def _metrics(items: list[tuple[float, int]]) -> dict[str, Any]:
    if not items: return {"n": 0, "brier": None, "logloss": None}
    return {
        "n": len(items),
        "brier": sum((p - y) ** 2 for p, y in items) / len(items),
        "logloss": sum(_logloss(p, y) for p, y in items) / len(items),
    }


def _market_report(rows: list[dict[str, Any]], market: str) -> dict[str, Any]:
    selection = MARKETS[market]; primary: list[tuple[float, int]] = []; secondary: list[tuple[float, int]] = []
    paired_primary: list[tuple[float, float, int]] = []; paired_secondary: list[tuple[float, float, int]] = []
    dated_primary: list[tuple[str, float]] = []; dated_secondary: list[tuple[str, float]] = []
    for row in rows:
        y = _outcome(row, market); model = _num((row.get("probabilities") or {}).get(selection))
        if y is None or model is None: continue
        p1 = pinnacle_probability(row, selection); p2 = consensus_probability(row, selection)
        if p1 is not None:
            primary.append((p1, y)); paired_primary.append((model, p1, y))
            diff = paired_score_differences([(model, p1, y)])["brier_gain"][0]; dated_primary.append((str(row.get("target_date") or ""), diff))
        if p2 is not None:
            secondary.append((p2, y)); paired_secondary.append((model, p2, y))
            diff = paired_score_differences([(model, p2, y)])["brier_gain"][0]; dated_secondary.append((str(row.get("target_date") or ""), diff))
    def inference(items: list[tuple[float, float, int]], dated: list[tuple[str, float]], label: str) -> dict[str, Any]:
        diffs = paired_score_differences(items)
        return {
            "paired_n": len(items),
            "brier_gain": bootstrap_mean_ci(diffs["brier_gain"], label=f"{label}:brier"),
            "logloss_gain": bootstrap_mean_ci(diffs["logloss_gain"], label=f"{label}:logloss"),
            "calendar_block_brier_gain": block_bootstrap_mean_ci(dated, label=f"{label}:block-brier"),
        }
    return {
        "primary_pinnacle_no_vig": _metrics(primary),
        "secondary_consensus": _metrics(secondary),
        "model_vs_primary": inference(paired_primary, dated_primary, f"{market}:pinnacle"),
        "model_vs_secondary": inference(paired_secondary, dated_secondary, f"{market}:consensus"),
    }


def build(path: Path | str = PREDICTIONS) -> dict[str, Any]:
    rows = [r for r in _read(path) if r.get("settled")]
    selected = select_canonical(rows)
    phases: dict[str, Any] = {}
    for phase in ("EARLY", "LATE", "FINAL"):
        phase_rows = [by_phase[phase] for by_phase in selected.values() if phase in by_phase]
        phases[phase] = {"games": len(phase_rows), "markets": {m: _market_report(phase_rows, m) for m in MARKETS}}
    return {
        "schema": "pulsar-v14-sharp-benchmark-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network_calls": 0,
        "primary_benchmark": "PINNACLE_NO_VIG",
        "secondary_benchmark": "WEIGHTED_SHARP_CONSENSUS",
        "exchange_policy": "exchange proxies remain secondary; no raw exchange price can serve as primary benchmark",
        "snapshot_policy": "canonical observed EARLY/LATE/FINAL windows; no cross-phase mixing",
        "bootstrap_policy": "deterministic paired nonparametric bootstrap; calendar-block diagnostic",
        "phases": phases,
    }


def write(predictions: Path | str = PREDICTIONS, output: Path | str = OUTPUT) -> dict[str, Any]:
    report = build(predictions); target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build zero-API Pinnacle/consensus sharp benchmark report")
    parser.add_argument("--predictions", default=str(PREDICTIONS)); parser.add_argument("--output", default=str(OUTPUT)); args = parser.parse_args()
    report = write(args.predictions, args.output)
    print(json.dumps({"schema": report["schema"], "primary": report["primary_benchmark"], "network_calls": 0}, sort_keys=True))


if __name__ == "__main__": main()
