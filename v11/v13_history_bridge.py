from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean

OLD = Path("data/mlb_backtest_2026.jsonl")
V13 = Path("data/v13_historical_backfill.jsonl")
OUT = Path("data/v13_history_bridge_report.json")


def _num(x, default=None):
    try:
        y = float(x)
        return y if math.isfinite(y) else default
    except Exception:
        return default


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _home_ml(row):
    home = str(row.get("home") or "")
    for opt in row.get("options") or []:
        if str(opt.get("market") or "").upper() == "ML" and str(opt.get("name") or "") == home:
            p = _num(opt.get("p_baseball_raw"))
            if p is not None:
                return p
    return None


def _corr(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    vx = sum((x-mx)**2 for x in xs)
    vy = sum((y-my)**2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return sum((x-mx)*(y-my) for x,y in zip(xs,ys)) / math.sqrt(vx*vy)


def build_report():
    old_rows = _read_jsonl(OLD)
    v13_rows = _read_jsonl(V13)
    old = {str(r.get("game_pk")): r for r in old_rows if r.get("game_pk") is not None}

    # Use one latest true point-in-time FINAL replay per game. EARLY/LATE are not
    # comparable with the historical FINAL-information reconstruction.
    finals = {}
    for r in v13_rows:
        if str(r.get("phase") or "").upper() != "FINAL" or r.get("point_in_time") is not True:
            continue
        gid = str(r.get("game_pk") or "")
        if not gid or gid not in old:
            continue
        rank = str(r.get("analyzed_at") or "")
        if gid not in finals or rank > finals[gid][0]:
            finals[gid] = (rank, r)

    pairs = []
    for gid, (_, nr) in sorted(finals.items()):
        orow = old[gid]
        v10 = orow.get("v10") or {}
        p10 = _num(v10.get("p_home_raw"))
        p13 = _home_ml(nr)
        h10, a10 = _num(v10.get("home_mu")), _num(v10.get("away_mu"))
        h13, a13 = _num(nr.get("projected_home_runs")), _num(nr.get("projected_away_runs"))
        if None in (p10, p13, h10, a10, h13, a13):
            continue
        pairs.append({
            "game_pk": gid,
            "p_v10": p10, "p_v13": p13,
            "p_abs_error": abs(p10-p13),
            "home_run_abs_error": abs(h10-h13),
            "away_run_abs_error": abs(a10-a13),
        })

    p10s = [x["p_v10"] for x in pairs]
    p13s = [x["p_v13"] for x in pairs]
    run_errors = [e for x in pairs for e in (x["home_run_abs_error"], x["away_run_abs_error"])]
    p_errors = [x["p_abs_error"] for x in pairs]

    metrics = {
        "overlap_games": len(pairs),
        "probability_mae": mean(p_errors) if p_errors else None,
        "probability_max_abs_error": max(p_errors) if p_errors else None,
        "probability_correlation": _corr(p10s, p13s),
        "team_run_mae": mean(run_errors) if run_errors else None,
        "team_run_max_abs_error": max(run_errors) if run_errors else None,
    }

    # This bridge never promotes historical rows directly. It only determines
    # whether they may be considered as a weak prior candidate. Production use
    # requires a separate frozen-holdout validation.
    sufficient_overlap = len(pairs) >= 20
    close_probability = metrics["probability_mae"] is not None and metrics["probability_mae"] <= 0.04
    close_runs = metrics["team_run_mae"] is not None and metrics["team_run_mae"] <= 0.50
    correlated = metrics["probability_correlation"] is not None and metrics["probability_correlation"] >= 0.85
    bridge_pass = bool(sufficient_overlap and close_probability and close_runs and correlated)

    warm = [r for r in old_rows if min(int(r.get("pregame_games_home") or 0), int(r.get("pregame_games_away") or 0)) >= 5]
    return {
        "schema": "v13-history-bridge-v1",
        "old_source": str(OLD),
        "v13_source": str(V13),
        "historical_games": len(old_rows),
        "historical_warm_games": len(warm),
        "comparison_phase": "FINAL",
        "metrics": metrics,
        "bridge_pass": bridge_pass,
        "eligibility_if_pass": "WEAK_PRIOR_CANDIDATE_ONLY",
        "direct_calibration_allowed": False,
        "direct_production_activation_allowed": False,
        "reason": "V10 historical probabilities are not V13 probabilities; bridge similarity is necessary but not sufficient for production use.",
        "sample": pairs[:20],
    }


def main():
    report = build_report()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
