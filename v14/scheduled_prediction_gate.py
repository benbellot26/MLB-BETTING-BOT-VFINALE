from __future__ import annotations

"""Zero-paid-call gate for objective scheduled FINAL snapshots.

The workflow may wake frequently, but this module performs only a free MLB
schedule read plus local ledger reads. The default API-budget policy remains the
ultra-low one-snapshot fail-safe. Production may explicitly grant more than one
snapshot per MLB slate; when it does, this gate plans all remaining snapshots
jointly so an early valid cluster is not sacrificed merely because a larger
cluster exists later.

Planning policy:
- never relax the frozen canonical 10-60m certification window;
- maximize unique uncovered games captured with the *remaining* paid snapshot
  allowance for the MLB slate;
- among equally complete plans, use fewer paid snapshots;
- then minimize mean distance from the frozen 30m FINAL target, measured at the
  first selected snapshot that would certify each game;
- deterministic ties prefer later snapshot instants, matching the original
  single-snapshot policy and improving lineup-confirmation probability.
"""

import argparse
from datetime import datetime, timedelta, timezone
from itertools import combinations
import json
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .acquisition import mlb_schedule, parse_time, resolve_target_date
from .api_budget import KIND_PREDICTION, latest_recorded_at, prediction_allowance
from .certification_timing import (
    CERTIFICATION_RUN_TRIGGER,
    FINAL_MAX_MINUTES_TO_GAME,
    FINAL_MIN_MINUTES_TO_GAME,
    FINAL_TARGET_MINUTES_TO_GAME,
    is_certification_snapshot,
)

PREDICTIONS = Path("data/v14_predictions.jsonl")
API_USAGE = Path("data/v14_api_usage.jsonl")
OUTPUT = Path("runtime/v14/scheduled_prediction_gate.json")
RETRY_COOLDOWN_MINUTES = 15.0
NON_STARTABLE_DETAIL_TOKENS = ("postponed", "cancelled", "canceled", "suspended", "delayed")


def _now(value: datetime | None = None) -> datetime:
    out = value or datetime.now(timezone.utc)
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _read_predictions(path: Path | str = PREDICTIONS) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _row_policy(row: dict[str, Any]) -> str | None:
    direct = row.get("probability_policy_id")
    if direct:
        return str(direct)
    nested = (row.get("calibration") or {}).get("probability_policy_id")
    return str(nested) if nested else None


def covered_game_ids(rows: list[dict[str, Any]]) -> set[str]:
    covered = set()
    for row in rows:
        if row.get("model_generation") != MODEL_GENERATION or _row_policy(row) != PROBABILITY_POLICY_ID:
            continue
        if is_certification_snapshot(row):
            game_pk = str(row.get("game_pk") or "")
            if game_pk:
                covered.add(game_pk)
    return covered


def _startable_pregame(game: dict[str, Any]) -> bool:
    status = game.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").strip().lower()
    if abstract in {"live", "final"}:
        return False
    detailed = str(status.get("detailedState") or "").strip().lower()
    if any(token in detailed for token in NON_STARTABLE_DETAIL_TOKENS):
        return False
    return True


def _uncovered_games(games: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    covered = covered_game_ids(predictions)
    out = []
    for game in games:
        game_pk = str(game.get("gamePk") or "")
        if not game_pk or game_pk in covered or not _startable_pregame(game):
            continue
        try:
            game_time = parse_time(game.get("gameDate"))
        except Exception:
            continue
        teams = game.get("teams") or {}
        out.append(
            {
                "game_pk": game_pk,
                "game_time": game_time,
                "game_date": game_time.isoformat(),
                "home": (((teams.get("home") or {}).get("team") or {}).get("name")),
                "away": (((teams.get("away") or {}).get("team") or {}).get("name")),
            }
        )
    return out


def _eligible_at(row: dict[str, Any], at: datetime) -> bool:
    minutes = (row["game_time"] - at).total_seconds() / 60.0
    return FINAL_MIN_MINUTES_TO_GAME <= minutes <= FINAL_MAX_MINUTES_TO_GAME


def due_games(
    games: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = _now(now)
    due = []
    for row in _uncovered_games(games, predictions):
        minutes = (row["game_time"] - current).total_seconds() / 60.0
        if FINAL_MIN_MINUTES_TO_GAME <= minutes <= FINAL_MAX_MINUTES_TO_GAME:
            due.append({k: v for k, v in row.items() if k != "game_time"} | {"minutes_to_game": minutes})
    return sorted(due, key=lambda row: (float(row["minutes_to_game"]), str(row["game_pk"])))


def _candidate_times(rows: list[dict[str, Any]], current: datetime) -> list[datetime]:
    candidates = {current}
    for row in rows:
        game_time = row["game_time"]
        for minutes in (
            FINAL_MAX_MINUTES_TO_GAME,
            FINAL_TARGET_MINUTES_TO_GAME,
            FINAL_MIN_MINUTES_TO_GAME,
        ):
            candidate = game_time - timedelta(minutes=float(minutes))
            if candidate >= current:
                candidates.add(candidate)
    return sorted(candidate for candidate in candidates if any(_eligible_at(row, candidate) for row in rows))


def best_cluster(
    games: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Backward-compatible single-snapshot optimizer used for diagnostics/tests."""

    current = _now(now)
    rows = [row for row in _uncovered_games(games, predictions) if row["game_time"] > current]
    if not rows:
        return {"target_at": None, "game_ids": [], "games": 0, "mean_target_error_minutes": None}
    scored = []
    for candidate in _candidate_times(rows, current):
        covered = [row for row in rows if _eligible_at(row, candidate)]
        errors = [
            abs((row["game_time"] - candidate).total_seconds() / 60.0 - FINAL_TARGET_MINUTES_TO_GAME)
            for row in covered
        ]
        scored.append((len(covered), sum(errors) / len(errors), candidate, covered))
    if not scored:
        return {"target_at": None, "game_ids": [], "games": 0, "mean_target_error_minutes": None}
    max_games = max(item[0] for item in scored)
    same = [item for item in scored if item[0] == max_games]
    min_error = min(item[1] for item in same)
    best = [item for item in same if abs(item[1] - min_error) < 1e-9]
    count, error, target, covered = max(best, key=lambda item: item[2])
    return {
        "target_at": target.isoformat(),
        "game_ids": [row["game_pk"] for row in covered],
        "games": count,
        "mean_target_error_minutes": error,
        "policy": "MAX_GAMES_THEN_CLOSEST_TO_30M_THEN_LATEST",
    }


def _effective_snapshot_capacity(budget: dict[str, Any]) -> int:
    """Return how many more snapshots can safely fit every current hard limit."""

    slate_remaining = max(0, int(budget.get("remaining") or 0))
    if slate_remaining <= 0 or not budget.get("allowed"):
        return 0
    provider = budget.get("provider_guard") or {}
    cost = max(1, int(provider.get("conservative_next_credit_cost") or provider.get("configured_next_credit_cost") or 1))
    capacities = [slate_remaining]
    for key in ("automated_month", "all_paid_month"):
        state = budget.get(key) or {}
        remaining = state.get("provider_credits_remaining")
        if remaining is not None:
            capacities.append(max(0, int(remaining) // cost))
    if provider.get("fresh") and provider.get("credits_remaining_until_provider_reset") is not None:
        usable = int(provider.get("credits_remaining_until_provider_reset") or 0) - int(provider.get("reserve_credits") or 0)
        capacities.append(max(0, usable // cost))
    return max(0, min(capacities))


def _evaluate_plan(
    selected: tuple[datetime, ...],
    rows: list[dict[str, Any]],
) -> tuple[set[str], float]:
    """Score the first qualifying selected snapshot for every covered game."""

    covered: set[str] = set()
    errors: list[float] = []
    for row in rows:
        for candidate in selected:
            if _eligible_at(row, candidate):
                covered.add(str(row["game_pk"]))
                minutes = (row["game_time"] - candidate).total_seconds() / 60.0
                errors.append(abs(minutes - FINAL_TARGET_MINUTES_TO_GAME))
                break
    mean_error = sum(errors) / len(errors) if errors else float("inf")
    return covered, mean_error


def optimal_snapshot_plan(
    games: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    max_snapshots: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Exact small-slate optimizer for up to ``max_snapshots`` future captures.

    A MLB slate has at most a few dozen candidate boundary/target instants, so an
    exhaustive combination search through at most four production snapshots is
    cheap and deterministic. It optimizes *unique games*, not rows or markets.
    """

    current = _now(now)
    limit = max(0, int(max_snapshots))
    rows = [row for row in _uncovered_games(games, predictions) if row["game_time"] > current]
    if not rows or limit <= 0:
        return {
            "snapshots": [],
            "snapshot_limit": limit,
            "games": 0,
            "game_ids": [],
            "mean_target_error_minutes": None,
            "policy": "MAX_UNIQUE_GAMES_THEN_MIN_SNAPSHOTS_THEN_CLOSEST_TO_30M",
        }

    candidates = _candidate_times(rows, current)
    best_selected: tuple[datetime, ...] = tuple()
    best_covered: set[str] = set()
    best_error = float("inf")
    best_key: tuple[Any, ...] | None = None
    max_r = min(limit, len(candidates))
    for r in range(1, max_r + 1):
        for combo in combinations(candidates, r):
            covered, mean_error = _evaluate_plan(combo, rows)
            if not covered:
                continue
            # Maximize unique games, then conserve paid calls, then target 30m.
            # Final deterministic tie prefers later instants, preserving the
            # original single-snapshot tie rule.
            timestamp_key = tuple(candidate.timestamp() for candidate in combo)
            key = (len(covered), -r, -mean_error, timestamp_key)
            if best_key is None or key > best_key:
                best_key = key
                best_selected = combo
                best_covered = covered
                best_error = mean_error

    snapshots = []
    already_assigned: set[str] = set()
    for candidate in best_selected:
        newly_covered = [
            str(row["game_pk"])
            for row in rows
            if str(row["game_pk"]) not in already_assigned and _eligible_at(row, candidate)
        ]
        if not newly_covered:
            continue
        assigned_rows = [row for row in rows if str(row["game_pk"]) in set(newly_covered)]
        errors = [
            abs((row["game_time"] - candidate).total_seconds() / 60.0 - FINAL_TARGET_MINUTES_TO_GAME)
            for row in assigned_rows
        ]
        newly_covered = sorted(newly_covered)
        already_assigned.update(newly_covered)
        snapshots.append(
            {
                "target_at": candidate.isoformat(),
                "game_ids": newly_covered,
                "games": len(newly_covered),
                "mean_target_error_minutes": sum(errors) / len(errors) if errors else None,
            }
        )

    return {
        "snapshots": snapshots,
        "snapshot_limit": limit,
        "snapshots_planned": len(snapshots),
        "games": len(best_covered),
        "game_ids": sorted(best_covered),
        "mean_target_error_minutes": best_error if best_covered else None,
        "policy": "MAX_UNIQUE_GAMES_THEN_MIN_SNAPSHOTS_THEN_CLOSEST_TO_30M",
    }


def build(
    *,
    predictions_path: Path | str = PREDICTIONS,
    api_usage_path: Path | str = API_USAGE,
    target_date: str | None = None,
    now: datetime | None = None,
    games_loader: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    current = _now(now)
    day = target_date or resolve_target_date(now=current)
    loader = games_loader or (lambda value: mlb_schedule(value, hydrate=""))
    games = loader(day)
    predictions = _read_predictions(predictions_path)
    due = due_games(games, predictions, now=current)
    budget = prediction_allowance(api_usage_path, now=current, slate_date=day)
    capacity = _effective_snapshot_capacity(budget)
    single_plan = best_cluster(games, predictions, now=current)
    plan = optimal_snapshot_plan(games, predictions, max_snapshots=capacity, now=current)

    last = latest_recorded_at(KIND_PREDICTION, api_usage_path)
    cooldown_remaining = 0.0
    if last is not None:
        elapsed = (current - last).total_seconds() / 60.0
        cooldown_remaining = max(0.0, RETRY_COOLDOWN_MINUTES - elapsed)

    first_target = None
    if plan.get("snapshots"):
        first_target = parse_time(plan["snapshots"][0]["target_at"])
    waiting_for_cluster = bool(due and first_target is not None and first_target > current + timedelta(seconds=30))

    if not due:
        reason = "NO_FINAL_SNAPSHOT_DUE"
    elif cooldown_remaining > 0:
        reason = "PREDICTION_RETRY_COOLDOWN"
    elif not budget.get("allowed") or capacity <= 0:
        reason = "AUTOMATED_PREDICTION_BUDGET_EXHAUSTED"
    elif waiting_for_cluster:
        reason = "WAITING_FOR_BEST_SLATE_CLUSTER"
    else:
        reason = "FINAL_SNAPSHOT_DUE"

    run_required = bool(
        due
        and budget.get("allowed")
        and capacity > 0
        and cooldown_remaining <= 0
        and not waiting_for_cluster
    )
    return {
        "schema": "pulsar-v14-scheduled-prediction-gate-v4",
        "checked_at": current.isoformat(),
        "target_date": day,
        "slate_date": day,
        "run_trigger": CERTIFICATION_RUN_TRIGGER,
        "run_required": run_required,
        "reason": reason,
        "network_policy": "MLB_SCHEDULE_FREE_PLUS_LOCAL_LEDGER_ONLY_BEFORE_PAID_RUN",
        "paid_api_calls_performed": 0,
        "final_window_minutes_to_game": {
            "min": FINAL_MIN_MINUTES_TO_GAME,
            "target": FINAL_TARGET_MINUTES_TO_GAME,
            "max": FINAL_MAX_MINUTES_TO_GAME,
        },
        "retry_cooldown_minutes": RETRY_COOLDOWN_MINUTES,
        "cooldown_remaining_minutes": cooldown_remaining,
        "due_games": due,
        "due_game_ids": [row["game_pk"] for row in due],
        "best_slate_cluster": single_plan,
        "best_daily_cluster": single_plan,
        "optimal_slate_plan": plan,
        "effective_snapshot_capacity_remaining": capacity,
        "projected_unique_games_covered": int(plan.get("games") or 0),
        "already_covered_scheduled_final_games": len(covered_game_ids(predictions)),
        "prediction_budget": budget,
        "cost_policy": "default ultra-low fail-safe; production may opt into a bounded multi-snapshot slate plan under the unchanged monthly hard cap/provider reserve",
    }


def write(*, output: Path | str = OUTPUT, **kwargs: Any) -> dict[str, Any]:
    result = build(**kwargs)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether an objective scheduled FINAL V14 prediction snapshot is optimally due")
    parser.add_argument("--predictions", default=str(PREDICTIONS))
    parser.add_argument("--api-usage-ledger", default=str(API_USAGE))
    parser.add_argument("--target-date")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    out = write(
        predictions_path=args.predictions,
        api_usage_path=args.api_usage_ledger,
        target_date=args.target_date,
        output=args.output,
    )
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
