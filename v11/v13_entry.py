from __future__ import annotations

from . import v123_entry as v123
from .v13_runtime import install

install()

from . import config, runner, discord_v13, core, selector, storage, journal, v13_daily_tracking, v13_analytics_only
from . import v13_coverage_report, v13_probability_diagnostics
from . import calibration_baseball_v13 as calibration_v13
from . import probability_contract_v13 as probability_contract
runner.discord = discord_v13

# V13 remains a predictive-analytics product. The legacy selector is still run
# to compute useful diagnostics (reference price, conservative EV, DQ, score),
# but every actionable betting output is scrubbed before runner/storage sees it.
_original_allocate = selector.allocate
_original_update_clv = storage.update_clv
_original_settle_rows = journal.settle_rows
_original_run = runner.run
_original_send_persisted = runner.send_persisted


def _tracked_allocate(results, *args, **kwargs):
    out = _original_allocate(results, *args, **kwargs)
    v13_daily_tracking.capture_results(results, target_date=core.TARGET_DATE)
    return v13_analytics_only.suppress_allocation(results, out)


def _tracked_update_clv(results, analyzed_at=None):
    n = _original_update_clv(results, analyzed_at)
    v13_daily_tracking.observe_closing(results, analyzed_at)
    return n


def _tracked_settle_rows(rows):
    n = _original_settle_rows(rows)
    v13_daily_tracking.settle_from_journal(rows)
    return n


def _assert_v135_calibration_artifact():
    """Fail closed unless calibration belongs to the exact current model generation."""
    model=calibration_v13.load_model()
    bad_status=str(model.get("status") or "").upper() in {"ABSENT","INCOMPATIBLE","INVALID"}
    if (model.get("schema") != "v13-baseball-calibration-model-v2"
            or model.get("baseball_only") is not True
            or model.get("model_generation") != probability_contract.MODEL_GENERATION_FINGERPRINT
            or bad_status):
        raise SystemExit("V13.5.2 calibration artifact stale/incompatible: run `python -m v11.v13_train` before analysis")


def _write_postrun_diagnostics():
    """Persist non-actionable evidence views after the run without blocking Discord."""
    try:
        v13_coverage_report.main()
    except Exception:
        core.logging.exception("V13 coverage report impossible; analytics publication remains available")
    try:
        v13_probability_diagnostics.main()
    except Exception:
        core.logging.exception("V13 probability diagnostics impossible; analytics publication remains available")


def _run_v135(*args, **kwargs):
    _assert_v135_calibration_artifact()
    report = _original_run(*args, **kwargs)
    _write_postrun_diagnostics()
    return report


def _send_persisted_v135():
    # Discord publication is fail-closed if a stale/future code path manages to
    # re-introduce actionable betting state into the analytics payload.
    v13_analytics_only.assert_payload_file(runner.DISCORD_PAYLOAD)
    return _original_send_persisted()


selector.allocate = _tracked_allocate
# Redundant storage guard: even if a future runner bypasses the empty chosen
# list returned above, V13 cannot create PROPOSED betting ledger events.
storage.record_selected_bets = v13_analytics_only.disabled_record_selected_bets
runner.storage.record_selected_bets = v13_analytics_only.disabled_record_selected_bets
storage.update_clv = _tracked_update_clv
journal.settle_rows = _tracked_settle_rows
runner.run = _run_v135
runner.send_persisted = _send_persisted_v135


def _summary_v13(report):
    if int(report.get("ledger_settled_this_run") or 0) <= 0: return True
    fin = report.get("finance") or {}
    return core.send_embed("📊 BILAN V13", [("Ledger confirmé",
        f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}**")], 5763719)


def self_test_v13():
    from . import probability_contract_v13 as contract
    from . import calibration_baseball_v13 as cal
    from . import extra_innings_v13, v13_distribution_prior, v13_run_mean_runtime, v13_rich_run_shadow, uncertainty_v13
    assert config.VERSION.startswith("13.5")
    payload = contract.option_contract_payload(p_baseball_raw=.62,p_baseball_calibrated=.59,p_market=.56,p_posterior=.58,
        calibration_source="test",calibration_n=500,interval_low=.54,interval_high=.64)
    assert payload["p_baseball_calibrated"] == .59 and abs(payload["model_market_gap"]-.03) < 1e-9
    contract.assert_no_market_leakage(payload)
    row={}; contract.attach_contract(row); assert contract.row_is_predictively_compatible(row)
    assert row.get("model_generation_fingerprint") == contract.MODEL_GENERATION_FINGERPRINT
    p, source, n = cal.calibrate(.61, "ML", "FINAL", {"calibrators": {}})
    assert abs(p-.61) < 1e-9 and source == "identity" and n == 0
    c={"calibrators":{"GLOBAL":{"active":True,"method":"platt","a":0,"b":.5,"n":999},
                      "MARKET:ML":{"n":40},"PHASE:EARLY:ML":{"n":30},"PHASE:FINAL:ML":{"n":7}}}
    assert cal.calibrate(.61,"ML","FINAL",c)[0] == .61 and cal.calibrate(.61,"ML","FINAL",c)[2] == 7
    u_hi=uncertainty_v13.empirical_interval(.55,calibration_n=30,phase_n=30,market_n=40,data_quality=.95,sharp_dispersion=.01)
    u_lo=uncertainty_v13.empirical_interval(.55,calibration_n=30,phase_n=30,market_n=40,data_quality=.60,sharp_dispersion=.20)
    assert u_lo["sigma"] >= u_hi["sigma"] and u_hi["phase_n"] == 30
    assert u_hi["market_disagreement_affects_baseball_interval"] is False
    joint = [[.10,.10],[.20,.60]]; assert abs(extra_innings_v13.home_win_probability(joint)-.55) < 1e-9

    dist=v13_distribution_prior.load()
    d,e,meta=v13_distribution_prior.apply(7.5,.08,"FINAL")
    if dist.get("active"):
        assert dist.get("model_generation") == contract.MODEL_GENERATION_FINGERPRINT
        assert dist.get("historical_candidate_active") is True
        assert int(dist.get("exact_final_games") or 0) >= int(dist.get("exact_transfer_required_games") or 20)
        assert dist.get("exact_transfer_status") == "PASS_FINAL_ONLY"
        assert abs(d-float(dist.get("dispersion"))) < 1e-12 and abs(e-.08)<1e-12 and meta.get("active")
    else:
        assert d==7.5 and e==.08 and not meta.get("active")
    d2,e2,meta2=v13_distribution_prior.apply(7.5,.08,"EARLY"); assert d2==7.5 and e2==.08 and not meta2.get("active")

    mean_prior=v13_run_mean_runtime.load()
    required=int(mean_prior.get("exact_transfer_required_games") or 20)
    observed=int(mean_prior.get("exact_final_games") or mean_prior.get("exact_games") or 0)
    status=str(mean_prior.get("exact_transfer_status") or "")
    assert str(mean_prior.get("phase_scope") or "FINAL").upper() == "FINAL"
    if mean_prior.get("active"):
        assert mean_prior.get("model_generation") == contract.MODEL_GENERATION_FINGERPRINT
        assert mean_prior.get("historical_candidate_active") is True
        assert observed >= required
        assert status == "PASS_FINAL_ONLY"
        h,a,m=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",mean_prior)
        assert m.get("active") and (h,a) != (5.0,4.0)
    else:
        h,a,m=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",mean_prior)
        assert not m.get("active") and h==5.0 and a==4.0
        if mean_prior.get("model_generation") == contract.MODEL_GENERATION_FINGERPRINT:
            assert observed < required or status != "PASS_FINAL_ONLY" or mean_prior.get("historical_candidate_active") is not True
    h2,a2,m2=v13_run_mean_runtime.apply_pair(5.0,4.0,"LATE",mean_prior); assert h2==5.0 and a2==4.0 and not m2.get("active")

    rich=v13_rich_run_shadow.load(); assert rich.get("active_for_production") is not True
    assert v13_daily_tracking._band(.004) == "0-1%" and v13_daily_tracking._band(.12) == ">=10%"
    rec={"p_effective":.60,"probability_interval_low":.52,"model_uncertainty":.01}
    assert abs(selector.conservative_probability(rec)-.52)<1e-12
    assert storage.record_selected_bets([], {}, "test", "test", core.TARGET_DATE) == 0
    v13_analytics_only.assert_payload({"results": [], "chosen": [], "combo": {}})
    print("SELF-TEST V13.6 EVIDENCE + GENERATION-FINGERPRINT + NATIVE CALIBRATION + ANALYTICS-ONLY GATES OK")


runner._summary = _summary_v13
runner.self_test = self_test_v13

if __name__ == "__main__": runner.main()
