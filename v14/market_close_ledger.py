from __future__ import annotations

"""Prospective market-close archive for every tracked V14 game.

This ledger is deliberately separate from the paper-bet and authorized-bet
ledgers. It preserves verified market closes for research and for later
hydration of an already-existing paper bet, but archive rows themselves never
create a bet, never earn certification credit, and never affect the champion.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .acquisition import MATCH_TIME_TOLERANCE_MINUTES, odds_snapshot, parse_time
from .market_lines import DEFAULT_MAX_MARKET_AGE_MINUTES, _book_freshness, _market_outcomes
from .sharp_market import sharp_consensus

LEDGER = Path("data/v14_market_close_ledger.jsonl")
REPORT = Path("data/v14_market_close_report.json")
PAPER_LEDGER = Path("data/v14_paper_bet_ledger.jsonl")
SCHEMA = "pulsar-v14-market-close-v1"
ROLE = "RESEARCH_MARKET_CLOSE_ARCHIVE"
CLOSE_WINDOW_MINUTES = 120.0
CERTIFIED_CLOSE_MAX_MINUTES = 15.0
PAPER_SCHEMAS = {f"pulsar-v14-paper-bet-v{i}" for i in range(1, 8)}


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _read(path: Path | str = LEDGER) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("schema") == SCHEMA:
            rows.append(row)
    return rows


def _write(rows: list[dict[str, Any]], path: Path | str = LEDGER) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_paper(path: Path | str = PAPER_LEDGER) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("schema") in PAPER_SCHEMAS:
            rows.append(row)
    return rows


def _write_paper(rows: list[dict[str, Any]], path: Path | str = PAPER_LEDGER) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _strictly_pregame(analyzed_at: Any, game_date: Any) -> bool:
    try:
        return parse_time(analyzed_at) < parse_time(game_date)
    except Exception:
        return False


def _prediction_policy(result: dict[str, Any]) -> str | None:
    prediction = result.get("v14_prediction") or {}
    direct = prediction.get("probability_policy_id")
    if direct:
        return str(direct)
    nested = (prediction.get("calibration") or {}).get("probability_policy_id")
    return str(nested) if nested else None


def _event_identity(result: dict[str, Any]) -> tuple[str, bool, float | None]:
    market = result.get("market_snapshot") or {}
    event_id = str(result.get("odds_event_id") or market.get("event_id") or "")
    try:
        game = parse_time(result.get("game_date"))
        event = parse_time(market.get("commence_time"))
    except Exception:
        return event_id, False, None
    delta = abs((event - game).total_seconds()) / 60.0
    return event_id, bool(event_id) and delta <= MATCH_TIME_TOLERANCE_MINUTES, delta


def _line_key(value: float) -> str:
    return format(float(value), ".10g")


def _tracked_total_line(result: dict[str, Any]) -> float | None:
    value = (result.get("canonical_lines") or {}).get("TOTAL")
    if value is None:
        value = ((result.get("market_snapshot") or {}).get("markets") or {}).get("TOTAL", {}).get("line")
    return _num(value)


def record_payload(payload: dict[str, Any], path: Path | str = LEDGER) -> int:
    """Register every eligible current-generation game, independent of edge/pick status."""
    rows = _read(path)
    by_game = {
        str(row.get("game_pk") or ""): row
        for row in rows
        if row.get("model_generation") == MODEL_GENERATION
        and row.get("probability_policy_id") == PROBABILITY_POLICY_ID
        and str(row.get("game_pk") or "")
    }
    before = len(rows)
    changed = False
    if payload.get("model_generation") != MODEL_GENERATION:
        _write(rows, path)
        return 0

    for result in payload.get("results") or []:
        if result.get("model_generation") != MODEL_GENERATION:
            continue
        prediction = result.get("v14_prediction") or {}
        if prediction.get("model_generation") != MODEL_GENERATION:
            continue
        if _prediction_policy(result) != PROBABILITY_POLICY_ID:
            continue
        analyzed_at = str(result.get("analyzed_at") or payload.get("analyzed_at") or "")
        game_date = result.get("game_date")
        if not _strictly_pregame(analyzed_at, game_date):
            continue
        event_id, event_verified, event_delta = _event_identity(result)
        market = result.get("market_snapshot") or {}
        if not event_verified or market.get("freshness_verified") is not True:
            continue
        game_pk = str(result.get("game_pk") or "")
        if not game_pk:
            continue
        line = _tracked_total_line(result)
        existing = by_game.get(game_pk)
        if existing is None:
            total_lines = [_line_key(line)] if line is not None else []
            row = {
                "schema": SCHEMA,
                "ledger_role": ROLE,
                "research_only": True,
                "certification_eligible": False,
                "champion_impact": False,
                "auto_activation": False,
                "model_generation": MODEL_GENERATION,
                "probability_policy_id": PROBABILITY_POLICY_ID,
                "game_pk": game_pk,
                "odds_event_id": event_id,
                "odds_event_time_verified": True,
                "odds_event_time_delta_minutes": event_delta,
                "target_date": str(payload.get("target_date") or ""),
                "game_date": game_date,
                "home": result.get("home"),
                "away": result.get("away"),
                "first_tracked_at": analyzed_at,
                "latest_tracked_at": analyzed_at,
                "tracked_total_lines": total_lines,
                "latest_total_line": line,
                "close_history": [],
                "best_close": None,
            }
            rows.append(row)
            by_game[game_pk] = row
            changed = True
            continue

        # Tracking may legitimately receive EARLY/LATE/FINAL snapshots. Keep the
        # latest strictly-pregame line and all lines needed to hydrate an earlier
        # paper entry, without changing the immutable game/event identity.
        if str(existing.get("odds_event_id") or "") != event_id:
            continue
        try:
            newer = parse_time(analyzed_at) > parse_time(existing.get("latest_tracked_at"))
        except Exception:
            newer = False
        lines = list(existing.get("tracked_total_lines") or [])
        if line is not None and _line_key(line) not in lines:
            lines.append(_line_key(line))
            existing["tracked_total_lines"] = sorted(lines, key=float)
            changed = True
        if newer:
            existing["latest_tracked_at"] = analyzed_at
            existing["latest_total_line"] = line
            changed = True

    if changed or not Path(path).exists():
        rows.sort(key=lambda row: (str(row.get("game_date") or ""), str(row.get("game_pk") or "")))
        _write(rows, path)
    return len(rows) - before


def _event_for_row(row: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    event_id = str(row.get("odds_event_id") or "")
    if not event_id:
        return None
    exact = [event for event in events if str(event.get("id") or "") == event_id]
    if len(exact) != 1:
        return None
    event = exact[0]
    try:
        delta = abs((parse_time(event.get("commence_time")) - parse_time(row.get("game_date"))).total_seconds()) / 60.0
    except Exception:
        return None
    return event if delta <= MATCH_TIME_TOLERANCE_MINUTES else None


def _outcome_price(
    outcomes: list[dict[str, Any]], name: str, point: float | None = None
) -> float | None:
    for outcome in outcomes:
        if str(outcome.get("name") or "") != name:
            continue
        actual_point = _num(outcome.get("point"))
        if point is not None and actual_point != point:
            continue
        price = _num(outcome.get("price"))
        if price is not None and price > 1:
            return price
    return None


def _execution_prices(event: dict[str, Any], *, as_of: str, total_lines: list[float]) -> dict[str, Any]:
    home = str(event.get("home_team") or "")
    away = str(event.get("away_team") or "")
    output: dict[str, Any] = {}
    for book in event.get("bookmakers") or []:
        key = str(book.get("key") or "")
        if not key or _book_freshness(book, as_of, DEFAULT_MAX_MARKET_AGE_MINUTES) != "VERIFIED_FRESH":
            continue
        row: dict[str, Any] = {}
        h2h = _market_outcomes(book, "h2h")
        for selection, name in (("home_ml", home), ("away_ml", away)):
            price = _outcome_price(h2h, name)
            if price is not None:
                row[selection] = price
        spreads = _market_outcomes(book, "spreads")
        spread_specs = (
            ("home_minus_1_5", home, -1.5),
            ("away_plus_1_5", away, 1.5),
            ("away_minus_1_5", away, -1.5),
            ("home_plus_1_5", home, 1.5),
        )
        for selection, name, point in spread_specs:
            price = _outcome_price(spreads, name, point)
            if price is not None:
                row[selection] = price
        totals = _market_outcomes(book, "totals")
        total_prices: dict[str, Any] = {}
        for line in total_lines:
            by_side: dict[str, float] = {}
            for selection, name in (("over", "Over"), ("under", "Under")):
                price = _outcome_price(totals, name, line)
                if price is not None:
                    by_side[selection] = price
            if by_side:
                total_prices[_line_key(line)] = by_side
        if total_prices:
            row["totals"] = total_prices
        if row:
            output[key] = row
    return output


def _compact_selection(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    probability = _num(row.get("fair_probability"))
    if probability is None or not 0 < probability < 1:
        return None
    return {
        "fair_probability": probability,
        "dispersion_pp": _num(row.get("dispersion_pp")),
        "source_count": int(row.get("source_count") or 0),
        "sportsbook_source_count": int(row.get("sportsbook_source_count") or 0),
        "exchange_proxy_source_count": int(row.get("exchange_proxy_source_count") or 0),
        "books": list(row.get("books") or []),
    }


def _snapshot_close(event: dict[str, Any], row: dict[str, Any], *, captured: str, mins: float) -> dict[str, Any] | None:
    raw_lines = row.get("tracked_total_lines") or []
    total_lines = sorted({_num(value) for value in raw_lines if _num(value) is not None})
    # One no-total call guarantees ML/RL are still captured if totals disappear.
    base = sharp_consensus(event, total_line=None, as_of=captured)
    selections: dict[str, Any] = {}
    for selection in (
        "home_ml",
        "away_ml",
        "home_minus_1_5",
        "away_plus_1_5",
        "away_minus_1_5",
        "home_plus_1_5",
    ):
        compact = _compact_selection((base.get("selections") or {}).get(selection))
        if compact is not None:
            selections[selection] = compact
    totals: dict[str, Any] = {}
    for line in total_lines:
        sharp = sharp_consensus(event, total_line=line, as_of=captured)
        by_side: dict[str, Any] = {}
        for selection in ("over", "under"):
            compact = _compact_selection((sharp.get("selections") or {}).get(selection))
            if compact is not None:
                by_side[selection] = compact
        if by_side:
            totals[_line_key(line)] = by_side
    if not selections and not totals:
        return None
    quality = "CERTIFIED_CLOSE" if mins <= CERTIFIED_CLOSE_MAX_MINUTES else "PROVISIONAL_CLOSE"
    return {
        "captured_at": captured,
        "minutes_to_game": mins,
        "quality": quality,
        "odds_event_id": event.get("id"),
        "event_commence_time": event.get("commence_time"),
        "selections": selections,
        "totals": totals,
        "execution_prices": _execution_prices(event, as_of=captured, total_lines=total_lines),
    }


def _better_close(candidate: dict[str, Any], incumbent: dict[str, Any] | None) -> bool:
    if not isinstance(incumbent, dict):
        return True
    rank = {"CERTIFIED_CLOSE": 0, "PROVISIONAL_CLOSE": 1}
    c_rank = rank.get(str(candidate.get("quality") or ""), 9)
    i_rank = rank.get(str(incumbent.get("quality") or ""), 9)
    if c_rank != i_rank:
        return c_rank < i_rank
    c_mins = _num(candidate.get("minutes_to_game"))
    i_mins = _num(incumbent.get("minutes_to_game"))
    if c_mins is None:
        return False
    return i_mins is None or c_mins < i_mins


def capture(
    path: Path | str = LEDGER,
    *,
    api_key: str | None = None,
    events_loader: Callable[[], list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> int:
    rows = _read(path)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    pending: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        if row.get("model_generation") != MODEL_GENERATION or row.get("probability_policy_id") != PROBABILITY_POLICY_ID:
            continue
        if row.get("odds_event_time_verified") is not True:
            continue
        try:
            mins = (parse_time(row.get("game_date")) - current).total_seconds() / 60.0
        except Exception:
            continue
        if 0 < mins <= CLOSE_WINDOW_MINUTES:
            pending.append((row, mins))
    if not pending:
        return 0

    events = (events_loader or (lambda: odds_snapshot(api_key=api_key)))()
    changed = 0
    captured = current.isoformat()
    for row, mins in pending:
        event = _event_for_row(row, events)
        if event is None:
            continue
        close = _snapshot_close(event, row, captured=captured, mins=mins)
        if close is None:
            continue
        history = row.get("close_history") if isinstance(row.get("close_history"), list) else []
        # Idempotent across reruns at the same timestamp/event.
        duplicate = any(
            h.get("captured_at") == close["captured_at"] and h.get("odds_event_id") == close["odds_event_id"]
            for h in history
            if isinstance(h, dict)
        )
        if duplicate:
            continue
        history.append(close)
        row["close_history"] = history
        if _better_close(close, row.get("best_close")):
            row["best_close"] = close
        changed += 1
    if changed:
        _write(rows, path)
    return changed


def _selection_from_close(close: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any] | None:
    selection = str(paper.get("selection") or "")
    if selection in {"over", "under"}:
        line = _num(paper.get("total_line"))
        if line is None:
            return None
        return (((close.get("totals") or {}).get(_line_key(line)) or {}).get(selection))
    return (close.get("selections") or {}).get(selection)


def _execution_from_close(close: dict[str, Any], paper: dict[str, Any]) -> float | None:
    book = str(paper.get("execution_book") or "")
    selection = str(paper.get("selection") or "")
    book_row = (close.get("execution_prices") or {}).get(book) or {}
    if selection in {"over", "under"}:
        line = _num(paper.get("total_line"))
        if line is None:
            return None
        return _num((((book_row.get("totals") or {}).get(_line_key(line)) or {}).get(selection)))
    return _num(book_row.get(selection))


def _eligible_archive_closes(archive: dict[str, Any], paper: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    try:
        analyzed = parse_time(paper.get("analyzed_at"))
        game = parse_time(paper.get("game_date"))
    except Exception:
        return []
    for close in archive.get("close_history") or []:
        if not isinstance(close, dict) or close.get("quality") != "CERTIFIED_CLOSE":
            continue
        if str(close.get("odds_event_id") or "") != str(paper.get("odds_event_id") or ""):
            continue
        try:
            captured = parse_time(close.get("captured_at"))
        except Exception:
            continue
        mins = _num(close.get("minutes_to_game"))
        if not (analyzed <= captured < game) or mins is None or not (0 < mins <= CERTIFIED_CLOSE_MAX_MINUTES):
            continue
        selection = _selection_from_close(close, paper)
        fair = _num((selection or {}).get("fair_probability"))
        if fair is None or not 0 < fair < 1:
            continue
        output.append(close)
    output.sort(key=lambda close: float(close.get("minutes_to_game") or 9999.0))
    return output


def hydrate_paper(
    close_path: Path | str = LEDGER,
    paper_path: Path | str = PAPER_LEDGER,
) -> int:
    """Reuse only prospectively persisted certified closes for existing paper bets.

    This function cannot create paper bets. It only fills close fields on rows
    that already passed the paper-ledger entry contract.
    """
    archives = {
        str(row.get("game_pk") or ""): row
        for row in _read(close_path)
        if row.get("model_generation") == MODEL_GENERATION
        and row.get("probability_policy_id") == PROBABILITY_POLICY_ID
        and row.get("certification_eligible") is False
    }
    paper_rows = _read_paper(paper_path)
    changed = 0
    for paper in paper_rows:
        if paper.get("model_generation") != MODEL_GENERATION or paper.get("probability_policy_id") != PROBABILITY_POLICY_ID:
            continue
        archive = archives.get(str(paper.get("game_pk") or ""))
        if archive is None:
            continue
        if str(archive.get("odds_event_id") or "") != str(paper.get("odds_event_id") or ""):
            continue
        candidates = _eligible_archive_closes(archive, paper)
        if not candidates:
            continue
        close = candidates[0]
        existing_quality = str(paper.get("close_quality") or "")
        existing_mins = _num(paper.get("close_minutes_to_game"))
        archive_mins = _num(close.get("minutes_to_game"))
        if existing_quality == "CERTIFIED_CLOSE" and existing_mins is not None and archive_mins is not None and existing_mins <= archive_mins:
            continue
        selection = _selection_from_close(close, paper) or {}
        fair = _num(selection.get("fair_probability"))
        if fair is None:
            continue
        entry_sharp = _num(paper.get("entry_sharp_probability"))
        entry_exec = _num(paper.get("entry_execution_implied_probability"))
        if entry_exec is None:
            odds = _num(paper.get("execution_odds"))
            entry_exec = 1 / odds if odds is not None and odds > 1 else None
        execution_close = _execution_from_close(close, paper)
        marker = {
            "captured_at": close.get("captured_at"),
            "minutes_to_game": archive_mins,
            "quality": "CERTIFIED_CLOSE",
            "sharp_fair_probability": fair,
            "sharp_dispersion_pp": _num(selection.get("dispersion_pp")),
            "execution_close_odds": execution_close,
            "odds_event_id": close.get("odds_event_id"),
            "event_time_delta_minutes": archive.get("odds_event_time_delta_minutes"),
            "source": ROLE,
        }
        history = paper.get("close_history") if isinstance(paper.get("close_history"), list) else []
        if not any(
            isinstance(item, dict)
            and item.get("captured_at") == marker["captured_at"]
            and item.get("odds_event_id") == marker["odds_event_id"]
            and item.get("source") == ROLE
            for item in history
        ):
            history.append(marker)
        paper["close_history"] = history
        paper["close_captured_at"] = close.get("captured_at")
        paper["close_minutes_to_game"] = archive_mins
        paper["close_quality"] = "CERTIFIED_CLOSE"
        paper["closing_sharp_probability"] = fair
        paper["sharp_fair_close_odds"] = 1 / fair
        paper["sharp_clv_pp"] = (fair - entry_sharp) * 100 if entry_sharp is not None else None
        paper["certification_clv_pp"] = (fair - entry_exec) * 100 if entry_exec is not None else None
        paper["execution_close_odds"] = execution_close
        paper["execution_price_clv_pp"] = (
            (1 / execution_close - entry_exec) * 100
            if execution_close is not None and execution_close > 1 and entry_exec is not None
            else None
        )
        changed += 1
    if changed:
        _write_paper(paper_rows, paper_path)
    return changed


def report(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = _read() if rows is None else rows
    current = [
        row
        for row in data
        if row.get("model_generation") == MODEL_GENERATION
        and row.get("probability_policy_id") == PROBABILITY_POLICY_ID
    ]
    certified = [row for row in current if any((h or {}).get("quality") == "CERTIFIED_CLOSE" for h in row.get("close_history") or [])]
    observations = sum(len(row.get("close_history") or []) for row in current)
    market_counts = {"ML": 0, "RL_HOME_-1.5": 0, "RL_AWAY_-1.5": 0, "TOTAL_OVER": 0}
    for row in certified:
        history = [h for h in row.get("close_history") or [] if isinstance(h, dict) and h.get("quality") == "CERTIFIED_CLOSE"]
        if not history:
            continue
        best = sorted(history, key=lambda h: float(h.get("minutes_to_game") or 9999.0))[0]
        selections = best.get("selections") or {}
        if "home_ml" in selections:
            market_counts["ML"] += 1
        if "home_minus_1_5" in selections:
            market_counts["RL_HOME_-1.5"] += 1
        if "away_minus_1_5" in selections:
            market_counts["RL_AWAY_-1.5"] += 1
        if best.get("totals"):
            market_counts["TOTAL_OVER"] += 1
    return {
        "schema": "pulsar-v14-market-close-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ledger_role": ROLE,
        "research_only": True,
        "certification_eligible": False,
        "champion_impact": False,
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "tracked_games": len(current),
        "games_with_certified_close": len(certified),
        "close_observations": observations,
        "certified_market_coverage": market_counts,
        "paper_hydration_policy": "existing paper rows only; exact event/current identity; prospectively persisted <=15m close",
    }


def write_report(path: Path | str = REPORT, *, ledger: Path | str = LEDGER) -> dict[str, Any]:
    payload = report(_read(ledger))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Pulsar V14 prospective market-close archive")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record")
    record.add_argument("--payload", required=True)
    record.add_argument("--ledger", default=str(LEDGER))

    close = sub.add_parser("capture")
    close.add_argument("--ledger", default=str(LEDGER))
    close.add_argument("--report", default=str(REPORT))

    hydrate = sub.add_parser("hydrate-paper")
    hydrate.add_argument("--ledger", default=str(LEDGER))
    hydrate.add_argument("--paper-ledger", default=str(PAPER_LEDGER))

    rep = sub.add_parser("report")
    rep.add_argument("--ledger", default=str(LEDGER))
    rep.add_argument("--output", default=str(REPORT))

    args = parser.parse_args()
    if args.command == "record":
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        print(json.dumps({"recorded": record_payload(payload, args.ledger)}, sort_keys=True))
    elif args.command == "capture":
        changed = capture(args.ledger)
        payload = write_report(args.report, ledger=args.ledger)
        print(json.dumps({"captured": changed, "report": payload}, sort_keys=True))
    elif args.command == "hydrate-paper":
        print(json.dumps({"hydrated": hydrate_paper(args.ledger, args.paper_ledger)}, sort_keys=True))
    elif args.command == "report":
        print(json.dumps(write_report(args.output, ledger=args.ledger), sort_keys=True))


if __name__ == "__main__":
    main()
