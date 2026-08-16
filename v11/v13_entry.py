from __future__ import annotations

# Load the hardened V12.3 runtime first, then replace only the probability
# contract. Existing data collection, score distribution, shadow challengers,
# delivery checkpoints and operational safeguards stay active.
from . import v123_entry as v123
from .v13_runtime import install

install()

from . import config, runner, discord_v13, core

# V13 changes the user-facing product to probability-first reporting while
# retaining the mature Discord transport and delivery checkpoints.
runner.discord = discord_v13


def _summary_v13(report):
    if int(report.get("ledger_settled_this_run") or 0) <= 0:
        return True
    fin = report.get("finance") or {}
    return core.send_embed("📊 BILAN V13", [("Ledger confirmé",
        f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}**")], 5763719)


def self_test_v13():
    from . import probability_contract_v13 as contract
    from . import calibration_baseball_v13 as cal
    from . import extra_innings_v13
    from . import v13_distribution_prior
    assert config.VERSION.startswith("13.1-")
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
    joint = [[.10,.10],[.20,.60]]
    # 20% regulation home win + 70% tie * neutral 50% = 55%.
    assert abs(extra_innings_v13.home_win_probability(joint)-.55) < 1e-9
    dist=v13_distribution_prior.load()
    assert dist.get("active") and dist.get("variant") == "dispersion_only"
    d,e,meta=v13_distribution_prior.apply(7.5,.08,"FINAL")
    assert abs(d-2.835691107635618) < 1e-12 and abs(e-.08) < 1e-12 and meta.get("active")
    d2,e2,meta2=v13_distribution_prior.apply(7.5,.08,"EARLY")
    assert d2 == 7.5 and e2 == .08 and not meta2.get("active")
    print("SELF-TEST V13.1 PROFESSIONAL PROBABILITY CONTRACT OK")


runner._summary = _summary_v13
runner.self_test = self_test_v13


if __name__ == "__main__":
    runner.main()
