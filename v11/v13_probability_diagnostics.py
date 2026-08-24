from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract
from . import v13_daily_tracking as tracking

OUT = Path("data/v13_probability_diagnostics.json")
SCHEMA = "v13-probability-diagnostics-v3"
MARKETS = ("ML", "RUNLINE", "TOTAL")
PHASE_RANK = {"EARLY": 0, "LATE": 1, "FINAL": 2}
MARKET_BENCHMARK_FIELDS = (
    ("p_market", "MODEL_SNAPSHOT_SHARP"),
    ("close_sharp_fair", "CLOSING_SHARP"),
    ("t60_sharp_fair", "T60_SHARP"),
)


def _num(v: Any, d: float | None = None) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d


def _norm(v: Any) -> str:
    return "".join(c.lower() for c in str(v or "") if c.isalnum())


def _gap_bin(gap: float) -> str:
    pp = 100 * gap
    if pp < -10:
        return "<-10pp"
    if pp < -6:
        return "-10/-6pp"
    if pp < -3:
        return "-6/-3pp"
    if pp < 0:
        return "-3/0pp"
    if pp < 3:
        return "0/3pp"
    if pp < 6:
        return "3/6pp"
    if pp < 10:
        return "6/10pp"
    return ">=10pp"


def _rank(s: dict[str, Any]) -> tuple[int, str]:
    phase = str(s.get("phase") or s.get("observation_phase") or "").upper()
    at = str(s.get("observation_at") or s.get("observed_at") or "")
    return PHASE_RANK.get(phase, -1), at


def _current_generation_state(s: dict[str, Any]) -> bool:
    if s.get("model_generation") != contract.MODEL_GENERATION_FINGERPRINT:
        return False
    payload = s.get("predictive_contract") or {}
    return contract.CONTRACT.compatible_with(payload)


def _market_benchmark(s: dict[str, Any]) -> tuple[float | None, str | None]:
    """Return a real captured sharp probability; never synthesize one.

    Prefer the sharp fair probability captured with the model snapshot. Older
    RL/TOTAL observations often lacked that field even though the tracking poll
    later captured a real pregame closing or T-60 sharp probability for the
    exact same side and line. Those observations are valid diagnostic market
    benchmarks and are used only when the contemporaneous field is absent.
    """
    for field, source in MARKET_BENCHMARK_FIELDS:
        value = _num(s.get(field))
        if value is not None and 0 < value < 1:
            return value, source
    return None, None


def _scoreable(s: dict[str, Any]) -> bool:
    market_probability, _ = _market_benchmark(s)
    return _num(s.get("p_model")) is not None and market_probability is not None


def _preferred_side(states: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Choose one real, comparable market target without synthesising a line.

    The tracking journal historically did not always persist ``canonical=True``
    on RUNLINE/TOTAL. We prefer a genuine canonical marker, but allow a strict
    fallback only when the observed market surface leaves exactly one
    unambiguous preferred side/line with a real captured sharp benchmark.
    """
    if not states:
        return None, "EMPTY"
    market = str(states[0].get("market") or "").upper()
    home = _norm(states[0].get("home"))
    scoreable = [s for s in states if _scoreable(s)]
    if not scoreable:
        return None, "NO_REAL_MODEL_MARKET_PAIR"

    marked = [s for s in scoreable if bool(s.get("canonical"))]
    pool = marked or scoreable
    source = "CANONICAL_MARKER" if marked else "UNAMBIGUOUS_REAL_MARKET_FALLBACK"

    if market == "ML":
        preferred = [s for s in pool if _norm(s.get("pick")) == home]
    elif market == "RUNLINE":
        preferred = [s for s in pool if _norm(s.get("pick")) == home and _num(s.get("point")) is not None]
    elif market == "TOTAL":
        preferred = [s for s in pool if str(s.get("pick") or "").lower() == "over" and _num(s.get("point")) is not None]
    else:
        return None, "UNSUPPORTED_MARKET"

    if not preferred:
        return None, "PREFERRED_SIDE_MISSING"

    line_tokens = {
        "game" if market == "ML" else f"{_num(s.get('point')):g}"
        for s in preferred
    }
    if len(line_tokens) != 1:
        return None, "AMBIGUOUS_REAL_LINES"

    chosen = sorted(
        preferred,
        key=lambda s: (
            str(s.get("tracking_key") or ""),
            str(s.get("pick") or ""),
            str(s.get("point") or ""),
        ),
    )[0]
    return chosen, source


def _independent_selection(
    states: list[dict[str, Any]], *, current_generation_only: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    raw_counts = Counter()
    for s in states:
        if current_generation_only and not _current_generation_state(s):
            continue
        if s.get("settled_result") not in {"WIN", "LOSS"}:
            continue
        market = str(s.get("market") or "").upper()
        gid = str(s.get("game_pk") or "")
        if not gid or market not in MARKETS:
            continue
        raw_counts[f"settled_{market}"] += 1
        groups.setdefault((gid, market), []).append(s)

    selected: list[dict[str, Any]] = []
    reasons = Counter()
    benchmark_sources = Counter()
    by_market = {m: Counter() for m in MARKETS}
    for (_gid, market), group in groups.items():
        scoreable = [s for s in group if _scoreable(s)]
        if not scoreable:
            reasons["NO_REAL_MODEL_MARKET_PAIR"] += 1
            by_market[market]["excluded_no_real_model_market_pair"] += 1
            continue
        latest_rank = max(_rank(s) for s in scoreable)
        latest = [s for s in scoreable if _rank(s) == latest_rank]
        chosen, reason = _preferred_side(latest)
        if chosen is None:
            reasons[reason] += 1
            by_market[market][f"excluded_{reason.lower()}"] += 1
            continue
        market_probability, benchmark_source = _market_benchmark(chosen)
        if market_probability is None or benchmark_source is None:
            reasons["NO_REAL_MODEL_MARKET_PAIR"] += 1
            by_market[market]["excluded_no_real_model_market_pair"] += 1
            continue
        selected.append(chosen)
        reasons[reason] += 1
        benchmark_sources[benchmark_source] += 1
        by_market[market]["selected"] += 1
        by_market[market][f"selected_via_{reason.lower()}"] += 1
        by_market[market][f"benchmark_{benchmark_source.lower()}"] += 1

    selected.sort(
        key=lambda s: (
            str(s.get("game_date") or ""),
            str(s.get("game_pk") or ""),
            str(s.get("market") or ""),
        )
    )
    audit = {
        "policy": "latest scoreable pregame snapshot per unique game+market; prefer persisted canonical marker; otherwise accept exactly one unambiguous real preferred side/line; benchmark priority is model-snapshot sharp then captured closing sharp then captured T-60 sharp; never synthesize line or market probability",
        "groups_seen": len(groups),
        "selected": len(selected),
        "reasons": dict(reasons),
        "benchmark_sources": dict(benchmark_sources),
        "by_market": {m: dict(c) for m, c in by_market.items()},
        "raw_settled_state_counts": {m: raw_counts.get(f"settled_{m}", 0) for m in MARKETS},
    }
    return selected, audit


def independent_states(states: list[dict[str, Any]], *, current_generation_only: bool = False) -> list[dict[str, Any]]:
    """Collapse repeated snapshots and complementary sides to independent targets."""
    return _independent_selection(states, current_generation_only=current_generation_only)[0]


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    b_model = b_market = ll_model = ll_market = 0.0
    residuals: list[float] = []
    gaps: list[float] = []
    source_counts = Counter()
    scored = 0
    for s in rows:
        benchmark, source = _market_benchmark(s)
        pm = _num(s.get("p_model"))
        if benchmark is None or source is None or pm is None:
            continue
        pm = max(.001, min(.999, pm))
        ps = max(.001, min(.999, benchmark))
        y = 1 if s.get("settled_result") == "WIN" else 0
        gap = pm - ps
        b_model += (pm-y) ** 2
        b_market += (ps-y) ** 2
        ll_model += -(y*math.log(pm) + (1-y)*math.log(1-pm))
        ll_market += -(y*math.log(ps) + (1-y)*math.log(1-ps))
        residuals.append(y-ps)
        gaps.append(gap)
        source_counts[source] += 1
        scored += 1
    if not scored:
        return {"n": 0}
    n = scored
    mean_gap = sum(gaps) / n
    mean_res = sum(residuals) / n
    var = sum((x-mean_gap) ** 2 for x in gaps)
    slope = (
        sum((x-mean_gap)*(y-mean_res) for x, y in zip(gaps, residuals)) / var
        if var > 1e-12 else None
    )
    return {
        "n": n,
        "model_brier": b_model/n,
        "market_brier": b_market/n,
        "brier_gain_vs_market": (b_market-b_model)/n,
        "model_logloss": ll_model/n,
        "market_logloss": ll_market/n,
        "logloss_gain_vs_market": (ll_market-ll_model)/n,
        "mean_model_minus_market": mean_gap,
        "outcome_residual_vs_market": mean_res,
        "gap_residual_slope": slope,
        "market_benchmark_sources": dict(source_counts),
    }


def _availability(states: list[dict[str, Any]]) -> dict[str, Any]:
    by_market = {m: Counter() for m in MARKETS}
    totals = Counter()
    for s in states:
        if s.get("settled_result") not in {"WIN", "LOSS"}:
            continue
        market = str(s.get("market") or "").upper()
        if market not in by_market:
            continue
        totals["settled_states"] += 1
        by_market[market]["settled_states"] += 1
        if bool(s.get("canonical")):
            totals["persisted_canonical_states"] += 1
            by_market[market]["persisted_canonical_states"] += 1
        if _num(s.get("p_model")) is None:
            totals["missing_model_probability_states"] += 1
            by_market[market]["missing_model_probability_states"] += 1
        benchmark, source = _market_benchmark(s)
        if benchmark is None:
            totals["missing_market_probability_states"] += 1
            by_market[market]["missing_market_probability_states"] += 1
        else:
            totals["real_market_benchmark_states"] += 1
            by_market[market]["real_market_benchmark_states"] += 1
            by_market[market][f"benchmark_{str(source).lower()}_states"] += 1
        if _current_generation_state(s):
            totals["current_generation_attested_states"] += 1
            by_market[market]["current_generation_attested_states"] += 1
        else:
            totals["not_current_generation_attested_states"] += 1
            by_market[market]["not_current_generation_attested_states"] += 1

    current, current_audit = _independent_selection(states, current_generation_only=True)
    historical, historical_audit = _independent_selection(states, current_generation_only=False)
    for row in current:
        market = str(row.get("market") or "").upper()
        totals["current_generation_independent_scoreable"] += 1
        by_market[market]["current_generation_independent_scoreable"] += 1
    for row in historical:
        market = str(row.get("market") or "").upper()
        totals["all_generation_independent_scoreable"] += 1
        by_market[market]["all_generation_independent_scoreable"] += 1

    return {
        "total": dict(totals),
        "by_market": {m: dict(v) for m, v in by_market.items()},
        "current_generation_selection": current_audit,
        "all_generation_selection": historical_audit,
        "note": "market probabilities are never imputed; diagnostics prefer contemporaneous captured sharp and may fall back to a real captured pregame closing/T-60 sharp benchmark; ambiguous unmarked RL/TOTAL lines fail closed",
    }


def _view(states: list[dict[str, Any]], *, current_generation_only: bool) -> dict[str, Any]:
    rows, selection_audit = _independent_selection(states, current_generation_only=current_generation_only)
    by_market = {
        m: _metrics([r for r in rows if str(r.get("market") or "").upper() == m])
        for m in MARKETS
    }
    names = ("<-10pp", "-10/-6pp", "-6/-3pp", "-3/0pp", "0/3pp", "3/6pp", "6/10pp", ">=10pp")
    bins: dict[str, Any] = {}
    for market in MARKETS:
        subset = [r for r in rows if str(r.get("market") or "").upper() == market]
        bins[market] = {}
        for name in names:
            bucket = []
            for row in subset:
                benchmark, _source = _market_benchmark(row)
                model_probability = _num(row.get("p_model"))
                if benchmark is None or model_probability is None:
                    continue
                if _gap_bin(model_probability-benchmark) == name:
                    bucket.append(row)
            bins[market][name] = _metrics(bucket)
    return {
        "independent_targets": len(rows),
        "by_market": by_market,
        "by_model_market_gap_bin": bins,
        "selection_audit": selection_audit,
    }


def build(states: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    folded = list(tracking.fold().values()) if states is None else list(states)
    current = _view(folded, current_generation_only=True)
    historical = _view(folded, current_generation_only=False)
    return {
        "schema": SCHEMA,
        "model_generation": contract.MODEL_GENERATION_FINGERPRINT,
        "scope": "current-generation-only",
        "sample_unit": "unique game + market; latest scoreable pregame snapshot; deterministic real representative line",
        "market_benchmark_policy": "p_market at model snapshot preferred; otherwise real captured close_sharp_fair; otherwise real captured t60_sharp_fair; never imputed or reconstructed",
        "independent_targets": current["independent_targets"],
        "by_market": current["by_market"],
        "by_model_market_gap_bin": current["by_model_market_gap_bin"],
        "selection_audit": current["selection_audit"],
        "tracking_availability": _availability(folded),
        "all_generations_historical": {
            "scope": "descriptive historical only; never promotion evidence",
            **historical,
        },
        "interpretation": {
            "gap_residual_slope": "positive is desirable: larger model-minus-market gaps should correspond to larger positive outcome residuals versus the selected real sharp benchmark",
            "proper_scoring": "Brier and LogLoss are the primary comparison; repeated phases, complementary sides and ambiguous unmarked lines are excluded from the independent view",
            "generation_boundary": "top-level metrics require an explicit current model_generation and compatible predictive_contract; unattested legacy tracking rows are historical-only",
            "line_selection": "persisted canonical markers are preferred; fallback is allowed only for one unambiguous real preferred side/line",
            "benchmark_timing": "closing/T-60 sharp is diagnostic comparison evidence only and never feeds the model, selection, calibration or primary probability",
        },
    }


def main():
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
