from __future__ import annotations

"""Simple daily Discord summary built from already-settled V14 evidence.

The summary is informational only. It never changes predictions, certification,
selection, staking, calibration or any research artifact.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID, VERSION
from .acquisition import parse_time
from .discord import send_embed

PREDICTIONS = Path("data/v14_predictions.jsonl")
PERFORMANCE = Path("data/v14_performance.json")
CERTIFICATION = Path("data/v14_betting_certification.json")


def _read_json(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _row_policy(row: dict[str, Any]) -> str | None:
    direct = row.get("probability_policy_id")
    if direct:
        return str(direct)
    nested = (row.get("calibration") or {}).get("probability_policy_id")
    return str(nested) if nested else None


def _strictly_pregame(row: dict[str, Any]) -> bool:
    try:
        return parse_time(row.get("analyzed_at")) < parse_time(row.get("game_date"))
    except Exception:
        return False


def _canonical_rows(rows: list[dict[str, Any]], target_date: str) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if row.get("settled") is True
        and row.get("model_generation") == MODEL_GENERATION
        and _row_policy(row) == PROBABILITY_POLICY_ID
        and str(row.get("target_date") or "") == target_date
        and _strictly_pregame(row)
    ]
    latest: dict[str, dict[str, Any]] = {}
    for row in eligible:
        game_pk = str(row.get("game_pk") or "")
        if not game_pk:
            continue
        current = latest.get(game_pk)
        if current is None:
            latest[game_pk] = row
            continue
        try:
            if parse_time(row.get("analyzed_at")) > parse_time(current.get("analyzed_at")):
                latest[game_pk] = row
        except Exception:
            continue
    return sorted(latest.values(), key=lambda row: (str(row.get("game_date") or ""), str(row.get("game_pk") or "")))


def _latest_settled_date(rows: list[dict[str, Any]]) -> str | None:
    dates = {
        str(row.get("target_date") or "")
        for row in rows
        if row.get("settled") is True
        and row.get("model_generation") == MODEL_GENERATION
        and _row_policy(row) == PROBABILITY_POLICY_ID
        and _strictly_pregame(row)
        and str(row.get("target_date") or "")
    }
    return max(dates) if dates else None


def _pct(wins: int, losses: int) -> str:
    decisions = wins + losses
    return f"{100 * wins / decisions:.1f}%" if decisions else "—"


def _grade_day(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ml_wins = ml_losses = 0
    total_wins = total_losses = total_pushes = 0
    for row in rows:
        try:
            home_score = int(row["home_score"])
            away_score = int(row["away_score"])
        except Exception:
            continue
        probabilities = row.get("probabilities") or {}
        try:
            home_ml = float(probabilities.get("home_ml"))
            away_ml = float(probabilities.get("away_ml"))
            predicted_home = home_ml >= away_ml
            actual_home = home_score > away_score
            if predicted_home == actual_home:
                ml_wins += 1
            else:
                ml_losses += 1
        except Exception:
            pass

        try:
            line = float(row.get("total_line"))
            over = float(probabilities.get("over"))
            under = float(probabilities.get("under"))
            total = home_score + away_score
            if abs(total - line) < 1e-9:
                total_pushes += 1
            else:
                predicted_over = over >= under
                actual_over = total > line
                if predicted_over == actual_over:
                    total_wins += 1
                else:
                    total_losses += 1
        except Exception:
            pass

    decisions = ml_wins + ml_losses + total_wins + total_losses
    wins = ml_wins + total_wins
    return {
        "games": len(rows),
        "ml": {"wins": ml_wins, "losses": ml_losses, "accuracy": _pct(ml_wins, ml_losses)},
        "total": {
            "wins": total_wins,
            "losses": total_losses,
            "pushes": total_pushes,
            "accuracy": _pct(total_wins, total_losses),
        },
        "combined": {"wins": wins, "decisions": decisions, "accuracy": f"{100 * wins / decisions:.1f}%" if decisions else "—"},
    }


def _display_status(value: Any, certified: bool) -> str:
    if certified:
        return "✅ CERTIFIÉ"
    raw = str(value or "RESEARCH_ONLY").upper()
    if raw == "RESEARCH_ONLY":
        return "🧪 RECHERCHE"
    return f"🧪 {raw.replace('_', ' ')}"


def build_summary_embed(
    *,
    predictions_path: Path | str = PREDICTIONS,
    performance_path: Path | str = PERFORMANCE,
    certification_path: Path | str = CERTIFICATION,
    target_date: str | None = None,
) -> dict[str, Any]:
    rows = _read_jsonl(predictions_path)
    day = target_date or _latest_settled_date(rows)
    performance = _read_json(performance_path)
    certification = _read_json(certification_path)
    strict_games = int(((performance.get("certification_cohort") or {}).get("games")) or 0)
    certified = certification.get("certified") is True
    status = _display_status(certification.get("betting_status"), certified)

    if not day:
        return {
            "title": "📊 PULSAR V14 — BILAN QUOTIDIEN",
            "description": "Aucun nouveau match réglé.",
            "color": 0x5865F2,
            "footer": {"text": f"Pulsar V14.{VERSION} • bilan automatique"},
        }

    canonical = _canonical_rows(rows, day)
    grade = _grade_day(canonical)
    ml = grade["ml"]
    total = grade["total"]
    combined = grade["combined"]
    push_suffix = f" • {total['pushes']} push" if total["pushes"] else ""
    date_label = datetime.fromisoformat(day).strftime("%d/%m/%Y")

    return {
        "title": f"📊 PULSAR V14 — {date_label}",
        "description": (
            f"**{grade['games']} matchs analysés**\n\n"
            f"🏆 **Moneyline** : {ml['wins']} ✅  {ml['losses']} ❌  — **{ml['accuracy']}**\n"
            f"📈 **Total O/U** : {total['wins']} ✅  {total['losses']} ❌{push_suffix} — **{total['accuracy']}**\n\n"
            f"🎯 **ML + Total : {combined['wins']}/{combined['decisions']} corrects — {combined['accuracy']}**\n"
            f"🧪 Matchs stricts : **{strict_games}/600**\n"
            f"🔐 Statut : **{status}**"
        ),
        "color": 0xE91E63,
        "footer": {
            "text": "Bilan automatique des projections réglées • ce message ne constitue pas une certification de paris"
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def send_daily_summary(**kwargs: Any) -> bool:
    return send_embed(build_summary_embed(**kwargs), username="Pulsar V14 • Daily")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the simple settled Pulsar V14 daily summary to Discord")
    parser.add_argument("--predictions", default=str(PREDICTIONS))
    parser.add_argument("--performance", default=str(PERFORMANCE))
    parser.add_argument("--certification", default=str(CERTIFICATION))
    parser.add_argument("--date")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()
    kwargs = {
        "predictions_path": args.predictions,
        "performance_path": args.performance,
        "certification_path": args.certification,
        "target_date": args.date,
    }
    embed = build_summary_embed(**kwargs)
    if args.print_only:
        print(json.dumps(embed, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if not send_embed(embed, username="Pulsar V14 • Daily"):
        raise SystemExit("Pulsar V14 daily Discord summary publication incomplete")
    print("PULSAR_V14_DAILY_DISCORD sent=true")


if __name__ == "__main__":
    main()
