from __future__ import annotations

import json
import os

from .v123_runtime import activate

activate()

from . import config, core, journal, runner, shadow_v115, pro_model, predictive_v124
from . import discord_v123, v123_bootstrap, v124_research_monitor
from . import engine_v12 as engine

runner.discord = discord_v123
runner.historical_bootstrap = v123_bootstrap

_original_row = runner._row
_original_run = runner.run
_original_send = runner._send
_original_analyze = engine.analyze
_shadow_context_enabled = True


def _analyze_with_shadows(game, event, as_of=None):
    result = _original_analyze(game, event, as_of=as_of)
    if not _shadow_context_enabled:
        return result

    shadow115 = None
    if shadow_v115.enabled():
        try:
            shadow115 = shadow_v115.analyze(game, event, as_of=as_of)
            shadow115["comparison"] = shadow_v115.compare(result, shadow115)
            result["shadow_v115"] = shadow115
        except Exception as exc:
            core.logging.exception("V11.5 shadow impossible gamePk=%s", game.get("gamePk"))
            shadow115 = {
                "enabled": True,
                "version": shadow_v115.VERSION,
                "source_commit": shadow_v115.SOURCE_COMMIT,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "options": [],
                "comparison": {"exact_common_options": 0},
            }
            result["shadow_v115"] = shadow115

    if predictive_v124.enabled():
        try:
            result["shadow_v124"] = predictive_v124.analyze(result, shadow115)
        except Exception as exc:
            core.logging.exception("V12.4 predictive shadow impossible gamePk=%s", game.get("gamePk"))
            result["shadow_v124"] = {
                "enabled": True,
                "version": predictive_v124.VERSION,
                "schema": predictive_v124.SCHEMA,
                "research_only": True,
                "affects_v12_selection": False,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "variants": {},
                "implementation": predictive_v124.implementation_report(),
            }
    return result


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
        saved["reference_market"] = src.get("reference_market")
    row["baseline_schema"] = "v12.3-structural-v1"
    for key in ("shadow_v115", "shadow_v124"):
        shadow = result.get(key)
        if isinstance(shadow, dict):
            row[key] = shadow
    return row


def _summary_v123(report):
    monitor = report.get("research_monitor_v124") or {}
    if monitor:
        try:
            if not discord_v123.send_research_monitor(monitor):
                core.logging.warning("Research Monitor V12.4 Discord non publié; publication officielle non bloquée")
        except Exception:
            core.logging.exception("Research Monitor V12.4 Discord impossible; publication officielle non bloquée")
    if int(report.get("ledger_settled_this_run") or 0) <= 0:
        return True
    fin = report.get("finance") or {}
    return core.send_embed("📊 BILAN V12.3.2", [("Ledger confirmé",
        f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}**")], 5763719)


def _send_v123(results, portfolio, chosen, combo, health, report):
    # Keep the official sender untouched when games exist. If no games remain,
    # still allow the research/settlement summary to publish on a valid webhook.
    if results:
        return _original_send(results, portfolio, chosen, combo, health, report)
    if not core.discord_test():
        return False
    return bool(_summary_v123(report))


def _refresh_deferred_payload(report):
    path = runner.DISCORD_PAYLOAD
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["report"] = report
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return True
    except Exception:
        core.logging.exception("Impossible de rafraîchir le payload Discord avec le Research Monitor V12.4")
        return False


def self_test_v123():
    assert config.VERSION.startswith("12.3.2")
    assert .5 < engine.prob_home_win(5, 4) < .8
    j = engine.joint_score_matrix(4.5, 4, dispersion=3.0, env_sigma=.12)
    assert abs(sum(sum(x) for x in j)-1) < 1e-9
    assert len(j) >= config.MAX_RUNS_MATRIX
    model = v123_bootstrap.build_from_file()
    assert model.get("status") in {"PASS", "FAIL", "COLLECTING", "INCOMPATIBLE_BASELINE"}
    assert (model.get("metadata") or {}).get("test_used_for_activation") is False
    assert shadow_v115.VERSION.startswith("11.5-")
    assert .5 < shadow_v115.prob_home_win(5, 4) < .8
    assert predictive_v124.VERSION.startswith("12.4-")
    assert predictive_v124.implementation_report()["8_model_ensemble"]["status"] == "ADDED_RESEARCH_ONLY"
    assert v124_research_monitor.VERSION.startswith("v12.4-research-monitor-")
    assert getattr(pro_model, "CALIBRATION_GENERATION", "") == "hierarchical-challenger-v2"
    synthetic = {
        "options": [
            {"market": "RUNLINE", "name": "A", "point": 1.5, "p_effective": .62},
            {"market": "RUNLINE", "name": "B", "point": -1.5, "p_effective": .38},
        ]
    }
    shadow = {"options": [
        {"market": "RUNLINE", "name": "A", "point": 1.5, "p_effective": .58},
        {"market": "RUNLINE", "name": "B", "point": -1.5, "p_effective": .42},
    ]}
    cmp = shadow_v115.compare(synthetic, shadow)
    assert cmp["consensus_gt55"] == 1 and cmp["v12_only_gt55"] == 0
    print("SELF-TEST V12.3.2 + V11.5 SHADOW + CALIBRATION + V12.4 PREDICTIVE/MONITOR SHADOW OK")


def run_v123(snapshot_only=False):
    global _shadow_context_enabled
    previous_report = None if snapshot_only else v124_research_monitor.load_report(config.REPORT_FILE)
    previous_shadow_context = _shadow_context_enabled
    _shadow_context_enabled = not snapshot_only
    try:
        report = _original_run(snapshot_only=snapshot_only)
    finally:
        _shadow_context_enabled = previous_shadow_context
    if snapshot_only or not isinstance(report, dict):
        return report
    report["version"] = config.VERSION
    report.setdefault("production", {})["engine"] = "V12.3.2"
    report["production"]["claim"] = "LIVE_VALIDATED" if (report.get("production_evidence") or {}).get("passes") else "COLLECTING"
    report.setdefault("methodology", {}).update({
        "generation": "V12.3.2 value-selection-v1 + V12.4 predictive shadow",
        "event_matching": "team identity + closest commence_time within strict tolerance",
        "starter_model": "current season + N-1/N-2 prior affects structural run means",
        "validation_parity": "production and Champion/Challenger share compose_runtime",
        "canonical_research_boundary": "featured standard sharp RL/TOTAL may train calibration when Winamax is absent; alternate_spreads are excluded",
        "alternate_runlines": "event-level alternate_spreads; evaluates both +/-1.5 pairs when actually available",
        "selection": "informational recommendations use model confidence + conservative EV/edge + DQ + uncertainty + Kelly; Winamax never decides eligibility",
        "selection_reference_price": "fresh configured sharp books; exact side/point; second-best effective quote when >=2 books, otherwise single fresh sharp quote",
        "selection_price_floor": f"reference decimal odds >= {getattr(config, 'V123_MIN_REFERENCE_PRICE', 1.40):.2f}",
        "selection_confidence": f"RL >= {100*getattr(config, 'V123_MIN_CONFIDENCE_RUNLINE', .55):.0f}%; ML/TOTAL >= {100*getattr(config, 'V123_MIN_CONFIDENCE_ML', .58):.0f}%",
        "sharp_disagreement": "large model-vs-sharp disagreement reduces selection score but is not a hard directional veto",
        "calibration": "hierarchical market fallback + phase-specific challenger; identity vs Platt vs beta; holdout Brier/LogLoss/ECE; existing stack walk-forward remains mandatory",
        "historical_evidence": "legacy V10 1,801-game data are diagnostic only until a V12.3 structural baseline exists",
        "execution_freshness": f"Winamax is optional execution/display only; if shown, timestamp required and max age {getattr(config, 'V123_MAX_WINAMAX_AGE_MIN', 15):g} min",
        "v115_shadow": "frozen V11.5 probability challenger runs on the same game/market snapshot; research-only and never changes V12 selection",
        "v124_predictive_shadow": "8-module predictive challenger with ablation variants; research-only; V12.3.2 remains official Champion",
        "v124_research_monitor": "one latest settled pre-game snapshot per gamePk; per-market ablations, optimizer progress, disagreements and prior-run deltas; Discord monitor is non-blocking",
    })
    rows = journal.load_rows()
    try:
        report["shadow_challenger"] = shadow_v115.metrics(rows)
    except Exception as exc:
        core.logging.exception("Rapport V11.5 shadow impossible")
        report["shadow_challenger"] = {
            "version": shadow_v115.VERSION,
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "activation": {"affects_v12_selection": False},
        }
    try:
        report["calibration_health"] = pro_model.calibration_diagnostics(rows, pro_model.load_model())
    except Exception as exc:
        core.logging.exception("Rapport calibration V12 impossible")
        report["calibration_health"] = {
            "schema": "v12-calibration-diagnostics-v2",
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "affects_v12_selection": False,
        }
    try:
        report["predictive_v124"] = predictive_v124.metrics(rows)
    except Exception as exc:
        core.logging.exception("Rapport V12.4 predictive shadow impossible")
        report["predictive_v124"] = {
            "schema": "v12-4-shadow-metrics-v1", "version": predictive_v124.VERSION,
            "status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
            "activation": {"affects_v12_selection": False},
            "implementation": predictive_v124.implementation_report(),
        }
    try:
        report["research_monitor_v124"] = v124_research_monitor.build(report, previous_report, rows)
    except Exception as exc:
        core.logging.exception("Research Monitor V12.4 impossible")
        report["research_monitor_v124"] = {
            "schema": v124_research_monitor.SCHEMA, "version": v124_research_monitor.VERSION,
            "status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
            "research_only": True, "affects_v12_selection": False,
            "guardrails": {"selector_unchanged": True, "staking_unchanged": True, "discord_monitor_non_blocking": True},
        }
    journal.write_report(report)
    if os.getenv("V12_DEFER_DISCORD", "0") == "1":
        _refresh_deferred_payload(report)
    else:
        monitor = report.get("research_monitor_v124") or {}
        if monitor:
            try:
                discord_v123.send_research_monitor(monitor)
            except Exception:
                core.logging.exception("Research Monitor V12.4 Discord post-run impossible; production inchangée")
    return report


runner.engine.analyze = _analyze_with_shadows
runner._row = _row_v123
runner._summary = _summary_v123
runner._send = _send_v123
runner.self_test = self_test_v123
runner.run = run_v123


if __name__ == "__main__":
    runner.main()
