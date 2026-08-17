from __future__ import annotations

from . import v123_entry as v123
from .v13_runtime import install

install()

from . import config, runner, discord_v13, core, selector, storage, journal, v13_daily_tracking
runner.discord = discord_v13

# Observation-only hooks. They never alter probabilities, gates, stakes or picks.
_original_allocate = selector.allocate
_original_update_clv = storage.update_clv
_original_settle_rows = journal.settle_rows


def _tracked_allocate(results, *args, **kwargs):
    out = _original_allocate(results, *args, **kwargs)
    v13_daily_tracking.capture_results(results, target_date=core.TARGET_DATE)
    return out


def _tracked_update_clv(results, analyzed_at=None):
    n = _original_update_clv(results, analyzed_at)
    v13_daily_tracking.observe_closing(results, analyzed_at)
    return n


def _tracked_settle_rows(rows):
    n = _original_settle_rows(rows)
    v13_daily_tracking.settle_from_journal(rows)
    return n


selector.allocate = _tracked_allocate
storage.update_clv = _tracked_update_clv
journal.settle_rows = _tracked_settle_rows


def _summary_v13(report):
    if int(report.get("ledger_settled_this_run") or 0) <= 0: return True
    fin = report.get("finance") or {}
    return core.send_embed("📊 BILAN V13", [("Ledger confirmé",
        f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}**")], 5763719)


def self_test_v13():
    from . import probability_contract_v13 as contract
    from . import calibration_baseball_v13 as cal
    from . import extra_innings_v13, v13_distribution_prior, v13_run_mean_runtime, v13_rich_run_shadow
    assert config.VERSION.startswith("13.3-")
    payload = contract.option_contract_payload(p_baseball_raw=.62,p_baseball_calibrated=.59,p_market=.56,p_posterior=.58,
        calibration_source="test",calibration_n=500,interval_low=.54,interval_high=.64)
    assert payload["p_baseball_calibrated"] == .59 and abs(payload["model_market_gap"]-.03) < 1e-9
    contract.assert_no_market_leakage(payload)
    p, source, n = cal.calibrate(.61, "ML", "FINAL", {"calibrators": {}})
    assert abs(p-.61) < 1e-9 and source == "identity" and n == 0
    joint = [[.10,.10],[.20,.60]]; assert abs(extra_innings_v13.home_win_probability(joint)-.55) < 1e-9
    dist=v13_distribution_prior.load(); assert dist.get("active") and dist.get("variant") == "dispersion_only"
    d,e,meta=v13_distribution_prior.apply(7.5,.08,"FINAL"); assert abs(d-2.835691107635618)<1e-12 and abs(e-.08)<1e-12 and meta.get("active")
    d2,e2,meta2=v13_distribution_prior.apply(7.5,.08,"EARLY"); assert d2==7.5 and e2==.08 and not meta2.get("active")
    mean_prior=v13_run_mean_runtime.load(); assert mean_prior.get("active") and mean_prior.get("exact_games",0)>=20
    h,a,m=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",mean_prior); assert m.get("active") and abs(h-5.0)<=.75 and abs(a-4.0)<=.75
    h2,a2,m2=v13_run_mean_runtime.apply_pair(5.0,4.0,"LATE",mean_prior); assert h2==5.0 and a2==4.0 and not m2.get("active")
    rich=v13_rich_run_shadow.load(); assert rich.get("active_for_production") is not True
    assert v13_daily_tracking._band(.004) == "0-1%" and v13_daily_tracking._band(.12) == ">=10%"
    print("SELF-TEST V13.3 PROFESSIONAL PROBABILITY + RICH RUN SHADOW + DAILY TRACKING OK")


runner._summary = _summary_v13
runner.self_test = self_test_v13

if __name__ == "__main__": runner.main()
