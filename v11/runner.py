from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from . import config, core, selector, journal, storage, data_quality, pro_model, historical_bootstrap
from . import engine_v12 as engine
from . import discord_v12 as discord

DISCORD_PAYLOAD = storage.RUNTIME_DIR/"discord_payload.json"


def _historical_reference():
    p = Path("data/mlb_backtest_2026_report.json")
    if not p.exists(): return None
    try:
        d = json.loads(p.read_text(encoding="utf-8")); x = d.get("v10_ml") or {}
        b = historical_bootstrap.load_model(); meta = b.get("metadata") or {}
        return {"source": "frozen 2026 baseball bootstrap; FINAL-only; not betting-profitability evidence",
                "ml_accuracy": x.get("accuracy"), "ml_brier": x.get("brier"),
                "ml_logloss": x.get("logloss"), "historical_odds_used": (d.get("methodology") or {}).get("historical_odds_used"),
                "bootstrap": {"version": b.get("version"), "status": b.get("status"), "active": bool(b.get("active")),
                              "games": meta.get("games"), "split": meta.get("split"), "phase_scope": b.get("phase_scope"),
                              "run_prior_active": bool((b.get("run_correction") or {}).get("active")),
                              "dispersion_active": bool((b.get("dispersion") or {}).get("active")),
                              "environment_active": bool((b.get("environment") or {}).get("active")),
                              "betting_profitability_claim": bool(meta.get("betting_profitability_claim", False))}}
    except Exception: return None


def _row(r, run_id, at, snapshot=None, source_replay=None):
    keys = ("market", "name", "point", "is_canonical_line", "p_structural", "p_learned", "p_model", "p_effective",
            "p_win", "p_push", "p_push_model", "p_market", "refs", "sharp_books", "sharp_weight",
            "sharp_dispersion", "sharp_robustness", "sharp_effective_n", "quality", "model_uncertainty",
            "calibration_source", "phase_model", "data_quality", "selection_score", "result", "brier", "logloss",
            "sharp_brier", "sharp_logloss")
    return {"schema": config.SCHEMA_VERSION, "engine_version": config.VERSION, "feature_schema": config.FEATURE_SCHEMA_VERSION,
            "feature_schema_hash": pro_model.feature_schema_hash(), "run_id": run_id, "analyzed_at": at,
            "target_date": core.TARGET_DATE, "game_pk": r.get("game_pk"), "game_date": (r.get("game") or {}).get("gameDate"),
            "home": r["ctx"]["home"], "away": r["ctx"]["away"], "phase": r.get("phase"), "as_of": at,
            "structural_home_runs": round(core.num(r.get("structural_hmu")), 4),
            "structural_away_runs": round(core.num(r.get("structural_amu")), 4),
            "projected_home_runs": round(core.num(r.get("hmu")), 4), "projected_away_runs": round(core.num(r.get("amu")), 4),
            "p_home": round(core.num(r.get("p_home"), .5), 6), "quality": round(core.num(r.get("quality")), 4),
            "data_quality": data_quality.assess(r), "features": r.get("features"), "canonical_lines": r.get("canonical_lines"),
            "starters": {"home": r["ctx"].get("home_starter"), "away": r["ctx"].get("away_starter")},
            "lineups": {"home": r["ctx"].get("home_lineup"), "away": r["ctx"].get("away_lineup")},
            "sharp_ml": r.get("con"), "model": r.get("model"), "raw_snapshot": str(snapshot) if snapshot else None,
            "source_replay": str(source_replay) if source_replay else None,
            "options": [{k: o.get(k) for k in keys}|{"winamax_eval": o.get("winamax_eval")} for o in r.get("options") or []],
            "official_bets": journal.capture_bets(r), "result_status": "PENDING", "winner": None,
            "home_score": None, "away_score": None, "settled_at": None}


def _summary(report):
    if int(report.get("ledger_settled_this_run") or 0) <= 0: return True
    fin = report.get("finance") or {}
    return core.send_embed("📊 BILAN V12.2", [("Ledger confirmé",
        f"{fin.get('wins',0)}V-{fin.get('losses',0)}D-{fin.get('pushes',0)}P • P/L **{core.num(fin.get('profit_units')):+.2f}u** • ROI **{core.pct(fin.get('roi'))}**")], 5763719)


def _send(results, portfolio, chosen, combo, health, report):
    if not core.discord_test() or not results: return False
    ok = True
    for r in results: ok = bool(discord.send_game(r, portfolio)) and ok
    ok = bool(discord.send_top(results)) and ok
    ok = bool(discord.send_plan(chosen, combo, portfolio, [])) and ok
    ok = bool(discord.send_health(health)) and ok
    ok = bool(_summary(report)) and ok
    return ok


def _write_discord_payload(results, portfolio, chosen, combo, health, report):
    DISCORD_PAYLOAD.parent.mkdir(parents=True, exist_ok=True)
    DISCORD_PAYLOAD.write_text(json.dumps({"results": results, "portfolio": portfolio, "chosen": chosen,
                                           "combo": combo, "health": health, "report": report},
                                          ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def send_persisted():
    if not DISCORD_PAYLOAD.exists(): raise SystemExit(f"Payload Discord absent: {DISCORD_PAYLOAD}")
    p = json.loads(DISCORD_PAYLOAD.read_text(encoding="utf-8"))
    if not _send(p.get("results") or [], p.get("portfolio") or {}, p.get("chosen") or [], p.get("combo") or {}, p.get("health") or {}, p.get("report") or {}):
        raise SystemExit("Publication Discord incomplète: ledger conservé en PROPOSED")
    n = storage.mark_run_published((p.get("report") or {}).get("run_id"))
    print(f"PUBLISHED recommendations={n}")


def self_test():
    assert config.VERSION.startswith("12.2")
    assert .5 < engine.prob_home_win(5, 4) < .8
    j = engine.joint_score_matrix(4.5, 4, dispersion=3.0, env_sigma=.12)
    assert abs(sum(sum(x) for x in j)-1) < 1e-9
    assert len(j) >= config.MAX_RUNS_MATRIX
    q1, q2, qp, _ = pro_model.calibrate_triplet("TOTAL", .62, .38, .08, {"active": False}, "FINAL")
    assert abs(q1+q2-1) < 1e-12 and 0 <= qp < 1
    print("SELF-TEST V12.2 PROFESSIONAL VALIDATION OK")


def _prepare_run():
    at = datetime.now(timezone.utc).isoformat()
    run_id = hashlib.sha1(f"{at}|{core.TARGET_DATE}|{config.VERSION}".encode()).hexdigest()[:16]
    source = storage.source_replay_path(core.TARGET_DATE, run_id)
    core.start_http_recording(source, run_id, at, core.TARGET_DATE)
    return at, run_id, source


def run(snapshot_only=False):
    if not core.ODDS_KEY: raise SystemExit("ODDS_API_KEY absente")
    at, run_id, source = _prepare_run()
    rows = journal.load_rows(); results = []; games = []; events = []; matches = {}
    try:
        journal.settle_rows(rows)
        ledger_settled = storage.settle_from_journal(rows)
        games = core.mlb_schedule(core.TARGET_DATE); events = core.odds_api(); matches = core.match_odds_events(games, events)
        wanted = None
        if snapshot_only:
            wanted = {str(v.get("game_pk")) for v in storage.open_recommendations().values() if v.get("game_pk") is not None}
        for g in games:
            gid = str(g.get("gamePk"))
            if wanted is not None and gid not in wanted: continue
            try:
                if core.parse_dt(g.get("gameDate")) <= core.parse_dt(at): continue
            except Exception: continue
            e = matches.get(gid)
            if not e: continue
            try: results.append(engine.analyze(g, e, as_of=at))
            except Exception: core.logging.exception("Analyse V12.2 impossible gamePk=%s", g.get("gamePk"))
    finally:
        core.stop_http_recording()
    raw = storage.snapshot_run(games, events, run_id, at, core.TARGET_DATE, source)
    storage.capture_market_snapshot(events, run_id, at, core.TARGET_DATE)
    storage.update_clv(results, at)
    if snapshot_only:
        journal.write_rows(rows)
        core.logging.info("V12.2 snapshot-only | tracked=%d", len(results))
        return {"run_id": run_id, "results": len(results), "source_replay": str(source)}

    portfolio, chosen, combo, _ = selector.allocate(results, core.UNIT, core.BANKROLL, storage.open_recommendations(), core.TARGET_DATE)
    storage.record_selected_bets(chosen, combo, run_id, at, core.TARGET_DATE)
    rows.extend(_row(r, run_id, at, raw, source) for r in results)
    journal.write_rows(rows)
    health = data_quality.health_report(results, len(games), len(matches))
    finance = storage.ledger_summary(); model = pro_model.load_model(); evidence = pro_model.production_evidence_gate(finance)
    bootstrap = historical_bootstrap.load_model()
    report = {"version": config.VERSION, "schema": config.SCHEMA_VERSION, "run_id": run_id, "analyzed_at": at,
              "target_date": core.TARGET_DATE, "scheduled_games": len(games), "matched_events": len(matches),
              "remaining_games_analyzed": len(results), "ledger_settled_this_run": ledger_settled,
              "production": {"engine": "V12.2", "claim": "COLLECTING" if not evidence["passes"] else "LIVE_VALIDATED"},
              "performance": journal.metrics(rows), "finance": finance, "production_evidence": evidence, "data_health": health,
              "model": {"version": model.get("version"), "active": bool(model.get("active")),
                        "artifact_status": model.get("artifact_status"), "artifact_error": model.get("artifact_error"),
                        "run_dispersion": pro_model.model_dispersion(model)[0],
                        "environment_sigma": pro_model.model_environment_sigma(model)[0],
                        "historical_bootstrap": {"version": bootstrap.get("version"), "status": bootstrap.get("status"),
                                                 "active": bool(bootstrap.get("active")), "phase_scope": bootstrap.get("phase_scope")}},
              "historical_reference": _historical_reference(),
              "methodology": {"runs_model": "immutable structural baseline + validated FINAL historical prior fallback + phase-specific live residual",
                              "distribution": "correlated NB mixture; validated historical FINAL fallback; dynamic tail truncation",
                              "calibration": "phase-specific side + push calibration; end-to-end promotion gate",
                              "uncertainty": "empirical phase/market reliability bins + market disagreement + DQ penalty",
                              "execution": "fixed Winamax canonical lines for evaluation; all executable lines for selection",
                              "staking": "bankroll-aware fractional Kelly; official combos disabled",
                              "ledger": "PROPOSED -> PUBLISHED -> CONFIRMED_PLACED -> SETTLED",
                              "historical_evidence": "1801-game frozen baseball bootstrap is FINAL-only and never counted as betting-profitability/CLV evidence",
                              "raw_archive": str(raw), "source_replay": str(source)}}
    journal.write_report(report)
    if os.getenv("V12_DEFER_DISCORD", "0") == "1": _write_discord_payload(results, portfolio, chosen, combo, health, report)
    else:
        if _send(results, portfolio, chosen, combo, health, report): storage.mark_run_published(run_id)
    return report


def replay_dry_run(path):
    payload = core.load_http_replay(path)
    old_date, old_season = core.TARGET_DATE, core.SEASON
    try:
        core.TARGET_DATE = str(payload.get("target_date") or old_date); core.SEASON = int(core.TARGET_DATE[:4])
        at = payload.get("analyzed_at")
        games = core.mlb_schedule(core.TARGET_DATE); events = core.odds_api(); matches = core.match_odds_events(games, events)
        results = []
        for g in games:
            e = matches.get(str(g.get("gamePk")))
            if e and core.parse_dt(g.get("gameDate")) > core.parse_dt(at): results.append(engine.analyze(g, e, as_of=at))
        out = {"schema": "v12-replay-check-v1", "as_of": at, "target_date": core.TARGET_DATE,
               "analyzed_games": len(results), "health": data_quality.health_report(results, len(games), len(matches))}
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)); return out
    finally:
        core.TARGET_DATE, core.SEASON = old_date, old_season; core.clear_http_replay()


def main():
    p = argparse.ArgumentParser(); p.add_argument("--self-test", action="store_true"); p.add_argument("--send-persisted", action="store_true")
    p.add_argument("--snapshot-only", action="store_true"); p.add_argument("--replay-dry-run"); p.add_argument("--confirm-placed"); p.add_argument("--price", type=float)
    a = p.parse_args()
    if a.self_test: self_test()
    elif a.send_persisted: send_persisted()
    elif a.replay_dry_run: replay_dry_run(a.replay_dry_run)
    elif a.confirm_placed: print(json.dumps(storage.confirm_placed(a.confirm_placed, a.price), ensure_ascii=False))
    else: run(snapshot_only=a.snapshot_only)


if __name__ == "__main__": main()
