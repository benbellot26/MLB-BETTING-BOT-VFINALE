from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from . import calibration_baseball_v13 as calibration
from . import journal


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _canonical_options(row: dict[str,Any]) -> list[dict[str,Any]]:
    """Keep at most one independent calibration target per market and game phase.

    Complementary sides and alternate lines carry the same game outcome and must
    not inflate calibration sample size. Prefer the canonical/main line and a
    deterministic side: home for ML/RUNLINE and Over for TOTAL.
    """
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
    Legacy V12.3 rows are migratable for calibration when they carry p_learned,
    because p_learned is the baseball-only probability saved before sharp blend.
    No legacy p_effective/p_model value is accepted as baseball-only evidence.
    """
    best: dict[tuple[str,str], tuple[str,dict[str,Any]]] = {}
    for row in rows:
        analyzed = _dt(row.get("analyzed_at"))
        game_time = _dt(row.get("game_date"))
        if analyzed is None or game_time is None or analyzed >= game_time:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
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


def build() -> dict[str,Any]:
    source = journal.load_rows()
    rows = eligible_probability_rows(source)
    model = calibration.build_model(rows)
    model["training_policy"] = {
        "software_version_required": False,
        "pregame_required": True,
        "settled_result_required": True,
        "accepted_probability_fields": ["p_baseball_raw","p_learned"],
        "forbidden_probability_fields_as_baseball_evidence": ["p_effective","p_model","p_market","p_posterior"],
        "canonical_row": "latest pregame row per game_pk and phase",
        "independent_target_policy": "max one canonical side per market/game/phase",
        "alternate_lines_trainable_for_calibration": False,
    }
    model["source_rows_total"] = len(source)
    model["eligible_rows"] = len(rows)
    model["eligible_games"] = len({str(r.get("game_pk")) for r in rows})
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
