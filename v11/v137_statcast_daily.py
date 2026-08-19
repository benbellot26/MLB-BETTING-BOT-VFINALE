from __future__ import annotations

import argparse
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .v137_free_data import (
    COHORT,
    STATCAST_MAX_CHUNK_DAYS,
    aggregate_statcast_priors,
    dedupe_statcast_rows,
    fetch_statcast_rows_adaptive,
)

OUT = Path("data/v137_statcast_priors_latest.json.gz")
REPORT = Path("data/v137_statcast_priors_report.json")


def _chunks(start: date, end: date):
    current = start
    while current <= end:
        stop = min(end, current + timedelta(days=STATCAST_MAX_CHUNK_DAYS - 1))
        yield current, stop
        current = stop + timedelta(days=1)


def collect(cutoff_day: str, lookback_days: int = 45) -> tuple[dict[str, Any], dict[str, Any]]:
    cutoff = date.fromisoformat(cutoff_day)
    lookback_days = max(7, min(180, int(lookback_days)))
    start = cutoff - timedelta(days=lookback_days)
    end = cutoff - timedelta(days=1)
    all_rows: list[dict[str, Any]] = []
    chunk_reports = []
    total_cap_hits = total_splits = total_requests = 0
    unresolved_truncation = False
    for a, b in _chunks(start, end):
        try:
            rows, diag = fetch_statcast_rows_adaptive(a.isoformat(), b.isoformat(), season=cutoff.year)
            all_rows.extend(rows)
            total_cap_hits += int(diag.get("cap_hits") or 0)
            total_splits += int(diag.get("splits") or 0)
            total_requests += int(diag.get("requests_made") or 0)
            unresolved_truncation = unresolved_truncation or bool(diag.get("unresolved_truncation"))
            chunk_reports.append(
                {
                    "start": a.isoformat(),
                    "end": b.isoformat(),
                    "rows": len(rows),
                    "status": "OK",
                    "cap_hits": int(diag.get("cap_hits") or 0),
                    "splits": int(diag.get("splits") or 0),
                    "requests": diag.get("requests") or [],
                }
            )
        except Exception as exc:
            if "row_cap" in str(exc):
                unresolved_truncation = True
            chunk_reports.append(
                {
                    "start": a.isoformat(),
                    "end": b.isoformat(),
                    "rows": 0,
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
    all_rows = dedupe_statcast_rows(all_rows)
    priors = aggregate_statcast_priors(all_rows, cutoff_day)
    priors.update(
        {
            "lookback_start": start.isoformat(),
            "lookback_end": end.isoformat(),
            "lookback_days": lookback_days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider_integrity": {
                "cap_hits": total_cap_hits,
                "adaptive_splits": total_splits,
                "requests_made": total_requests,
                "unresolved_truncation": unresolved_truncation,
            },
        }
    )
    report = {
        "schema": "v13-7-statcast-priors-report-v2",
        "cohort": COHORT,
        "cutoff_day": cutoff_day,
        "lookback_days": lookback_days,
        "chunk_days": STATCAST_MAX_CHUNK_DAYS,
        "chunks": chunk_reports,
        "chunks_ok": sum(c["status"] == "OK" for c in chunk_reports),
        "chunks_failed": sum(c["status"] != "OK" for c in chunk_reports),
        "raw_rows": len(all_rows),
        "hitter_ids": len(priors.get("hitters") or {}),
        "pitcher_ids": len(priors.get("pitchers") or {}),
        "cap_hits": total_cap_hits,
        "adaptive_splits": total_splits,
        "requests_made": total_requests,
        "unresolved_truncation": unresolved_truncation,
        "stable_id_only": True,
        "point_in_time": True,
        "promotion_eligible": False,
        "claim": "free ID-first Statcast priors; any observed server row-cap is split and unresolved truncation fails closed",
    }
    return priors, report


def _write_gzip_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect free stable-ID Statcast priors")
    parser.add_argument("--cutoff", default=date.today().isoformat(), help="features use game_date strictly before this day")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--archive", action="store_true", help="also keep a dated gzip under data/v137/")
    args = parser.parse_args()
    priors, report = collect(args.cutoff, args.lookback_days)
    if report.get("unresolved_truncation"):
        raise SystemExit("Statcast provider integrity failure: unresolved row-cap truncation")
    if int(report.get("chunks_failed") or 0):
        raise SystemExit(f"Statcast provider integrity failure: {report['chunks_failed']} chunk(s) failed")
    _write_gzip_json(OUT, priors)
    if args.archive:
        _write_gzip_json(Path("data/v137") / f"statcast_priors_{args.cutoff}.json.gz", priors)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
