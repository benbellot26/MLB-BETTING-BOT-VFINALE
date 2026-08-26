from v14.governance import assess_challenger, promotion_contract


def champion():
    return {
        "overall": {"brier": .235, "log_loss": .665},
        "markets": {"ML_HOME": {"brier": .240}, "TOTAL_OVER": {"brier": .230}},
    }


def challenger_good():
    return {
        "holdout_games": 150,
        "overall": {"brier": .231, "log_loss": .658, "max_abs_calibration_bias_pp": 2.0},
        "markets": {"ML_HOME": {"brier": .238}, "TOTAL_OVER": {"brier": .229}},
        "validation": "chronological_holdout",
        "data_leakage_detected": False,
    }


def test_good_challenger_is_only_eligible_not_auto_promoted():
    decision = assess_challenger(champion(), challenger_good()).as_dict()
    assert decision["eligible"] is True
    assert decision["automatic_promotion"] is False
    assert decision["requires_manual_review"] is True


def test_market_regression_blocks_promotion():
    c = challenger_good(); c["markets"]["TOTAL_OVER"]["brier"] = .240
    decision = assess_challenger(champion(), c)
    assert decision.eligible is False
    assert "market_regression:TOTAL_OVER" in decision.reasons


def test_leakage_or_random_split_blocks_promotion():
    c = challenger_good(); c["validation"] = "random_split"; c["data_leakage_detected"] = True
    decision = assess_challenger(champion(), c)
    assert decision.eligible is False
    assert "invalid_validation_protocol" in decision.reasons
    assert "leakage_gate_failed" in decision.reasons


def test_contract_forbids_automatic_mutation():
    contract = promotion_contract()
    assert contract["automatic_promotion"] is False
    assert contract["production_mutation_allowed"] is False
