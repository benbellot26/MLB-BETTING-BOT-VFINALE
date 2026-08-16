from pathlib import Path

from v11 import v13_historical_distribution_prior as prior


def test_persisted_prior_is_distribution_only_and_validated():
    model = prior.load(Path("data/v13_historical_distribution_prior.json"))
    assert model["schema"] == "v13-historical-distribution-prior-v1"
    assert model["eligible_as_distribution_prior"] is True
    assert model["eligible_for_probability_calibration"] is False
    assert model["eligible_for_market_edge_training"] is False
    assert model["warm_games"] == 1724
    assert model["validation"]["nll_gain"] > 0
    assert model["test"]["nll_gain"] > 0
    assert model["walk_forward"]["passes"] is True


def test_validated_defaults_match_frozen_artifact():
    defaults = prior.validated_defaults(Path("data/v13_historical_distribution_prior.json"))
    assert defaults is not None
    assert defaults["dispersion"] == 3.5
    assert defaults["environment_sigma"] == 0.0
    assert defaults["source"] == "v13-historical-distribution-prior"
    assert defaults["warm_games"] == 1724


def test_rebuild_remains_eligible():
    rebuilt = prior.build()
    assert rebuilt["warm_games"] == 1724
    assert rebuilt["eligible_as_distribution_prior"] is True
    assert rebuilt["candidate"]["dispersion"] == 3.5
    assert rebuilt["validation"]["nll_gain"] > 0
    assert rebuilt["test"]["nll_gain"] > 0
