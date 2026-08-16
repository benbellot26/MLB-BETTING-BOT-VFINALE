from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .v13_historical_prior import build as build_prior, _joint_nll

EXACT_FILE = Path("data/v13_historical_backfill.jsonl")
REPORT_FILE = Path("data/v13_distribution_transfer_report.json")


def _load_exact_latest() -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    with EXACT_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row=json.loads(line)
            gid=str(row.get("game_pk") or "")
            if not gid or row.get("home_score") is None or row.get("away_score") is None:
                continue
            cur=best.get(gid)
            if cur is None or str(row.get("analyzed_at") or "") > str(cur.get("analyzed_at") or ""):
                best[gid]=row
    return sorted(best.values(), key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or "")))


def main() -> None:
    prior=build_prior()
    dist=prior.get("distribution") or {}
    cand=dist.get("candidate") or {}
    d=float(cand.get("dispersion") or 7.5)
    s=float(cand.get("environment_sigma") or .08)
    rows=_load_exact_latest()
    default=_joint_nll(rows,7.5,.08)
    candidate=_joint_nll(rows,d,s)
    gain=default-candidate
    report={
        "schema":"v13-distribution-transfer-v1",
        "exact_replay_games":len(rows),
        "selection":"latest exact pregame HTTP replay per game",
        "candidate":{"dispersion":d,"environment_sigma":s},
        "default_nll":default,"candidate_nll":candidate,"nll_gain":gain,
        "historical_outer_holdout_validated":bool(dist.get("historically_validated")),
        "exact_replay_support":bool(len(rows)>=20 and math.isfinite(gain) and gain>=0.0),
        "production_activation_allowed":bool(dist.get("historically_validated") and len(rows)>=20 and math.isfinite(gain) and gain>=0.0),
        "scope":"FINAL score-distribution prior only; calibration remains independent and historical ML/RL calibrators remain inactive.",
    }
    REPORT_FILE.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == "__main__": main()
