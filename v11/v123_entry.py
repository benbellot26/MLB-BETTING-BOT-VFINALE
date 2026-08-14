from __future__ import annotations

from .v123_runtime import activate

activate()

from . import config, core, journal, runner
from . import discord_v123, v123_bootstrap
from . import engine_v12 as engine

runner.discord = discord_v123
runner.historical_bootstrap = v123_bootstrap

_original_row = runner._row
_original_run = runner.run


def _row_v123(result, run_id, at, snapshot=None, source_replay=None):
    row = _original_row(result, run_id, at, snapshot, source_replay)
    live = {}
    for opt in result.get("options") or []:
        key = (str(opt.get("market")), str(opt.get("name")), opt.get("point"))
        live[key] = opt
    for saved in row.get("options") or []:
        src = live.get((str(saved.get("market")), str(saved.get("name")), saved.get("point"))) or {}
        saved["line_source"] = src.get("line_source")
        saved["execution_available"] = bool(src.get("execution_available"))
    row["baseline_schema"] = "v12.3-structural-v1"
    return row


def _summary_v123(report):
    if int(report.get("ledger_settled_this_run") or 0) <= 0:
        return True
    fin = report.get("finance") or {}
    return core.send_embed("📊 BILAN V12.3", [("Ledger confirmé",
        f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}**")], 5763719)


def self_test_v123():
    assert config.VERSION.startswith("12.3")
    assert .5 < engine.prob_home_win(5, 4) < .8
    j = engine.joint_score_matrix(4.5, 4, dispersion=3.0, env_sigma=.12)
    assert abs(sum(sum(x) for x in j)-1) < 1e-9
    assert len(j) >= config.MAX_RUNS_MATRIX
    model = v123_bootstrap.build_from_file()
    assert model.get("status") in {"PASS", "FAIL", "COLLECTING", "INCOMPATIBLE_BASELINE"}
    assert (model.get("metadata") or {}).get("test_used_for_activation") is False
    print("SELF-TEST V12.3 METHODOLOGY AUDIT OK")


def run_v123(snapshot_only=False):
    report = _original_run(snapshot_only=snapshot_only)
    if snapshot_only or not isinstance(report, dict):
        return report
    report["version"] = config.VERSION
    report.setdefault("production", {})["engine"] = "V12.3"
    report["production"]["claim"] = "LIVE_VALIDATED" if (report.get("production_evidence") or {}).get("passes") else "COLLECTING"
    report.setdefault("methodology", {}).update({
        "generation": "V12.3 methodology-audit-v1",
        "event_matching": "team identity + closest commence_time within strict tolerance",
        "starter_model": "current season + N-1/N-2 prior affects structural run means",
        "validation_parity": "production and Champion/Challenger share compose_runtime",
        "canonical_research_boundary": "sharp-only RL/Total are analysis-only and excluded from canonical training",
        "historical_evidence": "legacy V10 1,801-game data are diagnostic only until a V12.3 structural baseline exists",
        "execution_freshness": f"Winamax quote timestamp required; max age {getattr(config, 'V123_MAX_WINAMAX_AGE_MIN', 15):g} min",
    })
    journal.write_report(report)
    return report


runner._row = _row_v123
runner._summary = _summary_v123
runner.self_test = self_test_v123
runner.run = run_v123


if __name__ == "__main__":
    runner.main()
