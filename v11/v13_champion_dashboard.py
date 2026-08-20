from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import journal, pro_model
from .probability_contract_v13 import MODEL_GENERATION_FINGERPRINT, row_is_predictively_compatible

OUT_JSON = Path("data/v13_champion_dashboard.json")
OUT_MD = Path("data/v13_champion_dashboard.md")
SCHEMA = "v13.10-champion-dashboard-v1"
MARKETS = ("ML", "RUNLINE", "TOTAL")


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _current(row: dict[str, Any]) -> bool:
    generation = row.get("model_generation") or row.get("model_generation_fingerprint")
    return generation == MODEL_GENERATION_FINGERPRINT and row_is_predictively_compatible(row)


def _latest_settled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, tuple[tuple[int, str], dict[str, Any]]] = {}
    phase_rank = {"EARLY": 0, "LATE": 1, "FINAL": 2}
    for row in rows:
        if row.get("result_status") != "FINAL" or not row.get("game_pk") or not _current(row):
            continue
        rank = (phase_rank.get(str(row.get("phase") or "").upper(), -1), str(row.get("analyzed_at") or ""))
        gid = str(row["game_pk"])
        if gid not in best or rank > best[gid][0]:
            best[gid] = (rank, row)
    return [v[1] for v in best.values()]


def _prob(option: dict[str, Any]) -> float | None:
    for key in ("p_predictive_final", "p_baseball_calibrated", "p_effective"):
        p = _num(option.get(key))
        if p is not None:
            return max(.001, min(.999, p))
    return None


def _prob_metrics(options: list[dict[str, Any]]) -> dict[str, Any]:
    scored = []
    for option in options:
        if option.get("result") not in {"WIN", "LOSS"}:
            continue
        p = _prob(option)
        if p is None:
            continue
        y = 1.0 if option.get("result") == "WIN" else 0.0
        scored.append((p, y))
    if not scored:
        return {"n": 0}
    n = len(scored)
    brier = sum((p-y)**2 for p, y in scored) / n
    logloss = sum(-(y*math.log(p)+(1-y)*math.log(1-p)) for p, y in scored) / n
    mean_p = sum(p for p, _ in scored) / n
    outcome_rate = sum(y for _, y in scored) / n
    return {
        "n": n,
        "brier": round(brier, 6),
        "logloss": round(logloss, 6),
        "mean_probability": round(mean_p, 6),
        "outcome_rate": round(outcome_rate, 6),
        "calibration_gap": round(mean_p-outcome_rate, 6),
        "accuracy_at_50": round(sum((p >= .5) == bool(y) for p, y in scored)/n, 6),
    }


def _run_metrics(games: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for row in games:
        hp, ap = _num(row.get("projected_home_runs")), _num(row.get("projected_away_runs"))
        hs, ass = _num(row.get("home_score")), _num(row.get("away_score"))
        if None in {hp, ap, hs, ass}:
            continue
        rows.append((hp, ap, hs, ass))
    if not rows:
        return {"n": 0}
    n = len(rows)
    home_err = [hs-hp for hp, ap, hs, ass in rows]
    away_err = [ass-ap for hp, ap, hs, ass in rows]
    total_err = [(hs+ass)-(hp+ap) for hp, ap, hs, ass in rows]
    return {
        "n": n,
        "home_mae_runs": round(sum(abs(x) for x in home_err)/n, 4),
        "away_mae_runs": round(sum(abs(x) for x in away_err)/n, 4),
        "total_mae_runs": round(sum(abs(x) for x in total_err)/n, 4),
        "home_bias_runs": round(sum(home_err)/n, 4),
        "away_bias_runs": round(sum(away_err)/n, 4),
        "total_bias_runs": round(sum(total_err)/n, 4),
    }


def _canonical_options(games: list[dict[str, Any]], market: str | None = None) -> list[dict[str, Any]]:
    out = []
    for row in games:
        markets = (market,) if market else MARKETS
        for name in markets:
            option = pro_model.canonical_market_option(row, name)
            if option:
                out.append(option)
    return out


def _dq_band(row: dict[str, Any]) -> str:
    dq = row.get("data_quality") or {}
    score = _num(dq.get("model_input_score", dq.get("score")))
    if score is None:
        return "unknown"
    if score < .60:
        return "<0.60"
    if score < .75:
        return "0.60-0.75"
    if score < .90:
        return "0.75-0.90"
    return ">=0.90"


def _prob_band(p: float | None) -> str:
    if p is None:
        return "unknown"
    if p < .55:
        return "<55%"
    if p < .60:
        return "55-60%"
    if p < .65:
        return "60-65%"
    if p < .70:
        return "65-70%"
    return ">=70%"


def _venue(row: dict[str, Any]) -> str:
    features = row.get("features") or {}
    park = features.get("park_factor_runtime") or {}
    return str(park.get("venue") or "unknown")


def _group_games(games: list[dict[str, Any]], key_fn, min_n: int = 1) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in games:
        groups[str(key_fn(row))].append(row)
    out = {}
    for key, subset in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(subset) < min_n:
            continue
        out[key] = {
            "games": len(subset),
            "runs": _run_metrics(subset),
            "probability": _prob_metrics(_canonical_options(subset)),
        }
    return out


def _team_breakdown(games: list[dict[str, Any]], min_n: int = 3) -> dict[str, Any]:
    data: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "abs": [], "err": []})
    for row in games:
        hp, ap = _num(row.get("projected_home_runs")), _num(row.get("projected_away_runs"))
        hs, ass = _num(row.get("home_score")), _num(row.get("away_score"))
        if None in {hp, ap, hs, ass}:
            continue
        for team, predicted, actual in ((row.get("home"), hp, hs), (row.get("away"), ap, ass)):
            if not team:
                continue
            err = actual-predicted
            d = data[str(team)]
            d["n"] += 1
            d["abs"].append(abs(err))
            d["err"].append(err)
    out = {}
    for team, d in sorted(data.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        if d["n"] < min_n:
            continue
        out[team] = {
            "n": d["n"],
            "run_mae": round(sum(d["abs"])/d["n"], 4),
            "run_bias": round(sum(d["err"])/d["n"], 4),
        }
    return out


def _probability_band_breakdown(games: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for option in _canonical_options(games):
        grouped[_prob_band(_prob(option))].append(option)
    return {band: _prob_metrics(opts) for band, opts in grouped.items()}


def _dq_components(games: list[dict[str, Any]]) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    n = 0
    for row in games:
        dq = row.get("data_quality") or {}
        components = dq.get("components") or {}
        if components:
            n += 1
            for key, value in components.items():
                v = _num(value)
                if v is not None:
                    totals[key] += v
        for blocker in dq.get("blockers") or []:
            blockers[str(blocker)] += 1
    return {
        "n": n,
        "mean_components": {k: round(v/n, 4) for k, v in totals.items()} if n else {},
        "blockers": dict(blockers.most_common()),
    }


def _snapshot(games: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "games": len(games),
        "runs": _run_metrics(games),
        "probability": {
            "all_markets": _prob_metrics(_canonical_options(games)),
            "by_market": {m: _prob_metrics(_canonical_options(games, m)) for m in MARKETS},
        },
        "by_phase": _group_games(games, lambda r: str(r.get("phase") or "UNKNOWN").upper()),
        "by_data_quality": _group_games(games, _dq_band),
        "by_probability_band": _probability_band_breakdown(games),
        "data_quality_components": _dq_components(games),
    }


def build(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = journal.load_rows() if rows is None else list(rows)
    games = _latest_settled(rows)
    dates = sorted({str(r.get("target_date") or "") for r in games if r.get("target_date")})
    latest_date = dates[-1] if dates else None
    latest = [r for r in games if str(r.get("target_date") or "") == latest_date] if latest_date else []
    return {
        "schema": SCHEMA,
        "model_generation": MODEL_GENERATION_FINGERPRINT,
        "scope": "current-generation-only; latest settled pregame observation per game",
        "latest_date": latest_date,
        "latest_day": _snapshot(latest),
        "cumulative": _snapshot(games),
        "by_team": _team_breakdown(games),
        "by_venue": _group_games(games, _venue, min_n=3),
        "safety": {
            "changes_predictions": False,
            "market_used_as_model_feature": False,
            "legacy_generations_in_top_level_metrics": False,
        },
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    cum = report.get("cumulative") or {}
    day = report.get("latest_day") or {}
    lines = [
        "# V13.10 Champion Diagnostic Dashboard",
        "",
        f"Model generation: `{report.get('model_generation')}`",
        f"Latest settled date: `{report.get('latest_date') or 'none'}`",
        "",
        "## Core scorecard",
        "",
        "| Metric | Latest day | Cumulative |",
        "|---|---:|---:|",
    ]
    pairs = [
        ("Games", (day.get("games")), (cum.get("games"))),
        ("Home run MAE", ((day.get("runs") or {}).get("home_mae_runs")), ((cum.get("runs") or {}).get("home_mae_runs"))),
        ("Away run MAE", ((day.get("runs") or {}).get("away_mae_runs")), ((cum.get("runs") or {}).get("away_mae_runs"))),
        ("Total run MAE", ((day.get("runs") or {}).get("total_mae_runs")), ((cum.get("runs") or {}).get("total_mae_runs"))),
        ("Brier", (((day.get("probability") or {}).get("all_markets") or {}).get("brier")), (((cum.get("probability") or {}).get("all_markets") or {}).get("brier"))),
        ("LogLoss", (((day.get("probability") or {}).get("all_markets") or {}).get("logloss")), (((cum.get("probability") or {}).get("all_markets") or {}).get("logloss"))),
        ("Calibration gap", (((day.get("probability") or {}).get("all_markets") or {}).get("calibration_gap")), (((cum.get("probability") or {}).get("all_markets") or {}).get("calibration_gap"))),
    ]
    for label, a, b in pairs:
        lines.append(f"| {label} | {_fmt(a)} | {_fmt(b)} |")

    lines.extend(["", "## Cumulative by market", "", "| Market | N | Brier | LogLoss | Mean p | Outcome rate | Calibration gap |", "|---|---:|---:|---:|---:|---:|---:|"])
    by_market = ((cum.get("probability") or {}).get("by_market") or {})
    for market in MARKETS:
        m = by_market.get(market) or {}
        lines.append(f"| {market} | {_fmt(m.get('n'), 0)} | {_fmt(m.get('brier'))} | {_fmt(m.get('logloss'))} | {_fmt(m.get('mean_probability'))} | {_fmt(m.get('outcome_rate'))} | {_fmt(m.get('calibration_gap'))} |")

    lines.extend(["", "## Data-quality bands", "", "| DQ band | Games | Run MAE total | Brier | LogLoss |", "|---|---:|---:|---:|---:|"])
    for band, payload in (cum.get("by_data_quality") or {}).items():
        lines.append(f"| {band} | {_fmt(payload.get('games'), 0)} | {_fmt((payload.get('runs') or {}).get('total_mae_runs'))} | {_fmt((payload.get('probability') or {}).get('brier'))} | {_fmt((payload.get('probability') or {}).get('logloss'))} |")

    teams = report.get("by_team") or {}
    worst = sorted(teams.items(), key=lambda kv: (-float(kv[1].get("run_mae") or 0), -int(kv[1].get("n") or 0)))[:10]
    lines.extend(["", "## Highest run-error teams (min 3 observations)", "", "| Team | N | Run MAE | Bias |", "|---|---:|---:|---:|"])
    for team, payload in worst:
        lines.append(f"| {team} | {_fmt(payload.get('n'), 0)} | {_fmt(payload.get('run_mae'))} | {_fmt(payload.get('run_bias'))} |")

    blockers = (((cum.get("data_quality_components") or {}).get("blockers")) or {})
    lines.extend(["", "## Data blockers", ""])
    if blockers:
        for name, count in blockers.items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- None recorded in the current-generation settled sample.")
    lines.append("")
    lines.append("> Diagnostic only. This report does not modify V13.10 probabilities or selection behavior.")
    return "\n".join(lines) + "\n"


def main() -> None:
    report = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    OUT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
