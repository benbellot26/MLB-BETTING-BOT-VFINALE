import json
from pathlib import Path

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.daily_summary import build_summary_embed


def _row(
    *,
    game_pk: str,
    analyzed_at: str,
    game_date: str,
    home_score: int,
    away_score: int,
    home_ml: float,
    over: float,
    total_line: float,
    target_date: str = "2026-09-01",
):
    return {
        "schema": "pulsar-v14-prediction-record-v7",
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "game_pk": game_pk,
        "target_date": target_date,
        "game_date": game_date,
        "analyzed_at": analyzed_at,
        "settled": True,
        "home_score": home_score,
        "away_score": away_score,
        "total_line": total_line,
        "probabilities": {
            "home_ml": home_ml,
            "away_ml": 1.0 - home_ml,
            "over": over,
            "under": 1.0 - over,
        },
    }


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_daily_summary_is_simple_and_uses_latest_pregame_snapshot(tmp_path):
    predictions = tmp_path / "predictions.jsonl"
    performance = tmp_path / "performance.json"
    certification = tmp_path / "certification.json"

    rows = [
        # Older snapshot for game 1 predicts the wrong ML side; it must be ignored.
        _row(
            game_pk="1",
            analyzed_at="2026-09-01T18:00:00+00:00",
            game_date="2026-09-01T20:00:00+00:00",
            home_score=5,
            away_score=3,
            home_ml=0.40,
            over=0.55,
            total_line=7.5,
        ),
        _row(
            game_pk="1",
            analyzed_at="2026-09-01T19:30:00+00:00",
            game_date="2026-09-01T20:00:00+00:00",
            home_score=5,
            away_score=3,
            home_ml=0.60,
            over=0.55,
            total_line=7.5,
        ),
        _row(
            game_pk="2",
            analyzed_at="2026-09-01T20:30:00+00:00",
            game_date="2026-09-01T21:00:00+00:00",
            home_score=2,
            away_score=4,
            home_ml=0.70,
            over=0.40,
            total_line=7.0,
        ),
        _row(
            game_pk="3",
            analyzed_at="2026-09-01T21:30:00+00:00",
            game_date="2026-09-01T22:00:00+00:00",
            home_score=4,
            away_score=3,
            home_ml=0.40,
            over=0.60,
            total_line=7.0,
        ),
    ]
    _write_jsonl(predictions, rows)
    performance.write_text(json.dumps({"certification_cohort": {"games": 42}}), encoding="utf-8")
    certification.write_text(json.dumps({"certified": False, "betting_status": "RESEARCH_ONLY"}), encoding="utf-8")

    embed = build_summary_embed(
        predictions_path=predictions,
        performance_path=performance,
        certification_path=certification,
    )
    text = embed["description"]

    assert embed["title"] == "📊 PULSAR V14 — 01/09/2026"
    assert "**3 matchs analysés**" in text
    assert "**Moneyline** : 1 ✅  2 ❌  — **33.3%**" in text
    assert "**Total O/U** : 2 ✅  0 ❌ • 1 push — **100.0%**" in text
    assert "**ML + Total : 3/5 corrects — 60.0%**" in text
    assert "Matchs stricts : **42/600**" in text
    assert "Statut : **🧪 RECHERCHE**" in text
    assert "Brier" not in text
    assert "LogLoss" not in text
    assert "ECE" not in text


def test_daily_summary_fails_soft_when_no_settled_prediction_exists(tmp_path):
    predictions = tmp_path / "predictions.jsonl"
    performance = tmp_path / "performance.json"
    certification = tmp_path / "certification.json"
    predictions.write_text("", encoding="utf-8")
    performance.write_text("{}", encoding="utf-8")
    certification.write_text("{}", encoding="utf-8")

    embed = build_summary_embed(
        predictions_path=predictions,
        performance_path=performance,
        certification_path=certification,
    )

    assert embed["title"] == "📊 PULSAR V14 — BILAN QUOTIDIEN"
    assert embed["description"] == "Aucun nouveau match réglé."
