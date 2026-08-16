from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import calibration_baseball_v13 as calibration
from . import journal

STRICT_GLOBAL_N = 600
STRICT_MARKET_N = 400
STRICT_PHASE_MARKET_N = 300
EXACT_BACKFILL = Path("data/v13_historical_backfill.jsonl")


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _load_exact_backfill(path: Path = EXACT_BACKFILL) -> list[dict[str,Any]]:
    if not path.exists():
        return []
    out=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row=json.loads(line)
        except Exception:
            continue
        if not isinstance(row,dict):
            continue
        if not str(row.get("schema") or "").startswith("v13-point-in-time-backfill"):
            continue
        if row.get("point_in_time") is not True or row.get("features_from_postgame") is True:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        row=dict(row)
        row["v13_evidence_tier"]="A_EXACT_REPLAY"
        out.append(row)
    return out


def _canonical_options(row: dict[str,Any]) -> list[dict[str,Any]]:
    """Keep at most one independent calibration target per market and game phase."""
    options = [o for o in (row.get("options") or [])
               if o.get("result") in {"WIN","LOSS"}
               and (o.get("p_baseball_raw") is not None or o.get("p_learned") is not None)]
    home = _norm(row.get("home"))
    out: list[dict[str,Any]] = []
    for market in ("ML","RUNLINE","TOTAL"):
        candidates = [o for o in options if str(o.get("market") or "").upper() == market]
        if not candidates:
            continue
        marked = [o for o in candidates if o.get("is_canonical_line")]
        pool = marked or candidates
        if market == "ML":
            chosen = next((o for o in pool if _norm(o.get("name")) == home), pool[0])
        elif market == "RUNLINE":
            homes = [o for o in pool if _norm(o.get("name")) == home]
            chosen = min(homes or pool, key=lambda o: abs(abs(float(o.get("point") or 0))-1.5))
        else:
            overs = [o for o in pool if str(o.get("name") or "").lower() == "over"]
            chosen = (overs or pool)[0]
        out.append(dict(chosen))
    return out


def eligible_probability_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Use only genuine pregame probability observations.

    Compatibility is based on the probability contract, not software version.
    Exact V13 replay-backfill rows are tier-A evidence. Legacy rows are accepted
    only when they independently satisfy the same pregame/settled/baseball-only
    contract. No p_effective/p_model market-blended value is accepted.
    """
    best: dict[tuple[str,str], tuple[str,dict[str,Any]]] = {}
    for row in rows:
        analyzed = _dt(row.get("analyzed_at"))
        game_time = _dt(row.get("game_date"))
        if analyzed is None or game_time is None or analyzed >= game_time:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        if row.get("features_from_postgame") is True:
            continue
        canonical = _canonical_options(row)
        if not canonical:
            continue
        phase = str(row.get("phase") or "EARLY").upper()
        key = (str(row.get("game_pk") or ""), phase)
        rank = str(row.get("analyzed_at") or "")
        clone = dict(row)
        clone["options"] = canonical
        if key not in best or rank > best[key][0]:
            best[key] = (rank,clone)
    return sorted((x[1] for x in best.values()), key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or ""), str(r.get("phase") or "")))


def _strict_required_n(key: str) -> int:
    if key == "GLOBAL":
        return STRICT_GLOBAL_N
    if key.startswith("PHASE:"):
        return STRICT_PHASE_MARKET_N
    if key.startswith("MARKET:"):
        return STRICT_MARKET_N
    return STRICT_GLOBAL_N


def enforce_strict_activation(model: dict[str,Any]) -> dict[str,Any]:
    for key, cal in (model.get("calibrators") or {}).items():
        required = _strict_required_n(str(key))
        cal["strict_required_n"] = required
        cal["strict_volume_ready"] = int(cal.get("n") or 0) >= required
        if cal.get("active") and not cal["strict_volume_ready"]:
            cal["internal_candidate_active"] = True
            cal["active"] = False
            cal["status"] = "COLLECTING_STRICT_V13_VOLUME"
    model["strict_activation_floors"] = {
        "global":STRICT_GLOBAL_N,
        "market":STRICT_MARKET_N,
        "phase_market":STRICT_PHASE_MARKET_N,
    }
    return model


def build() -> dict[str,Any]:
    live = journal.load_rows()
    exact = _load_exact_backfill()
    source = list(live) + list(exact)
    rows = eligible_probability_rows(source)
    model = enforce_strict_activation(calibration.build_model(rows))
    model["training_policy"] = {
        "software_version_required": False,
        "pregame_required": True,
        "settled_result_required": True,
        "accepted_probability_fields": ["p_baseball_raw","p_learned"],
        "forbidden_probability_fields_as_baseball_evidence": ["p_effective","p_model","p_market","p_posterior"],
        "canonical_row": "latest pregame row per game_pk and phase",
        "independent_target_policy": "max one canonical side per market/game/phase",
        "alternate_lines_trainable_for_calibration": False,
        "strict_volume_floor_after_internal_holdout": True,
        "exact_v13_replay_backfill_allowed": True,
        "legacy_reconstructed_1801_allowed_as_native_calibration": False,
    }
    model["source_rows_total"] = len(source)
    model["source_rows_live"] = len(live)
    model["source_rows_exact_replay"] = len(exact)
    model["eligible_rows"] = len(rows)
    model["eligible_games"] = len({str(r.get("game_pk")) for r in rows})
    model["exact_replay_games"] = len({str(r.get("game_pk")) for r in exact})
    return model


def main():
    parser = argparse.ArgumentParser(description="Train V13 baseball-only probability calibration")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    model = build()
    if not args.dry_run:
        calibration.save_model(model)
    print(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
