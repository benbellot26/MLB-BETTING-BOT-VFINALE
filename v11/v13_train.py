from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import calibration_baseball_v13 as calibration
from . import journal
from . import point_in_time_v13 as pit
from . import probability_contract_v13 as contract

STRICT_GLOBAL_N = 600
STRICT_MARKET_N = 400
STRICT_PHASE_MARKET_N = 300
EXACT_BACKFILL = Path("data/v13_historical_backfill.jsonl")
LEGACY_2026_REPORT = Path("data/mlb_backtest_2026_report.json")


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _load_exact_backfill(path: Path = EXACT_BACKFILL) -> list[dict[str,Any]]:
    """Load exact archived pregame replays.

    These rows are not trusted merely because they came from a historical run.
    Only the separately persisted pre-candidate probability field may become
    calibration evidence after contract, point-in-time and settlement checks.
    """
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
        out.append(dict(row))
    return out


def _canonical_options(row: dict[str,Any]) -> list[dict[str,Any]]:
    """Keep at most one independent baseball-only calibration target per market/phase."""
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


def _native_contract_ok(row: dict[str,Any]) -> bool:
    return contract.row_is_predictively_compatible(row)


def eligible_probability_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Use only promotion-grade current-generation native V13 observations.

    Native calibration can eventually alter displayed probabilities, therefore
    operational PIT validity alone is not enough: feature timestamps must carry
    durable/source-time attestation accepted by the promotion-grade validator.
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
        if not _native_contract_ok(row):
            continue
        promotion_valid, _ = pit.validate_promotion_grade_row(row)
        if not promotion_valid:
            continue
        canonical = _canonical_options(row)
        if not canonical:
            continue
        phase = str(row.get("phase") or "EARLY").upper()
        key = (str(row.get("game_pk") or ""), phase)
        rank = str(row.get("analyzed_at") or "")
        clone = dict(row)
        clone["options"] = canonical
        clone["calibration_evidence_origin"] = "native-current-generation-promotion-grade"
        if key not in best or rank > best[key][0]:
            best[key] = (rank,clone)
    return sorted((x[1] for x in best.values()), key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or ""), str(r.get("phase") or "")))


def eligible_exact_replay_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Promote only leakage-safe pre-candidate probabilities from exact replays.

    The current layered replay probability is deliberately discarded. The
    calibration engine sees p_replay_baseline_raw as p_baseball_raw, computed
    from the frozen baseline captured before any historical V13 candidate layer.
    """
    best: dict[tuple[str,str], tuple[str,dict[str,Any]]] = {}
    for row in rows:
        analyzed = _dt(row.get("analyzed_at"))
        game_time = _dt(row.get("game_date"))
        if analyzed is None or game_time is None or analyzed >= game_time:
            continue
        if row.get("point_in_time") is not True or row.get("features_from_postgame") is True:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        if not row.get("source_replay") or not _native_contract_ok(row):
            continue
        if row.get("validation_baseline_model_generation") != contract.MODEL_GENERATION_FINGERPRINT:
            continue
        rebuilt=[]
        for opt in row.get("options") or []:
            p=opt.get("p_replay_baseline_raw")
            if opt.get("result") not in {"WIN","LOSS"} or p is None:
                continue
            rebuilt.append({
                "market":opt.get("market"),
                "name":opt.get("name"),
                "point":opt.get("point"),
                "is_canonical_line":bool(opt.get("is_canonical_line")),
                "result":opt.get("result"),
                "p_baseball_raw":p,
                "p_learned":None,
                "p_structural":None,
                "calibration_evidence_source":"exact-replay-pre-candidate-baseline",
            })
        clone=dict(row)
        clone["options"] = rebuilt
        clone["calibration_evidence_origin"] = "exact-replay-pre-candidate-baseline"
        clone["market_probability_used_as_baseball_feature"] = False
        canonical=_canonical_options(clone)
        if not canonical:
            continue
        clone["options"] = canonical
        phase=str(clone.get("phase") or "EARLY").upper()
        key=(str(clone.get("game_pk") or ""),phase)
        rank=str(clone.get("analyzed_at") or "")
        if key not in best or rank > best[key][0]:
            best[key]=(rank,clone)
    return sorted((x[1] for x in best.values()), key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or ""),str(r.get("phase") or "")))


def combine_calibration_rows(native_rows: list[dict[str,Any]], replay_rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    """Deduplicate game/phase evidence, preferring genuine native observations."""
    merged: dict[tuple[str,str],dict[str,Any]] = {}
    for row in replay_rows:
        key=(str(row.get("game_pk") or ""),str(row.get("phase") or "EARLY").upper())
        merged[key]=row
    for row in native_rows:
        key=(str(row.get("game_pk") or ""),str(row.get("phase") or "EARLY").upper())
        merged[key]=row
    return sorted(merged.values(),key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or ""),str(r.get("phase") or "")))


def _legacy_2026_research_summary(path: Path = LEGACY_2026_REPORT) -> dict[str,Any]:
    """Expose the large 2026 walk-forward dataset as research evidence only."""
    if not path.exists():
        return {"status":"ABSENT","role":"research-walk-forward-only","used_for_native_calibration":False}
    try:
        report=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status":"INVALID","error":type(exc).__name__,"role":"research-walk-forward-only","used_for_native_calibration":False}
    methodology=report.get("methodology") or {}
    return {
        "status":"AVAILABLE",
        "role":"research-walk-forward-only",
        "used_for_native_calibration":False,
        "games":int(report.get("games") or 0),
        "warm_games":int(report.get("warm_games") or 0),
        "range":report.get("range"),
        "walk_forward":bool(methodology.get("walk_forward")),
        "future_game_stats_used":bool(methodology.get("future_game_stats_used")),
        "historical_odds_used":bool(methodology.get("historical_odds_used")),
        "v10_ml":report.get("v10_ml"),
        "warm_v10_ml":report.get("warm_v10_ml"),
        "probability_bins":report.get("v10_probability_bins"),
        "reason_not_native":"The 2026 legacy reconstruction lacks the exact current V13 feature/market snapshot for every game; it remains a broad walk-forward benchmark instead of being mislabeled as current-generation calibration evidence.",
    }


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
    exact_source = _load_exact_backfill()
    native_rows = eligible_probability_rows(list(live))
    replay_rows = eligible_exact_replay_rows(exact_source)
    rows = combine_calibration_rows(native_rows, replay_rows)
    model = enforce_strict_activation(calibration.build_model(rows))
    model["model_generation"] = contract.MODEL_GENERATION_FINGERPRINT
    model["training_policy"] = {
        "native_predictive_contract_required": True,
        "native_promotion_grade_pit_required": True,
        "exact_model_generation_required": contract.MODEL_GENERATION_FINGERPRINT,
        "pregame_required": True,
        "settled_result_required": True,
        "accepted_native_probability_fields": ["p_baseball_raw","p_learned"],
        "accepted_exact_replay_probability_field": "p_replay_baseline_raw",
        "exact_replay_layered_probability_forbidden": True,
        "p_learned_requires_current_predictive_contract": True,
        "forbidden_probability_fields_as_baseball_evidence": ["p_effective","p_model","p_market","p_posterior","p_predictive_final","p_baseball_calibrated"],
        "canonical_row": "latest pregame row per game_pk and phase",
        "independent_target_policy": "max one canonical side per market/game/phase",
        "native_row_preferred_over_replay_on_collision": True,
        "alternate_lines_trainable_for_calibration": False,
        "strict_volume_floor_after_internal_holdout": True,
        "exact_v13_replay_backfill_allowed": True,
        "exact_replays_require_pre_candidate_baseline": True,
        "legacy_reconstructed_1801_allowed_as_native_calibration": False,
        "legacy_2026_dataset_role": "research-walk-forward-only",
        "runtime_global_cross_market_fallback_allowed": False,
        "activation_validation": "expanding walk-forward method selection + untouched chronological final holdout",
    }
    model["source_rows_total"] = len(live) + len(exact_source)
    model["source_rows_live"] = len(live)
    model["source_rows_exact_replay_total"] = len(exact_source)
    model["source_rows_exact_replay_eligible"] = len(replay_rows)
    model["source_rows_exact_replay_used_for_calibration"] = sum(
        1 for r in rows if r.get("calibration_evidence_origin") == "exact-replay-pre-candidate-baseline"
    )
    model["eligible_native_rows"] = len(native_rows)
    model["eligible_rows"] = len(rows)
    model["eligible_games"] = len({str(r.get("game_pk")) for r in rows})
    model["exact_replay_games"] = len({str(r.get("game_pk")) for r in replay_rows})
    model["rejected_non_current_generation_rows"] = sum(1 for r in live if not contract.row_is_predictively_compatible(r))
    model["rejected_non_promotion_grade_native_rows"] = sum(
        1 for r in live
        if contract.row_is_predictively_compatible(r)
        and r.get("home_score") is not None and r.get("away_score") is not None
        and not pit.validate_promotion_grade_row(r)[0]
    )
    model["legacy_2026_research"] = _legacy_2026_research_summary()
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
