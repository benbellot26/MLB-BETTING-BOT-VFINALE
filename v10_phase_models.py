"""Phase-aware learning for MLB V10.

Each EARLY/LATE/FINAL model is trained only on snapshots from the same phase.
This prevents late lineup/market information from leaking into morning forecasts.
"""
import math
from statistics import mean

import bot as core

PHASES = ("EARLY", "LATE", "FINAL")


def phase_snapshot(record, phase):
    snaps = [
        s for s in record.get("snapshots", [])
        if core.num(s.get("seconds_to_game"), -1) >= 0
        and s.get("phase") == phase
        and s.get("feature_version") == core.FEATURE_VERSION
        and s.get("model_version") == core.MODEL_VERSION
        and s.get("distribution_version") == core.DIST_VERSION
    ]
    return max(snaps, key=lambda s: s.get("analyzed_at", "")) if snaps else None


def training_games_phase(hist, phase):
    out = []
    for record in hist.values():
        if record.get("status") != "FINAL":
            continue
        snap = phase_snapshot(record, phase)
        if not snap:
            continue
        try:
            out.append((
                record.get("game_date", ""),
                snap,
                float(record["home_score"]),
                float(record["away_score"]),
            ))
        except Exception:
            pass
    out.sort(key=lambda row: row[0])
    return out


def run_model_state_phase(hist, phase):
    games = training_games_phase(hist, phase)
    out = {
        "phase": phase,
        "active": False,
        "model": None,
        "n": len(games),
        "rmse_model": None,
        "rmse_base": None,
        "gain_prob": 0.0,
        "folds": 0,
    }
    if len(games) < core.RUN_MODEL_MIN_GAMES:
        return out

    base_losses, new_losses = [], []
    folds = core.walk_folds(len(games), 90)
    for cut, end in folds:
        train = []
        for _, snap, hs, away_score in games[:cut]:
            train += [
                (snap["run_features_home"], hs - core.num(snap["base_home"])),
                (snap["run_features_away"], away_score - core.num(snap["base_away"])),
            ]
        if not train:
            continue
        model = core.fit_linear(train)
        for _, snap, hs, away_score in games[cut:end]:
            ph = core.num(snap["base_home"]) + core.clamp(
                core.linear_predict(model, snap["run_features_home"]), -2, 2
            )
            pa = core.num(snap["base_away"]) + core.clamp(
                core.linear_predict(model, snap["run_features_away"]), -2, 2
            )
            base_losses += [
                core.rmse_loss(core.num(snap["base_home"]), hs),
                core.rmse_loss(core.num(snap["base_away"]), away_score),
            ]
            new_losses += [
                core.rmse_loss(ph, hs),
                core.rmse_loss(pa, away_score),
            ]

    if not base_losses:
        return out

    rb = math.sqrt(mean(base_losses))
    rn = math.sqrt(mean(new_losses))
    gp = core.bootstrap_gain_prob(base_losses, new_losses)
    out.update({
        "rmse_base": rb,
        "rmse_model": rn,
        "gain_prob": gp,
        "folds": len(folds),
    })

    if rn + .035 < rb and gp >= .90:
        rows = []
        for _, snap, hs, away_score in games:
            rows += [
                (snap["run_features_home"], hs - core.num(snap["base_home"])),
                (snap["run_features_away"], away_score - core.num(snap["base_away"])),
            ]
        out.update({"active": True, "model": core.fit_linear(rows)})
    return out


def calibration_state_phase(hist, phase, engine_mode):
    rows = []
    for record in hist.values():
        if record.get("status") != "FINAL":
            continue
        snap = phase_snapshot(record, phase)
        if (
            snap
            and snap.get("engine_mode") == engine_mode
            and snap.get("p_model_raw") is not None
        ):
            rows.append((
                record.get("game_date", ""),
                core.num(snap["p_model_raw"], .5),
                int(record.get("home_win", 0)),
            ))
    rows.sort()
    out = {
        "phase": phase,
        "active": False,
        "model": None,
        "n": len(rows),
        "brier_raw": None,
        "brier_cal": None,
        "gain_prob": 0.0,
        "folds": 0,
    }
    if len(rows) < core.CAL_MIN_GAMES:
        return out

    base_losses, new_losses = [], []
    folds = core.walk_folds(len(rows), 110)
    for cut, end in folds:
        model = core.fit_platt([(p, y) for _, p, y in rows[:cut]])
        for _, p, y in rows[cut:end]:
            base_losses.append((p - y) ** 2)
            new_losses.append((core.platt_predict(model, p) - y) ** 2)

    if not base_losses:
        return out

    br = mean(base_losses)
    bc = mean(new_losses)
    gp = core.bootstrap_gain_prob(base_losses, new_losses)
    out.update({
        "brier_raw": br,
        "brier_cal": bc,
        "gain_prob": gp,
        "folds": len(folds),
    })
    if bc + .001 < br and gp >= .90:
        out.update({
            "active": True,
            "model": core.fit_platt([(p, y) for _, p, y in rows]),
        })
    return out


def skill_state_phase(hist, phase, engine_mode):
    pm, pk, ys = [], [], []
    for record in hist.values():
        if record.get("status") != "FINAL":
            continue
        snap = phase_snapshot(record, phase)
        if (
            not snap
            or snap.get("engine_mode") != engine_mode
            or snap.get("p_model") is None
            or snap.get("market_home") is None
        ):
            continue
        pm.append(core.num(snap["p_model"], .5))
        pk.append(core.num(snap["market_home"], .5))
        ys.append(int(record.get("home_win", 0)))

    if len(ys) < 60:
        return {
            "phase": phase,
            "n": len(ys),
            "brier_model": None,
            "brier_market": None,
            "model_weight": .42,
        }
    bm = core.brier(pm, ys)
    bk = core.brier(pk, ys)
    return {
        "phase": phase,
        "n": len(ys),
        "brier_model": bm,
        "brier_market": bk,
        "model_weight": core.clamp(.42 + (bk - bm) * 8, .25, .68),
    }


def build_run_states(hist):
    states = {phase: run_model_state_phase(hist, phase) for phase in PHASES}
    return {
        "active": any(s["active"] for s in states.values()),
        "model": None,
        "n": sum(s["n"] for s in states.values()),
        "rmse_model": next((s["rmse_model"] for s in reversed(tuple(states.values())) if s["rmse_model"] is not None), None),
        "rmse_base": next((s["rmse_base"] for s in reversed(tuple(states.values())) if s["rmse_base"] is not None), None),
        "gain_prob": max((s["gain_prob"] for s in states.values()), default=0.0),
        "folds": sum(s["folds"] for s in states.values()),
        "phase_states": states,
    }


def build_cal_states(hist, run_parent):
    states = {}
    for phase in PHASES:
        rs = run_parent["phase_states"][phase]
        engine = "learned-runs" if rs["active"] else "base-runs"
        states[phase] = calibration_state_phase(hist, phase, engine)
    return {
        "active": any(s["active"] for s in states.values()),
        "model": None,
        "n": sum(s["n"] for s in states.values()),
        "brier_raw": None,
        "brier_cal": None,
        "gain_prob": max((s["gain_prob"] for s in states.values()), default=0.0),
        "folds": sum(s["folds"] for s in states.values()),
        "phase_states": states,
    }


def build_skill_states(hist, run_parent):
    states = {}
    for phase in PHASES:
        rs = run_parent["phase_states"][phase]
        engine = "learned-runs" if rs["active"] else "base-runs"
        states[phase] = skill_state_phase(hist, phase, engine)
    return {
        "n": sum(s["n"] for s in states.values()),
        "brier_model": None,
        "brier_market": None,
        "model_weight": .42,
        "phase_states": states,
    }


def select_phase_states(states, phase):
    run_parent, dispersion, cal_parent, skill_parent = states
    run_state = run_parent.get("phase_states", {}).get(phase)
    cal_state = cal_parent.get("phase_states", {}).get(phase)
    skill_state = skill_parent.get("phase_states", {}).get(phase)
    if run_state is None:
        run_state = {"active": False, "model": None, "n": 0}
    if cal_state is None:
        cal_state = {"active": False, "model": None, "n": 0}
    if skill_state is None:
        skill_state = {"n": 0, "model_weight": .42}
    return run_state, dispersion, cal_state, skill_state


def self_test():
    base = {
        "status": "FINAL",
        "game_date": "2026-08-01T20:00:00Z",
        "home_score": 5,
        "away_score": 3,
        "home_win": 1,
        "snapshots": [],
    }

    def snap(phase, at, p=.55):
        return {
            "phase": phase,
            "analyzed_at": at,
            "seconds_to_game": 1000,
            "feature_version": core.FEATURE_VERSION,
            "model_version": core.MODEL_VERSION,
            "distribution_version": core.DIST_VERSION,
            "engine_mode": "base-runs",
            "base_home": 4.5,
            "base_away": 4.1,
            "run_features_home": [0.0] * 17,
            "run_features_away": [0.0] * 17,
            "p_model_raw": p,
            "p_model": p,
            "market_home": .53,
        }

    record = dict(base)
    record["snapshots"] = [
        snap("EARLY", "2026-08-01T10:00:00+00:00", .52),
        snap("EARLY", "2026-08-01T12:00:00+00:00", .54),
        snap("FINAL", "2026-08-01T19:30:00+00:00", .60),
    ]
    hist = {"1": record}
    assert phase_snapshot(record, "EARLY")["p_model"] == .54
    assert phase_snapshot(record, "FINAL")["p_model"] == .60
    assert len(training_games_phase(hist, "EARLY")) == 1
    assert len(training_games_phase(hist, "LATE")) == 0
    assert len(training_games_phase(hist, "FINAL")) == 1
    print("V10 PHASE MODEL TEST OK")


if __name__ == "__main__":
    self_test()
