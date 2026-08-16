from __future__ import annotations

# Load the hardened V12.3 runtime first, then replace only the probability
# contract. Existing data collection, score distribution, shadow challengers,
# delivery checkpoints and operational safeguards stay active.
from . import v123_entry as v123
from .v13_runtime import install

install()

from . import config, runner


def self_test_v13():
    from . import probability_contract_v13 as contract
    from . import calibration_baseball_v13 as cal
    assert config.VERSION.startswith("13.0-")
    payload = contract.option_contract_payload(
        p_baseball_raw=.62,
        p_baseball_calibrated=.59,
        p_market=.56,
        p_posterior=.58,
        calibration_source="test",
        calibration_n=500,
        interval_low=.54,
        interval_high=.64,
    )
    assert payload["p_baseball_calibrated"] == .59
    assert abs(payload["model_market_gap"]-.03) < 1e-9
    contract.assert_no_market_leakage(payload)
    model = {"calibrators": {}}
    p, source, n = cal.calibrate(.61, "ML", "FINAL", model)
    assert abs(p-.61) < 1e-9 and source == "identity" and n == 0
    print("SELF-TEST V13 PROFESSIONAL PROBABILITY CONTRACT OK")


runner.self_test = self_test_v13


if __name__ == "__main__":
    runner.main()
