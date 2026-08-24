from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import journal, pro_model
from . import v13_daily_tracking as tracking
from . import v1310_market_diagnostics as market_diag
from .probability_contract_v13 import MODEL_GENERATION_FINGERPRINT, row_is_predictively_compatible

OUT_JSON = Path("data/v13_champion_dashboard.json")
OUT_MD = Path("data/v13_champion_dashboard.md")
SCHEMA = "v13.10-champion-dashboard-v3"
MARKETS = ("ML", "RUNLINE", "TOTAL")
SHRINKAGE_PRIOR_N = 12


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


def _state_date(state: dict[str, Any]) -> str | None:
    target = str(state.get("target_date") or "").strip()
    if target:
        return target[:10]
    game_date = str(state.get("game_date") or "").strip()
    return game_date[:10] if len(game_date) >= 10 else None


def _market_settled_dates(states: list[dict[str, Any]]) -> list[str]:
    return sorted({
        date
        for state in states
        if state.get("settled_result") in {"WIN", "LOSS", "PUSH"}
        and _current(state)
        for date in [_state_date(state)]
        if date
    })


def _prob(option: dict[str, Any]) -> float | None:
    for key in ("p_predictive_final", "p_baseball_calibrated", "p_effective"):
        p = _num(option.get(key))
        if p is not None:
            return max(.001, min(.999, p))
    return None


def _prob_metrics(options: list[dict[str, Any]]) -> dict[str, Any]:
    scored = []
    pushes = 0
    for option in options:
        if option.get("result") == "PUSH":
            pushes += 1
            continue
        if option.get("result") not in {"WIN", "LOSS"}:
            continue
        p = _prob(option)
        if p is None:
            continue
        y = 1.0 if option.get("result") == "WIN" else 0.0
        scored.append((p, y))
    if not scored:
        return {"n": 0, "pushes": pushes}
    n = len(scored)
    brier = sum((p-y)**2 for p, y in scored) / n
    logloss = sum(-(y*math.log(p)+(1-y)*math.log(1-p)) for p, y in scored) / n
    mean_p = sum(p for p, _ in scored) / n
    outcome_rate = sum(y for _, y in scored) / n
    return {
        "n": n,
        "pushes": pushes,
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
    score = _num(dq.get("model_input_score", dq.get("score"))) if isinstance(dq, dict) else _num(dq)
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


def _shrink_bias(raw_bias: float | None, n: int, prior_n: int = SHRINKAGE_PRIOR_N) -> tuple[float | None, float]:
    if raw_bias is None or n <= 0:
        return None, 0.0
    reliability = n / (n + prior_n)
    return round(raw_bias * reliability, 4), round(reliability, 4)


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
        raw_bias = sum(d["err"])/d["n"]
        shrunk, reliability = _shrink_bias(raw_bias, d["n"])
        out[team] = {
            "n": d["n"],
            "run_mae": round(sum(d["abs"])/d["n"], 4),
            "run_bias": round(raw_bias, 4),
            "shrunk_run_bias": shrunk,
            "reliability": reliability,
            "shrinkage_prior_n": SHRINKAGE_PRIOR_N,
        }
    return out


def _venue_breakdown(games: list[dict[str, Any]], min_n: int = 3) -> dict[str, Any]:
    out = _group_games(games, _venue, min_n=min_n)
    for payload in out.values():
        runs = payload.get("runs") or {}
        n = int(runs.get("n") or 0)
        shrunk, reliability = _shrink_bias(_num(runs.get("total_bias_runs")), n)
        payload["shrinkage"] = {
            "shrunk_total_bias_runs": shrunk,
            "reliability": reliability,
            "prior_n": SHRINKAGE_PRIOR_N,
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
        components = dq.get("components") or {} if isinstance(dq, dict) else {}
        if components:
            n += 1
            for key, value in components.items():
                v = _num(value)
                if v is not None:
                    totals[key] += v
        if isinstance(dq, dict):
            for blocker in dq.get("blockers") or []:
                blockers[str(blocker)] += 1
    return {
        "n": n,
        "mean_components": {k: round(v/n, 4) for k, v in totals.items()} if n else {},
        "blockers": dict(blockers.most_common()),
    }


def _snapshot(games: list[dict[str, Any]], states: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if states is None:
        probability = {
            "all_markets": _prob_metrics(_canonical_options(games)),
            "by_market": {m: _prob_metrics(_canonical_options(games, m)) for m in MARKETS},
        }
    else:
        prepared = market_diag.enrich_with_games(states, games)
        probability = {
            "all_markets": market_diag.probability_metrics(market_diag.canonical_states(prepared)),
            "by_market": market_diag.market_scorecard(prepared),
        }
    return {
        "games": len(games),
        "runs": _run_metrics(games),
        "probability": probability,
        "by_phase": _group_games(games, lambda r: str(r.get("phase") or "UNKNOWN").upper()),
        "by_data_quality": _group_games(games, _dq_band),
        "by_probability_band": _probability_band_breakdown(games),
        "data_quality_components": _dq_components(games),
    }


def _states_for_dashboard(games: list[dict[str, Any]], explicit_rows: bool) -> list[dict[str, Any]]:
    if explicit_rows:
        return market_diag.states_from_games(games)
    try:
        states = list(tracking.fold().values())
    except Exception:
        states = []
    return states or market_diag.states_from_games(games)


def build(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    explicit_rows = rows is not None
    rows = journal.load_rows() if rows is None else list(rows)
    games = _latest_settled(rows)
    states = _states_for_dashboard(games, explicit_rows)
    diagnostics = market_diag.build(states, games)

    run_dates = sorted({str(r.get("target_date") or "") for r in games if r.get("target_date")})
    latest_run_date = run_dates[-1] if run_dates else None
    market_dates = _market_settled_dates(states)
    latest_market_date = market_dates[-1] if market_dates else None
    date_candidates = [d for d in (latest_run_date, latest_market_date) if d]
    latest_date = max(date_candidates) if date_candidates else None

    latest = [r for r in games if str(r.get("target_date") or "") == str(latest_date or "")]
    latest_states = [s for s in states if _state_date(s) == latest_date]
    latest_tracked_games = len({
        str(s.get("game_pk"))
        for s in latest_states
        if s.get("game_pk") and s.get("settled_result") in {"WIN", "LOSS", "PUSH"} and _current(s)
    })
    checkpoint = diagnostics.get("checkpoint_100") or {}

    return {
        "schema": SCHEMA,
        "model_generation": MODEL_GENERATION_FINGERPRINT,
        "scope": "current-generation-only; run-projection metrics and market-tracking metrics expose their sample scopes separately; market metrics use one deterministic latest side per unique game+market line",
        "latest_date": latest_date,
        "latest_run_projection_date": latest_run_date,
        "latest_market_tracking_date": latest_market_date,
        "sample_counts": {
            "latest_run_projection_games": len(latest),
            "cumulative_run_projection_games": len(games),
            "latest_tracked_unique_games": latest_tracked_games,
            "cumulative_tracked_unique_games": int(checkpoint.get("unique_games") or 0),
        },
        "latest_day": _snapshot(latest, latest_states),
        "cumulative": _snapshot(games, states),
        "market_diagnostics": diagnostics,
        "by_team": _team_breakdown(games),
        "by_venue": _venue_breakdown(games, min_n=3),
        "safety": {
            "changes_predictions": False,
            "market_used_as_model_feature": False,
            "legacy_generations_in_top_level_metrics": False,
            "diagnostic_only": True,
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


def _pct(value: Any) -> str:
    x = _num(value)
    return "—" if x is None else f"{100*x:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    cum = report.get("cumulative") or {}
    day = report.get("latest_day") or {}
    diag = report.get("market_diagnostics") or {}
    checkpoint = diag.get("checkpoint_100") or {}
    counts = report.get("sample_counts") or {}
    lines = [
        "# V13.10 Champion Diagnostic Dashboard",
        "",
        f"Model generation: `{report.get('model_generation')}`",
        f"Latest settled date (any monitored current-generation evidence): `{report.get('latest_date') or 'none'}`",
        f"Run-projection sample settled through: `{report.get('latest_run_projection_date') or 'none'}`",
        f"Market-tracking sample settled through: `{report.get('latest_market_tracking_date') or 'none'}`",
        f"100-game checkpoint: **{checkpoint.get('unique_games', 0)}/{checkpoint.get('target', 100)}** ({_fmt(checkpoint.get('progress_pct'), 1)}%) — `{checkpoint.get('status', 'COLLECTING')}`",
        "",
        "## Core scorecard",
        "",
        "| Metric | Latest day | Cumulative |",
        "|---|---:|---:|",
    ]
    pairs = [
        ("Run-projection games", counts.get("latest_run_projection_games", day.get("games")), counts.get("cumulative_run_projection_games", cum.get("games"))),
        ("Tracked unique games", counts.get("latest_tracked_unique_games"), counts.get("cumulative_tracked_unique_games")),
        ("Home run MAE", (day.get("runs") or {}).get("home_mae_runs"), (cum.get("runs") or {}).get("home_mae_runs")),
        ("Away run MAE", (day.get("runs") or {}).get("away_mae_runs"), (cum.get("runs") or {}).get("away_mae_runs")),
        ("Total run MAE", (day.get("runs") or {}).get("total_mae_runs"), (cum.get("runs") or {}).get("total_mae_runs")),
        ("Brier all markets", ((day.get("probability") or {}).get("all_markets") or {}).get("brier"), ((cum.get("probability") or {}).get("all_markets") or {}).get("brier")),
        ("LogLoss all markets", ((day.get("probability") or {}).get("all_markets") or {}).get("logloss"), ((cum.get("probability") or {}).get("all_markets") or {}).get("logloss")),
    ]
    for label, a, b in pairs:
        lines.append(f"| {label} | {_fmt(a)} | {_fmt(b)} |")

    lines.extend(["", "## Cumulative by market", "", "| Market | N | Accuracy | Brier | LogLoss | ECE | Pushes |", "|---|---:|---:|---:|---:|---:|---:|"])
    by_market = ((cum.get("probability") or {}).get("by_market") or {})
    for market in MARKETS:
        m = by_market.get(market) or {}
        lines.append(f"| {market} | {_fmt(m.get('n'), 0)} | {_pct(m.get('accuracy_at_50'))} | {_fmt(m.get('brier'))} | {_fmt(m.get('logloss'))} | {_fmt(m.get('ece'))} | {_fmt(m.get('pushes'), 0)} |")

    lines.extend(["", "## Market × data quality", "", "| Market | DQ band | N | Accuracy | Brier | LogLoss |", "|---|---|---:|---:|---:|---:|"])
    for market in MARKETS:
        for band, payload in ((diag.get("by_data_quality") or {}).get(market) or {}).items():
            lines.append(f"| {market} | {band} | {_fmt(payload.get('n'), 0)} | {_pct(payload.get('accuracy_at_50'))} | {_fmt(payload.get('brier'))} | {_fmt(payload.get('logloss'))} |")

    rl = diag.get("runline") or {}
    rlp = rl.get("projected_margin") or {}
    lines.extend(["", "## Run Line diagnostic", ""])
    lines.append(f"Probability sample: **{(rl.get('overall') or {}).get('n', 0)}** • accuracy {_pct((rl.get('overall') or {}).get('accuracy_at_50'))} • projected-margin sample **{rlp.get('n', 0)}** • margin MAE {_fmt(rlp.get('mae_runs'))} • bias {_fmt(rlp.get('bias_runs'))}")
    if rl.get("by_abs_projected_margin"):
        lines.extend(["", "| |Projected margin| | N | Accuracy | Brier |", "|---|---:|---:|---:|"])
        for band, payload in rl["by_abs_projected_margin"].items():
            lines.append(f"| {band} | {_fmt(payload.get('n'), 0)} | {_pct(payload.get('accuracy_at_50'))} | {_fmt(payload.get('brier'))} |")

    total = diag.get("total") or {}
    tp = total.get("projection") or {}
    lines.extend(["", "## Total / Over-Under diagnostic", ""])
    lines.append(f"Probability sample: **{(total.get('overall') or {}).get('n', 0)}** • accuracy {_pct((total.get('overall') or {}).get('accuracy_at_50'))} • run-projection sample **{tp.get('n', 0)}** • total MAE {_fmt(tp.get('mae_runs'))} • bias {_fmt(tp.get('bias_runs'))}")
    if total.get("by_market_line"):
        lines.extend(["", "| Total line | N | Accuracy | Brier |", "|---|---:|---:|---:|"])
        for band, payload in total["by_market_line"].items():
            lines.append(f"| {band} | {_fmt(payload.get('n'), 0)} | {_pct(payload.get('accuracy_at_50'))} | {_fmt(payload.get('brier'))} |")

    lines.extend(["", "## Posterior shadow monitor", "", "| Market | N | Δ Brier | Δ LogLoss | Status |", "|---|---:|---:|---:|---|"])
    for market in MARKETS:
        payload = ((diag.get("posterior_shadow") or {}).get(market) or {})
        lines.append(f"| {market} | {_fmt(payload.get('n'), 0)} | {_fmt(payload.get('brier_improvement'), 4)} | {_fmt(payload.get('logloss_improvement'), 4)} | {payload.get('status', 'COLLECTING')} |")

    lines.extend(["", "## Data-quality bands (run projection)", "", "| DQ band | Games | Run MAE total | Brier | LogLoss |", "|---|---:|---:|---:|---:|"])
    for band, payload in (cum.get("by_data_quality") or {}).items():
        lines.append(f"| {band} | {_fmt(payload.get('games'), 0)} | {_fmt((payload.get('runs') or {}).get('total_mae_runs'))} | {_fmt((payload.get('probability') or {}).get('brier'))} | {_fmt((payload.get('probability') or {}).get('logloss'))} |")

    teams = report.get("by_team") or {}
    worst = sorted(teams.items(), key=lambda kv: (-float(kv[1].get("run_mae") or 0), -int(kv[1].get("n") or 0)))[:10]
    lines.extend(["", "## Highest run-error teams — shrinkage protected", "", "| Team | N | Run MAE | Raw bias | Shrunk bias | Reliability |", "|---|---:|---:|---:|---:|---:|"])
    for team, payload in worst:
        lines.append(f"| {team} | {_fmt(payload.get('n'), 0)} | {_fmt(payload.get('run_mae'))} | {_fmt(payload.get('run_bias'))} | {_fmt(payload.get('shrunk_run_bias'))} | {_pct(payload.get('reliability'))} |")

    venues = report.get("by_venue") or {}
    venue_worst = sorted(venues.items(), key=lambda kv: (-float((kv[1].get("runs") or {}).get("total_mae_runs") or 0), -int(kv[1].get("games") or 0)))[:8]
    lines.extend(["", "## Highest run-error venues — shrinkage protected", "", "| Venue | Games | Total MAE | Raw total bias | Shrunk bias |", "|---|---:|---:|---:|---:|"])
    for venue, payload in venue_worst:
        runs = payload.get("runs") or {}
        shrink = payload.get("shrinkage") or {}
        lines.append(f"| {venue} | {_fmt(payload.get('games'), 0)} | {_fmt(runs.get('total_mae_runs'))} | {_fmt(runs.get('total_bias_runs'))} | {_fmt(shrink.get('shrunk_total_bias_runs'))} |")

    blockers = (((cum.get("data_quality_components") or {}).get("blockers")) or {})
    lines.extend(["", "## Data blockers", ""])
    if blockers:
        for name, count in blockers.items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- None recorded in the current-generation settled sample.")
    lines.append("")
    lines.append("> Diagnostic only. Market tracking, posterior monitoring, shrinkage and the 100-game checkpoint do not modify V13.10 probabilities or selection behavior.")
    return "\n".join(lines) + "\n"


def main() -> None:
    report = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    OUT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
