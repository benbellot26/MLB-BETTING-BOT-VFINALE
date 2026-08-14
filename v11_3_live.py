#!/usr/bin/env python3
"""V11.3 live winner engine with the exact V10 Discord delivery layer.

Prediction:
- V10.0.15 remains the baseball/base engine.
- V11.2 remains the calibrated ML probability head.
- V11.3 remains the directional winner head.
- Run Line and Total remain V10.0.15.

Delivery:
- Discord is sent only through bot.py's V10 functions.
- No V11-specific Discord formatter or extra V11 fields are shown.

Observability:
- data/v11_3_live.jsonl is the canonical V10 vs V11.3 comparison journal.
- Pending rows are automatically settled from MLB Stats API on later runs.
- data/v11_3_live_report.json exposes cumulative de-duplicated comparison metrics.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import bot as core

VERSION = "11.3-live-v10-discord-v3"
MODEL_FILE = Path(os.getenv("V11_3_MODEL_FILE", "data/v11_3_direction_model.json"))
LIVE_FILE = Path(os.getenv("V11_3_LIVE_FILE", "data/v11_3_live.jsonl"))
REPORT_FILE = Path(os.getenv("V11_3_LIVE_REPORT", "data/v11_3_live_report.json"))

DEFAULT_MODEL = {
    "version": "11.3-directional-recent400-v1",
    "trained_through": "2026-08-12",
    "window_games": 400,
    "l2": 3.333,
    "decision_threshold": 0.5,
    "features": [
        "lineup_relative", "regular_overlap", "lineup_abs", "lineup_cov_diff",
        "lineup_x_uncertainty", "lineup_available",
    ],
    "means": {
        "lineup_relative": -0.00223125,
        "regular_overlap": -0.015703125,
        "lineup_abs": -0.017934375,
        "lineup_cov_diff": 0.0,
        "lineup_x_uncertainty": -0.0028245662561229784,
        "lineup_available": 1.0,
    },
    "stds": {
        "lineup_relative": 0.31243396496049763,
        "regular_overlap": 0.34877941429216314,
        "lineup_abs": 0.447148145095235,
        "lineup_cov_diff": 1.0,
        "lineup_x_uncertainty": 0.2717101855670158,
        "lineup_available": 1.0,
    },
    "beta": [
        0.08480752116865005,
        -0.1289723019635723,
        -0.023497525218618854,
        -0.1084445530804969,
        0.0,
        0.35530824359040025,
        0.0,
    ],
    "v11_2_params": {
        "intercept": 0.045,
        "relative_lineup_coef": 0.05,
        "regular_overlap_coef": -0.25,
    },
    "validation": {
        "method": "rolling recent-400; predict all games on an Eastern date before adding that date",
        "holdout_n": 451,
        "wins": 271,
        "accuracy": 0.6008869179600886,
        "note": "historical validation only; live confirmation still required",
    },
}


def clamp(x, lo=.001, hi=.999):
    return max(lo, min(hi, float(x)))


def logit(p):
    p = clamp(p)
    return math.log(p / (1.0 - p))


def sigmoid(z):
    z = max(-30.0, min(30.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def load_model():
    if MODEL_FILE.exists():
        try:
            model = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
            if model.get("version") == DEFAULT_MODEL["version"]:
                return model
        except Exception:
            pass
    return dict(DEFAULT_MODEL)


def _lineup_ops(ctx, side, regular_ops):
    lineup = ctx.get(f"{side}_lineup") or {}
    value = lineup.get("weighted_ops")
    count = int(core.num(lineup.get("count"), 0))
    if value is None or core.num(value, 0) <= .2 or count < 5:
        return float(regular_ops), False, count
    return float(value), True, count


def live_features(result):
    ctx = result.get("ctx") or {}
    lg_ops = core.num(core.league_baselines().get("ops"), .710)
    hhit = core.season_stats(ctx.get("home_id"), "hitting") or {}
    ahit = core.season_stats(ctx.get("away_id"), "hitting") or {}
    hreg = core.num(hhit.get("ops"), lg_ops)
    areg = core.num(ahit.get("ops"), lg_ops)
    hlu, hok, hc = _lineup_ops(ctx, "home", hreg)
    alu, aok, ac = _lineup_ops(ctx, "away", areg)
    lineup_ok = bool(hok and aok)

    if lineup_ok:
        relative = ((hlu-hreg) - (alu-areg)) / .08
        regular_overlap = (hreg-areg) / .08
        lineup_abs = (hlu-alu) / .08
    else:
        relative = regular_overlap = lineup_abs = 0.0

    base = clamp(result.get("p_model", .5))
    strength = min(abs(logit(base)), 2.5) / 2.5
    return {
        "lineup_relative": relative,
        "regular_overlap": regular_overlap,
        "lineup_abs": lineup_abs,
        "lineup_cov_diff": 0.0,
        "lineup_x_uncertainty": relative * (1.0-strength),
        "lineup_available": 1.0 if lineup_ok else 0.0,
        "home_lineup_ops": hlu,
        "away_lineup_ops": alu,
        "home_regular_ops": hreg,
        "away_regular_ops": areg,
        "home_lineup_count": hc,
        "away_lineup_count": ac,
        "lineup_both_available": lineup_ok,
    }


def v11_2_probability(base_p_home, features, model):
    p = model.get("v11_2_params") or DEFAULT_MODEL["v11_2_params"]
    z = logit(base_p_home)
    z += core.num(p.get("intercept"), 0)
    z += core.num(p.get("relative_lineup_coef"), 0) * features["lineup_relative"]
    z += core.num(p.get("regular_overlap_coef"), 0) * features["regular_overlap"]
    return clamp(sigmoid(z))


def v11_3_direction_probability(base_p_home, features, model):
    names = model["features"]
    means = model["means"]
    stds = model["stds"]
    beta = model["beta"]
    z = logit(base_p_home) + core.num(beta[0], 0)
    for i, name in enumerate(names, 1):
        sd = max(1e-9, abs(core.num(stds.get(name), 1)))
        z += core.num(beta[i], 0) * (
            (core.num(features.get(name), 0)-core.num(means.get(name), 0))/sd
        )
    return clamp(sigmoid(z))


def apply_heads(result, model):
    ctx = result["ctx"]
    base = clamp(result.get("p_model", .5))
    f = live_features(result)
    p112 = v11_2_probability(base, f, model)
    p113 = v11_3_direction_probability(base, f, model)
    threshold = core.num(model.get("decision_threshold"), .5)
    home_pick = p113 >= threshold
    pick = ctx["home"] if home_pick else ctx["away"]
    p112_pick = p112 if home_pick else 1-p112
    p113_pick = p113 if home_pick else 1-p113
    p112_side = ctx["home"] if p112 >= .5 else ctx["away"]
    agreement = pick == p112_side
    v10_pick = ctx["home"] if base >= .5 else ctx["away"]
    v10_pick_probability = base if v10_pick == ctx["home"] else 1-base

    rank_score = 100 * (
        .55 * abs(p113-.5)*2
        + .30 * abs(p112-.5)*2
        + .10 * core.clamp(core.num(result.get("quality"), 0), 0, 1)
        + .05 * (1.0 if agreement else 0.0)
    )
    if not f["lineup_both_available"]:
        rank_score -= 5
    rank_score = max(0.0, min(100.0, rank_score))

    if agreement and p112_pick >= .58 and f["lineup_both_available"]:
        grade = "FORT"
    elif agreement and p112_pick >= .55:
        grade = "BON"
    elif agreement and p112_pick >= .52:
        grade = "PRUDENCE"
    else:
        grade = "FAIBLE"

    out = {
        "model_version": VERSION,
        "direction_model_version": model.get("version"),
        "trained_through": model.get("trained_through"),
        "game_pk": result.get("game_pk"),
        "game_date": (result.get("game") or {}).get("gameDate"),
        "target_date": core.TARGET_DATE,
        "home": ctx["home"],
        "away": ctx["away"],
        "phase": result.get("phase"),
        "base_v10_p_home": round(base, 6),
        "base_v10_pick": v10_pick,
        "base_v10_probability_for_pick": round(v10_pick_probability, 6),
        "v11_2_p_home": round(p112, 6),
        "v11_3_direction_p_home": round(p113, 6),
        "v11_3_pick": pick,
        "v11_3_direction_score": round(p113_pick, 6),
        "v11_2_probability_for_pick": round(p112_pick, 6),
        "heads_agree": agreement,
        "v10_v11_same_pick": v10_pick == pick,
        "grade": grade,
        "rank_score": round(rank_score, 2),
        "quality": round(core.num(result.get("quality"), 0), 4),
        "lineup_both_available": f["lineup_both_available"],
        "home_lineup_count": f["home_lineup_count"],
        "away_lineup_count": f["away_lineup_count"],
        "features": {
            k: round(core.num(v), 6) if isinstance(v, (int, float)) else v
            for k, v in f.items()
        },
        "starter_home": ctx.get("home_sp"),
        "starter_away": ctx.get("away_sp"),
        "runline_inherited_from": "V10.0.15",
        "total_inherited_from": "V10.0.15",
        "official_effect": True,
        "official_ml_selected": False,
        "official_ml_units": 0,
        "official_ml_winamax_price": None,
        "official_ml_confidence": None,
        "official_ml_p_effective": None,
        "official_ml_score": None,
        "result_status": "PENDING",
        "winner": None,
        "home_score": None,
        "away_score": None,
        "v10_correct": None,
        "v11_3_correct": None,
        "v11_net_correction": None,
        "v10_brier": None,
        "v11_2_brier": None,
        "v10_logloss": None,
        "v11_2_logloss": None,
        "settled_at": None,
    }
    result["v11_3"] = out
    return out


def _orient_v112_for_v113(result):
    """Expose V11.3 winner through V10's existing ML presentation contract."""
    x = result["v11_3"]
    home_pick = x["v11_3_pick"] == result["ctx"]["home"]
    p112_home = clamp(x["v11_2_p_home"])
    if x["heads_agree"]:
        p_home = p112_home
    else:
        p_home = .5001 if home_pick else .4999
    result["p_model"] = p_home
    return p_home


def _patch_ml_options(result):
    """Replace only ML probabilities/direction; RL and Total remain V10.0.15."""
    x = result["v11_3"]
    pick = x["v11_3_pick"]
    p_pick = clamp(x["v11_2_probability_for_pick"])
    if not x["heads_agree"]:
        p_pick = .5001

    options = core.v1011_iter_options(result)
    for rec in options:
        if str(rec.get("market") or "").upper() != "ML":
            continue
        is_pick = str(rec.get("name") or "") == str(pick)
        rec["p_model"] = p_pick if is_pick else 1-p_pick
        core.v1011_apply_effective(rec, result)

    ml = (result.get("model_recs") or {}).get("ML")
    if ml and str(ml.get("name") or "") != str(pick):
        replacement = next(
            (r for r in options
             if r.get("market") == "ML" and str(r.get("name")) == str(pick)),
            None,
        )
        if replacement is not None:
            result["model_recs"]["ML"] = replacement


def _capture_official_ml(result):
    """Freeze the V10 selector/execution decision attached to the V11.3 ML side."""
    x = result["v11_3"]
    pick = str(x["v11_3_pick"])
    for rec in core.v1011_iter_options(result):
        if str(rec.get("market") or "").upper() != "ML":
            continue
        if str(rec.get("name") or "") != pick:
            continue
        e = rec.get("winamax_eval") or {}
        x["official_ml_selected"] = bool(e.get("official_selected"))
        x["official_ml_units"] = core.num(e.get("official_units"), 0)
        price = core.num(e.get("price"), 0)
        x["official_ml_winamax_price"] = round(price, 4) if price > 1 else None
        x["official_ml_confidence"] = round(core.num(rec.get("confidence"), 0), 4)
        pe = rec.get("p_effective", rec.get("p_model"))
        x["official_ml_p_effective"] = round(core.num(pe, .5), 6)
        score = rec.get("selection_official_score")
        x["official_ml_score"] = round(core.num(score), 4) if score is not None else None
        return


def load_live_rows():
    rows = []
    if not LIVE_FILE.exists():
        return rows
    for line in LIVE_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            core.logging.warning("V11.3 journal: ligne JSON ignorée")
    return rows


def _is_final_game(game):
    status = game.get("status") or {}
    return (
        str(status.get("abstractGameState") or "").lower() == "final"
        or str(status.get("codedGameState") or "").upper() == "F"
        or str(status.get("detailedState") or "").lower()
        in {"final", "game over", "completed early"}
    )


def _binary_logloss(p, y):
    p = clamp(p, 1e-9, 1-1e-9)
    return -(y*math.log(p) + (1-y)*math.log(1-p))


def settle_live_rows(rows):
    """Settle every pending comparison row from MLB's official schedule scores."""
    pending_dates = sorted({
        str(r.get("target_date"))
        for r in rows
        if r.get("result_status") != "FINAL" and r.get("target_date")
    })
    if not pending_dates:
        return 0

    games_by_pk = {}
    for day in pending_dates:
        try:
            for game in core.mlb_schedule(day):
                games_by_pk[str(game.get("gamePk"))] = game
        except Exception:
            core.logging.exception("V11.3 settlement MLB indisponible pour %s", day)

    settled = 0
    settled_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("result_status") == "FINAL":
            continue
        game = games_by_pk.get(str(row.get("game_pk")))
        if not game or not _is_final_game(game):
            continue

        teams = game.get("teams") or {}
        hs = int(core.num((teams.get("home") or {}).get("score"), 0))
        aps = int(core.num((teams.get("away") or {}).get("score"), 0))
        if hs == aps:
            continue
        home = str(row.get("home"))
        away = str(row.get("away"))
        winner = home if hs > aps else away
        p10 = clamp(row.get("base_v10_p_home", .5))
        p112 = clamp(row.get("v11_2_p_home", .5))
        y = 1 if winner == home else 0

        v10_pick = row.get("base_v10_pick")
        if not v10_pick:
            v10_pick = home if p10 >= .5 else away
            row["base_v10_pick"] = v10_pick
            row["base_v10_probability_for_pick"] = round(
                p10 if v10_pick == home else 1-p10, 6
            )
        v11_pick = row.get("v11_3_pick")
        c10 = v10_pick == winner
        c11 = v11_pick == winner

        row.update({
            "result_status": "FINAL",
            "winner": winner,
            "home_score": hs,
            "away_score": aps,
            "v10_correct": c10,
            "v11_3_correct": c11,
            "v10_v11_same_pick": v10_pick == v11_pick,
            "v11_net_correction": 1 if c11 and not c10 else -1 if c10 and not c11 else 0,
            "v10_brier": round((p10-y)**2, 8),
            "v11_2_brier": round((p112-y)**2, 8),
            "v10_logloss": round(_binary_logloss(p10, y), 8),
            "v11_2_logloss": round(_binary_logloss(p112, y), 8),
            "settled_at": settled_at,
        })
        settled += 1
    return settled


def write_rows(rows):
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIVE_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _canonical_final_rows(rows):
    """One closest-to-first-pitch observation per settled game."""
    best = {}
    for row in rows:
        if row.get("result_status") != "FINAL" or not row.get("game_pk"):
            continue
        analyzed = str(row.get("analyzed_at") or "")
        game_date = str(row.get("game_date") or "")
        key = str(row["game_pk"])
        rank = (analyzed, game_date)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, row)
    return [x[1] for x in best.values()]


def comparison_summary(rows):
    xs = _canonical_final_rows(rows)
    n = len(xs)
    if not n:
        return {
            "settled_games": 0,
            "v10_wins": 0,
            "v11_3_wins": 0,
            "v10_accuracy": None,
            "v11_3_accuracy": None,
            "changed_direction_games": 0,
            "v11_corrections": 0,
            "v11_regressions": 0,
            "v11_net_corrections": 0,
            "v10_brier": None,
            "v11_2_brier": None,
            "v10_logloss": None,
            "v11_2_logloss": None,
            "official_ml": {"n": 0, "wins": 0, "accuracy": None},
            "by_grade": {},
        }

    w10 = sum(bool(x.get("v10_correct")) for x in xs)
    w11 = sum(bool(x.get("v11_3_correct")) for x in xs)
    changed = [x for x in xs if not x.get("v10_v11_same_pick", True)]
    corr = sum(core.num(x.get("v11_net_correction"), 0) > 0 for x in xs)
    reg = sum(core.num(x.get("v11_net_correction"), 0) < 0 for x in xs)

    def avg(field):
        vals = [core.num(x.get(field)) for x in xs if x.get(field) is not None]
        return round(sum(vals)/len(vals), 8) if vals else None

    official = [x for x in xs if x.get("official_ml_selected")]
    off_wins = sum(bool(x.get("v11_3_correct")) for x in official)

    by_grade = {}
    for grade in ("FORT", "BON", "PRUDENCE", "FAIBLE"):
        gx = [x for x in xs if x.get("grade") == grade]
        if gx:
            gw = sum(bool(x.get("v11_3_correct")) for x in gx)
            by_grade[grade] = {
                "n": len(gx),
                "wins": gw,
                "accuracy": round(gw/len(gx), 6),
            }

    return {
        "settled_games": n,
        "v10_wins": w10,
        "v11_3_wins": w11,
        "v10_accuracy": round(w10/n, 6),
        "v11_3_accuracy": round(w11/n, 6),
        "changed_direction_games": len(changed),
        "v11_corrections": int(corr),
        "v11_regressions": int(reg),
        "v11_net_corrections": int(corr-reg),
        "v10_brier": avg("v10_brier"),
        "v11_2_brier": avg("v11_2_brier"),
        "v10_logloss": avg("v10_logloss"),
        "v11_2_logloss": avg("v11_2_logloss"),
        "official_ml": {
            "n": len(official),
            "wins": off_wins,
            "accuracy": round(off_wins/len(official), 6) if official else None,
        },
        "by_grade": by_grade,
    }


def self_test():
    model = load_model()
    f = {
        "lineup_relative": .5, "regular_overlap": .2, "lineup_abs": .7,
        "lineup_cov_diff": 0.0, "lineup_x_uncertainty": .4, "lineup_available": 1.0,
    }
    p112 = v11_2_probability(.55, f, model)
    p113 = v11_3_direction_probability(.55, f, model)
    assert 0 < p112 < 1 and 0 < p113 < 1
    assert model["validation"]["wins"] == 271 and model["validation"]["holdout_n"] == 451
    assert callable(core.send_game) and callable(core.send_top_messages) and callable(core.send_daily_plan)

    fake = [{
        "game_pk": 1, "result_status": "FINAL", "analyzed_at": "1",
        "grade": "BON", "v10_correct": False, "v11_3_correct": True,
        "v10_v11_same_pick": False, "v11_net_correction": 1,
        "v10_brier": .30, "v11_2_brier": .20,
        "v10_logloss": .80, "v11_2_logloss": .60,
        "official_ml_selected": True,
    }]
    s = comparison_summary(fake)
    assert s["v11_3_wins"] == 1 and s["v11_net_corrections"] == 1
    assert s["official_ml"]["n"] == 1
    print("SELF-TEST V11.3 LIVE + V10 DISCORD + COMPARISON JOURNAL OK")


def main():
    model = load_model()
    if not core.ODDS_KEY:
        raise SystemExit("ODDS_API_KEY absente")

    journal_rows = load_live_rows()
    settled_now = settle_live_rows(journal_rows)

    discord_ok = core.discord_test()
    hist = core.load_history()
    core.settle_history(hist)
    run_state = core.run_model_state(hist)
    disp_state = core.dispersion_state(hist)
    engine = "learned-runs" if run_state.get("active") else "base-runs"
    cal_state = core.calibration_state(hist, engine)
    skill = core.skill_state(hist, engine)
    states = (run_state, disp_state, cal_state, skill)

    core.savant_league()
    games = core.mlb_schedule(core.TARGET_DATE)
    events = core.odds_api()
    matches = core.match_odds_events(games, events)
    results = []

    now = core.NOW
    for game in games:
        if core.parse_dt(game["gameDate"]) <= now:
            continue
        pair = matches.get(str(game["gamePk"]))
        if not pair:
            continue
        try:
            result = core.analyze_base(game, pair[0], pair[1], states, hist)
            result["disp_state"] = disp_state
            core.attach_model_recommendations(result)
            apply_heads(result, model)
            _orient_v112_for_v113(result)
            _patch_ml_options(result)
            results.append(result)
        except Exception:
            core.logging.exception("V11.3 analyse impossible pour gamePk=%s", game.get("gamePk"))

    portfolio = core.allocate_portfolio(results) if results else {
        "daily_cap": 0.0, "allocated": 0.0, "remaining": 0.0, "game_cap": 0.0
    }

    analyzed_at = datetime.now(timezone.utc).isoformat()
    run_id = hashlib.sha1(
        f"{analyzed_at}|{core.TARGET_DATE}|{VERSION}".encode()
    ).hexdigest()[:16]
    new_rows = []
    for result in results:
        _capture_official_ml(result)
        row = dict(result["v11_3"])
        row.update({"run_id": run_id, "analyzed_at": analyzed_at})
        new_rows.append(row)

    journal_rows.extend(new_rows)
    write_rows(journal_rows)

    if discord_ok and results:
        for result in results:
            core.send_game(result, {}, portfolio)
        core.send_top_messages(results, skill)
        core.send_daily_plan(results)

    ranked = sorted(new_rows, key=lambda r: r["rank_score"], reverse=True)
    comparison = comparison_summary(journal_rows)
    report = {
        "version": VERSION,
        "run_id": run_id,
        "analyzed_at": analyzed_at,
        "target_date": core.TARGET_DATE,
        "model": model,
        "remaining_games_analyzed": len(new_rows),
        "settled_comparison_rows_this_run": settled_now,
        "discord_delivery": "exact-current-V10-functions",
        "comparison": comparison,
        "top_picks": [
            {k: r.get(k) for k in (
                "game_pk", "away", "home", "base_v10_pick", "v11_3_pick",
                "v11_3_direction_score", "v11_2_probability_for_pick",
                "heads_agree", "grade", "rank_score", "phase",
                "official_ml_selected", "official_ml_units",
            )}
            for r in ranked[:5]
        ],
        "methodology": {
            "winner_direction": "V11.3 recent-400 residual head",
            "probability_head": "V11.2 lineup-calibrated head",
            "runline_total": "V10.0.15 inherited",
            "discord": "V10 exact delivery layer",
            "comparison_canonicalization": "latest pregame observation per settled game",
            "comparison_settlement": "MLB Stats API official final scores",
            "tonight_model_trained_through": "2026-08-12",
            "important_note": "The 60.09% evidence comes from rolling day-frozen evaluation. Live confirmation remains required.",
        },
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    core.logging.info(
        "V11.3 LIVE terminé | Discord=V10 exact | nouveaux=%d | réglés=%d | "
        "comparatif=%d matchs V10=%s V11.3=%s net=%+d | top=%s",
        len(new_rows), settled_now, comparison["settled_games"],
        f"{100*comparison['v10_accuracy']:.1f}%" if comparison["v10_accuracy"] is not None else "-",
        f"{100*comparison['v11_3_accuracy']:.1f}%" if comparison["v11_3_accuracy"] is not None else "-",
        comparison["v11_net_corrections"],
        ", ".join(r["v11_3_pick"] for r in ranked[:3]) or "-",
    )


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()
