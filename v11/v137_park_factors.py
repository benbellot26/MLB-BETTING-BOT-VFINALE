from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import predictive_v124 as v124
from .v124_statcast_provider import _TableParser, _norm_header
from .v137_free_data import COHORT

OUT = Path("data/v137_park_factors.json")
REPORT = Path("data/v137_park_factors_report.json")
SOURCE_URL = "https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"


def _num(value: Any) -> float | None:
    try:
        out = float(str(value).replace(",", "").strip())
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _parse_park_table(html: str) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(html or "")
    for table in parser.tables:
        if not table:
            continue
        header = [text for tag, text in table[0] if tag == "th"]
        if not header:
            header = [text for _, text in table[0]]
        normalized = [_norm_header(x) for x in header]
        required = {"venue", "year", "parkfactor"}
        if not required.issubset(set(normalized)):
            continue
        out: list[dict[str, Any]] = []
        for raw in table[1:]:
            vals = [text for _, text in raw]
            if len(vals) < len(header):
                continue
            row = {normalized[i]: vals[i] for i in range(min(len(normalized), len(vals)))}
            venue = str(row.get("venue") or "").replace("Image", "").strip()
            team = str(row.get("team") or "").replace("Image", "").strip()
            park = _num(row.get("parkfactor"))
            if not venue or park is None:
                continue
            item = {
                "team": team or None,
                "venue": venue,
                "year_label": row.get("year"),
                "park_factor_index": park,
                "woba_contact_index": _num(row.get("wobacon")),
                "xwoba_contact_index": _num(row.get("xwobacon")),
                "hard_hit_index": _num(row.get("hardhit")),
                "runs_index": _num(row.get("r")),
                "hr_index": _num(row.get("hr")),
                "pa": _num(row.get("pa")),
            }
            out.append(item)
        if out:
            return out
    return []


def fetch_prior_factors(
    target_season: int,
    bat_side: str = "",
    fetch_text: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Fetch a three-season Savant park-factor window ending before target season.

    The target season is never included. This is intentionally less adaptive
    than an in-season park factor, but it is leakage-safe for historical
    research and known in full before Opening Day of the target season.
    """
    target = int(target_season)
    source_end = target - 1
    side = str(bat_side or "").upper()
    if side not in {"", "L", "R"}:
        raise ValueError("bat_side must be '', 'L', or 'R'")
    fetch_text = fetch_text or v124._http_text
    params = {
        "batSide": side,
        "condition": "All",
        "parks": "mlb",
        "rolling": 3,
        "stat": "index_wOBA",
        "type": "year",
        "year": source_end,
    }
    html = fetch_text(SOURCE_URL, params, timeout=30)
    rows = _parse_park_table(html or "")
    return {
        "schema": "v13-7-prior-park-factor-v1",
        "cohort": COHORT,
        "target_season": target,
        "source_window_end_season": source_end,
        "source_window_years": [source_end - 2, source_end - 1, source_end],
        "bat_side": side or "ALL",
        "point_in_time": True,
        "native_live": False,
        "promotion_eligible": False,
        "provider": "Baseball Savant Statcast Park Factors",
        "source_url": SOURCE_URL,
        "rows": rows,
        "venue_count": len(rows),
        "policy": "three completed seasons ending before target season; target-season results excluded",
    }


def collect(start_season: int, end_season: int) -> tuple[dict[str, Any], dict[str, Any]]:
    start, end = int(start_season), int(end_season)
    if end < start:
        raise ValueError("end season before start season")
    seasons: dict[str, Any] = {}
    failures = []
    for season in range(start, end + 1):
        side_payloads = {}
        for side in ("", "L", "R"):
            label = side or "ALL"
            try:
                side_payloads[label] = fetch_prior_factors(season, side)
            except Exception as exc:
                side_payloads[label] = {
                    "schema": "v13-7-prior-park-factor-v1",
                    "target_season": season,
                    "bat_side": label,
                    "point_in_time": True,
                    "rows": [],
                    "venue_count": 0,
                    "error": f"{type(exc).__name__}:{exc}",
                }
                failures.append({"season": season, "bat_side": label, "error": type(exc).__name__})
        seasons[str(season)] = side_payloads
    artifact = {
        "schema": "v13-7-prior-park-factors-store-v1",
        "cohort": COHORT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "point_in_time_policy": True,
        "native_live": False,
        "promotion_eligible": False,
        "seasons": seasons,
    }
    report = {
        "schema": "v13-7-prior-park-factors-report-v1",
        "start_season": start,
        "end_season": end,
        "season_count": len(seasons),
        "requests_expected": len(seasons) * 3,
        "failures": failures,
        "failed_requests": len(failures),
        "venue_counts": {
            season: {side: int(payload.get("venue_count") or 0) for side, payload in sides.items()}
            for season, sides in seasons.items()
        },
        "promotion_eligible": False,
    }
    return artifact, report


def load(path: Path = OUT) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def venue_prior(artifact: dict[str, Any], target_season: int, venue: str) -> dict[str, Any]:
    sides = (((artifact or {}).get("seasons") or {}).get(str(int(target_season))) or {})
    result = {
        "available": False,
        "target_season": int(target_season),
        "venue": venue,
        "point_in_time": True,
        "provider": "Baseball Savant Statcast Park Factors",
    }
    key = _norm(venue)
    for side in ("ALL", "L", "R"):
        payload = sides.get(side) or {}
        row = next((r for r in payload.get("rows") or [] if _norm(r.get("venue")) == key), None)
        if row:
            result[side.lower()] = row
            result["source_window_end_season"] = payload.get("source_window_end_season")
    result["available"] = any(k in result for k in ("all", "l", "r"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect leakage-safe prior-season Statcast park factors")
    parser.add_argument("--start-season", type=int, default=2021)
    parser.add_argument("--end-season", type=int, default=date.today().year)
    args = parser.parse_args()
    artifact, report = collect(args.start_season, args.end_season)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
