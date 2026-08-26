from __future__ import annotations

"""Immutable official-bet ledger for Pulsar V14.

Rows are created only from statistically certified BET decisions. The ledger is
kept separate from user-reported outcomes. Closing price is optional and must be
explicitly captured later; it is never fabricated from a missing historical
price.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from .acquisition import mlb_schedule
from .staking import size_candidates

LEDGER = Path("data/v14_bet_ledger.jsonl")
REPORT = Path("data/v14_bet_performance.json")


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
        if isinstance(row, dict) and row.get("schema") == "pulsar-v14-official-bet-v1":
            rows.append(row)
    return rows


def _write(rows: list[dict[str, Any]], path: Path | str = LEDGER) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _execution_book(result: dict[str, Any], market: str) -> str | None:
    return (
        (((result.get("market_snapshot") or {}).get("markets") or {}).get(market) or {}).get("bookmaker")
    )


def record_payload(payload: dict[str, Any], path: Path | str = LEDGER) -> int:
    certification = payload.get("betting_certification") or {}
    if certification.get("certified") is not True:
        return 0

    existing = _read(path)
    index = {
        (str(row.get("game_pk")), str(row.get("selection")), str(row.get("analyzed_at"))): row
        for row in existing
    }
    before = len(index)

    for result in payload.get("results") or []:
        if (result.get("starter_fallback") or {}).get("degraded"):
            continue
        decision = result.get("decision") or {}
        sized = size_candidates(list(decision.get("candidates") or []), certified=True)
        prediction = result.get("v14_prediction") or {}
        raw = prediction.get("raw_probabilities") or prediction.get("probabilities") or {}
        sharp = (result.get("sharp_market") or {}).get("selections") or {}

        for row in sized:
            if row.get("status") != "BET" or float(row.get("stake_fraction") or 0) <= 0:
                continue
            selection = str(row.get("selection") or "")
            market = str(row.get("market") or "")
            analyzed_at = str(result.get("analyzed_at") or payload.get("analyzed_at") or "")
            key = (str(result.get("game_pk") or ""), selection, analyzed_at)
            if key in index:
                continue
            index[key] = {
                "schema": "pulsar-v14-official-bet-v1",
                "model_generation": payload.get("model_generation"),
                "game_pk": str(result.get("game_pk") or ""),
                "target_date": str(payload.get("target_date") or ""),
                "game_date": result.get("game_date"),
                "analyzed_at": analyzed_at,
                "home": result.get("home"),
                "away": result.get("away"),
                "market": market,
                "selection": selection,
                "line": (result.get("canonical_lines") or {}).get("TOTAL") if market == "TOTAL" else None,
                "bookmaker": _execution_book(result, market),
                "odds": row.get("price"),
                "probability": row.get("probability"),
                "raw_probability": _num(raw.get(selection)),
                "lower_probability": row.get("lower_probability"),
                "sharp_probability": _num((sharp.get(selection) or {}).get("fair_probability")),
                "model_edge_pp": row.get("model_edge_pp"),
                "robust_edge_pp": row.get("robust_edge_pp"),
                "stake_fraction": row.get("stake_fraction"),
                "unit_tier": row.get("unit_tier"),
                "result": None,
                "profit_stake_units": None,
                "home_score": None,
                "away_score": None,
                "settled_at": None,
                "closing_odds": None,
                "closing_source": None,
                "clv_implied_probability_pp": None,
                "certification_snapshot": certification,
            }

    ordered = sorted(
        index.values(),
        key=lambda row: (
            str(row.get("target_date")),
            str(row.get("game_pk")),
            str(row.get("selection")),
            str(row.get("analyzed_at")),
        ),
    )
    _write(ordered, path)
    return len(index) - before


def _grade(selection: str, home_score: int, away_score: int, line: float | None) -> str:
    if selection == "home_ml":
        return "WIN" if home_score > away_score else "LOSS"
    if selection == "away_ml":
        return "WIN" if away_score > home_score else "LOSS"
    if selection == "home_minus_1_5":
        return "WIN" if home_score - away_score >= 2 else "LOSS"
    if selection == "away_plus_1_5":
        return "WIN" if home_score - away_score <= 1 else "LOSS"
    if selection == "away_minus_1_5":
        return "WIN" if away_score - home_score >= 2 else "LOSS"
    if selection == "home_plus_1_5":
        return "WIN" if away_score - home_score <= 1 else "LOSS"
    if selection == "over" and line is not None:
        total = home_score + away_score
        return "WIN" if total > line else ("PUSH" if total == line else "LOSS")
    if selection == "under" and line is not None:
        total = home_score + away_score
        return "WIN" if total < line else ("PUSH" if total == line else "LOSS")
    return "UNRESOLVED"


def settle(
    path: Path | str = LEDGER,
    *,
    schedule_loader: Callable[[str], list[dict[str, Any]]] | None = None,
) -> int:
    rows = _read(path)
    loader = schedule_loader or (lambda day: mlb_schedule(day, hydrate="linescore"))
    pending: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row.get("result"):
            pending[str(row.get("target_date") or "")].append(row)

    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for day, items in pending.items():
        if not day:
            continue
        games = {str(game.get("gamePk") or ""): game for game in loader(day)}
        for row in items:
            game = games.get(str(row.get("game_pk") or ""))
            status = str(((game or {}).get("status") or {}).get("abstractGameState") or "").lower()
            if status != "final":
                continue
            teams = (game or {}).get("teams") or {}
            home_score = _num((teams.get("home") or {}).get("score"))
            away_score = _num((teams.get("away") or {}).get("score"))
            if home_score is None or away_score is None:
                continue
            result = _grade(
                str(row.get("selection") or ""),
                int(home_score),
                int(away_score),
                _num(row.get("line")),
            )
            if result == "UNRESOLVED":
                continue
            odds = float(row.get("odds") or 0)
            profit = (odds - 1.0) if result == "WIN" else (-1.0 if result == "LOSS" else 0.0)
            row["result"] = result
            row["profit_stake_units"] = profit
            row["home_score"] = int(home_score)
            row["away_score"] = int(away_score)
            row["settled_at"] = now
            count += 1

    _write(rows, path)
    return count


def attach_closing_price(
    *,
    game_pk: str,
    selection: str,
    analyzed_at: str,
    closing_odds: float,
    source: str,
    path: Path | str = LEDGER,
) -> bool:
    """Attach an explicitly captured close; never infer or fabricate one."""
    odds = float(closing_odds)
    if odds <= 1:
        raise ValueError("closing_odds must be > 1")
    rows = _read(path)
    changed = False
    for row in rows:
        if (
            str(row.get("game_pk")) == str(game_pk)
            and str(row.get("selection")) == str(selection)
            and str(row.get("analyzed_at")) == str(analyzed_at)
        ):
            entry = float(row.get("odds") or 0)
            row["closing_odds"] = odds
            row["closing_source"] = str(source)
            row["clv_implied_probability_pp"] = (1 / odds - 1 / entry) * 100 if entry > 1 else None
            changed = True
    if changed:
        _write(rows, path)
    return changed


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled_rows = [row for row in rows if row.get("result") in {"WIN", "LOSS", "PUSH"}]
    decisions = [row for row in settled_rows if row.get("result") != "PUSH"]
    profit = sum(
        float(row.get("profit_stake_units") or 0) * float(row.get("stake_fraction") or 0)
        for row in settled_rows
    )
    staked = sum(float(row.get("stake_fraction") or 0) for row in decisions)
    closes = [_num(row.get("clv_implied_probability_pp")) for row in settled_rows]
    closes = [value for value in closes if value is not None]
    return {
        "schema": "pulsar-v14-official-bet-performance-v1",
        "bets": len(rows),
        "settled": len(settled_rows),
        "wins": sum(row.get("result") == "WIN" for row in settled_rows),
        "losses": sum(row.get("result") == "LOSS" for row in settled_rows),
        "pushes": sum(row.get("result") == "PUSH" for row in settled_rows),
        "profit_bankroll_fraction": profit,
        "staked_bankroll_fraction": staked,
        "roi": profit / staked if staked else None,
        "clv": {
            "status": "AVAILABLE" if closes else "UNAVAILABLE",
            "n": len(closes),
            "mean_clv": sum(closes) / len(closes) if closes else None,
            "definition": "explicitly captured closing price only; never imputed",
        },
    }


def write_report(path: Path | str = LEDGER, output: Path | str = REPORT) -> dict[str, Any]:
    out = report(_read(path))
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    record = sub.add_parser("record")
    record.add_argument("--payload", default="runtime/v14/discord_payload.json")
    record.add_argument("--ledger", default=str(LEDGER))
    settle_parser = sub.add_parser("settle")
    settle_parser.add_argument("--ledger", default=str(LEDGER))
    settle_parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args()

    if args.cmd == "record":
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        added = record_payload(payload, args.ledger)
        print(f"PULSAR_V14_BET_LEDGER added={added}")
    else:
        settled_n = settle(args.ledger)
        out = write_report(args.ledger, args.report)
        print(f"PULSAR_V14_BET_LEDGER settled={settled_n} bets={out['bets']}")


if __name__ == "__main__":
    main()
