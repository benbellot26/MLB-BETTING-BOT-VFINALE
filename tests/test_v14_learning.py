from v14.learning import learning_report


def row(game, p=.60, home_score=5, away_score=3, total=8.5):
    return {
        "game_pk": str(game), "model_generation": "pulsar-v14-context-v3",
        "analyzed_at": f"2026-08-{(game % 20)+1:02d}T18:00:00+00:00",
        "settled": True, "home_score": home_score, "away_score": away_score,
        "total_line": total,
        "probabilities": {"home_ml": p, "home_minus_1_5": p-.08, "away_minus_1_5": .25, "over": .57},
    }


def test_learning_is_evaluation_only_and_collects_small_sample():
    report=learning_report([row(i) for i in range(20)], "pulsar-v14-context-v3")
    assert report["mode"] == "EVALUATION_ONLY"
    assert report["production_mutation_allowed"] is False
    assert report["stage"] == "COLLECTING"


def test_learning_requires_large_history_before_challenger():
    report=learning_report([row(i) for i in range(220)], "pulsar-v14-context-v3")
    assert report["stage"] == "CHALLENGER_ELIGIBLE"
    assert "No automatic promotion" in report["promotion_policy"]


def test_learning_uses_latest_snapshot_per_game():
    rows=[row(1,p=.55), row(1,p=.75)]
    rows[0]["analyzed_at"]="2026-08-01T10:00:00+00:00"
    rows[1]["analyzed_at"]="2026-08-01T18:00:00+00:00"
    report=learning_report(rows,"pulsar-v14-context-v3")
    assert report["games"] == 1
    assert report["markets"]["ML_HOME"]["n"] == 1
