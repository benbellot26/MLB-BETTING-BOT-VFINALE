from __future__ import annotations

import json
import math
from pathlib import Path

from . import convergence_v124

VERSION = "v12.4-research-monitor-v1"
SCHEMA = "v12-4-research-monitor-v1"
_INSTALLED = False

MODULE_LABELS = {
    "platoon": "Platoon",
    "statcast": "Statcast",
    "bullpen_player": "Bullpen",
    "lineup_player": "Lineup",
    "starter_ip": "Starter IP",
    "weather_park": "Weather x Park",
}

VARIANT_LABELS = {
    "baseline_v1232": "V12.3.2 baseline",
    "all_core": "V12.4 all_core",
    "optimized": "V12.4 optimized",
    "ensemble": "V12.4 ensemble",
}


def _num(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _norm(value):
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _key(option):
    point = option.get("point")
    return (
        str(option.get("market") or "").upper(),
        _norm(option.get("name")),
        None if point is None else round(_num(point, 0.0), 4),
    )


def load_report(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def canonical_rows(rows):
    """Use one settled point-in-time snapshot per MLB game: the latest pre-game row."""
    latest = {}
    for row in rows or []:
        if row.get("bet_type") == "COMBO" or not row.get("game_pk"):
            continue
        shadow = row.get("shadow_v124") or {}
        if not shadow.get("enabled") or shadow.get("status") == "ERROR":
            continue
        has_score = row.get("home_score") is not None and row.get("away_score") is not None
        has_result = any((o or {}).get("result") in {"WIN", "LOSS", "PUSH"} for o in row.get("options") or [])
        if not has_score or not has_result:
            continue
        gid = str(row.get("game_pk"))
        rank = str(row.get("analyzed_at") or row.get("as_of") or row.get("game_date") or "")
        if gid not in latest or rank > latest[gid][0]:
            latest[gid] = (rank, row)
    selected = [value[1] for value in latest.values()]
    selected.sort(key=lambda row: str(row.get("game_date") or row.get("analyzed_at") or row.get("game_pk") or ""))
    return selected


def _variant_market_metrics(rows):
    aggregate = {}
    for row in rows or []:
        results = {_key(o): o.get("result") for o in row.get("options") or [] if o.get("result") in {"WIN", "LOSS"}}
        variants = ((row.get("shadow_v124") or {}).get("variants") or {})
        for variant, payload in variants.items():
            markets = aggregate.setdefault(variant, {})
            for option in payload.get("options") or []:
                outcome = results.get(_key(option))
                if outcome not in {"WIN", "LOSS"}:
                    continue
                market = str(option.get("market") or "").upper()
                bucket = markets.setdefault(market, {"n": 0, "wins": 0, "brier": 0.0, "logloss": 0.0, "gt55_n": 0, "gt55_wins": 0})
                p = max(.001, min(.999, _num(option.get("p_effective"), .5)))
                y = 1 if outcome == "WIN" else 0
                bucket["n"] += 1
                bucket["wins"] += y
                bucket["brier"] += (p-y)**2
                bucket["logloss"] += -(y*math.log(p)+(1-y)*math.log(1-p))
                if p > .55:
                    bucket["gt55_n"] += 1
                    bucket["gt55_wins"] += y
    out = {}
    for variant, markets in aggregate.items():
        out[variant] = {}
        for market, bucket in markets.items():
            n = bucket["n"]
            out[variant][market] = {
                "n": n,
                "accuracy": bucket["wins"]/n if n else None,
                "brier": bucket["brier"]/n if n else None,
                "logloss": bucket["logloss"]/n if n else None,
                "gt55_n": bucket["gt55_n"],
                "gt55_hit_rate": bucket["gt55_wins"]/bucket["gt55_n"] if bucket["gt55_n"] else None,
            }
    return out


def _metric_snapshot(payload):
    payload = payload or {}
    return {
        "n": int(_num(payload.get("n"), 0) or 0),
        "accuracy": _num(payload.get("accuracy")),
        "brier": _num(payload.get("brier")),
        "logloss": _num(payload.get("logloss")),
        "gt55_n": int(_num(payload.get("gt55_n"), 0) or 0),
        "gt55_hit_rate": _num(payload.get("gt55_hit_rate")),
        "by_market": payload.get("by_market") or {},
    }


def _metric_change(current, previous):
    current = current or {}
    previous = previous or {}
    out = {}
    for key in ("accuracy", "brier", "logloss", "gt55_hit_rate"):
        a, b = _num(current.get(key)), _num(previous.get(key))
        out[key] = (a-b) if a is not None and b is not None else None
    out["n"] = int(_num(current.get("n"), 0) or 0) - int(_num(previous.get("n"), 0) or 0)
    out["gt55_n"] = int(_num(current.get("gt55_n"), 0) or 0) - int(_num(previous.get("gt55_n"), 0) or 0)
    return out


def _variant_table(predictive):
    variants = predictive.get("variants") or {}
    out = {}
    for name in ("baseline_v1232", "all_core", "optimized", "ensemble"):
        if name in variants:
            out[name] = _metric_snapshot(variants.get(name))
    return out


def _progress(optimizer, predictive):
    settled = int(_num(optimizer.get("settled_games"), predictive.get("settled_games")) or 0)
    minimum = max(1, int(_num(optimizer.get("minimum_games"), 75) or 75))
    wf = max(minimum, int(_num(optimizer.get("walk_forward_ready_games"), 150) or 150))
    mature = max(wf, int(_num(optimizer.get("mature_games"), 250) or 250))
    if settled < minimum:
        next_target = minimum
    elif settled < wf:
        next_target = wf
    elif settled < mature:
        next_target = mature
    else:
        next_target = mature
    return {
        "settled_games": settled,
        "minimum_games": minimum,
        "walk_forward_ready_games": wf,
        "mature_games": mature,
        "remaining_to_minimum": max(0, minimum-settled),
        "next_target": next_target,
        "remaining_to_next_target": max(0, next_target-settled),
        "minimum_progress": min(1.0, settled/minimum),
        "status": optimizer.get("status") or "COLLECTING",
        "stage": optimizer.get("stage") or "COLLECT",
        "optimized_shadow_active": bool(optimizer.get("active_for_v124_shadow")),
    }


def _ablations(predictive, optimizer):
    variants = predictive.get("variants") or {}
    diagnostics = optimizer.get("modules") or {}
    weights = optimizer.get("weights") or {}
    out = {}
    for module, label in MODULE_LABELS.items():
        diag = diagnostics.get(module) or {}
        variant = _metric_snapshot(variants.get(f"only_{module}") or {})
        out[module] = {
            "label": label,
            "weight": _num(weights.get(module), 0.0) or 0.0,
            "verdict": diag.get("verdict") or "WATCH",
            "brier_improvement": _num(diag.get("brier_improvement")),
            "logloss_improvement": _num(diag.get("logloss_improvement")),
            "team_run_mae_improvement": _num(diag.get("team_run_mae_improvement")),
            "objective_improvement": _num(diag.get("paired_objective_improvement")),
            "ci95": diag.get("paired_objective_ci95") or [None, None],
            "metrics": variant,
        }
    return out


def _disagreements(rows, run_id, limit=6, strong_gap=.05):
    found = []
    for row in rows or []:
        if run_id and str(row.get("run_id")) != str(run_id):
            continue
        shadow = row.get("shadow_v124") or {}
        variants = shadow.get("variants") or {}
        base = variants.get("baseline_v1232") or {}
        challenger_name = "optimized" if variants.get("optimized") else "all_core"
        challenger = variants.get(challenger_name) or {}
        bmap = {_key(o): o for o in base.get("options") or []}
        cmap = {_key(o): o for o in challenger.get("options") or []}
        for key in set(bmap) & set(cmap):
            b, c = bmap[key], cmap[key]
            pb, pc = _num(b.get("p_effective")), _num(c.get("p_effective"))
            if pb is None or pc is None:
                continue
            gap = pc-pb
            if abs(gap) < strong_gap and ((pb > .55) == (pc > .55)):
                continue
            found.append({
                "game_pk": row.get("game_pk"),
                "game": f"{row.get('away') or '?'} @ {row.get('home') or '?'}",
                "market": b.get("market"),
                "name": b.get("name"),
                "point": b.get("point"),
                "baseline_p": pb,
                "v124_p": pc,
                "gap": gap,
                "abs_gap": abs(gap),
                "crosses_55": bool((pb > .55) != (pc > .55)),
                "challenger": challenger_name,
            })
    found.sort(key=lambda x: (x["crosses_55"], x["abs_gap"]), reverse=True)
    return found[:limit]


def _evolution(predictive, previous_report):
    previous = (previous_report or {}).get("predictive_v124") or {}
    current_variants = predictive.get("variants") or {}
    previous_variants = previous.get("variants") or {}
    out = {
        "has_previous": bool(previous),
        "settled_games_delta": int(_num(predictive.get("settled_games"), 0) or 0) - int(_num(previous.get("settled_games"), 0) or 0),
        "variants": {},
    }
    for name in ("baseline_v1232", "all_core", "optimized", "ensemble"):
        if name in current_variants:
            out["variants"][name] = _metric_change(current_variants.get(name), previous_variants.get(name))
    return out


def _v115_summary(shadow):
    overall = shadow.get("overall") or {}
    strong = overall.get("strong_disagreement") or {}
    consensus = overall.get("consensus_gt55") or {}
    return {
        "settled_games": int(_num(shadow.get("settled_games"), 0) or 0),
        "consensus_gt55_n": int(_num(consensus.get("n"), 0) or 0),
        "consensus_gt55_hit_rate": _num(consensus.get("hit_rate_ex_push")),
        "strong_disagreement_n": int(_num(strong.get("n"), 0) or 0),
        "strong_disagreement_hit_rate": _num(strong.get("hit_rate_ex_push")),
        "affects_v12_selection": bool((shadow.get("activation") or {}).get("affects_v12_selection")),
    }


def build(report, previous_report=None, rows=None):
    predictive = report.get("predictive_v124") or {}
    optimizer = predictive.get("weight_optimizer") or {}
    run_id = report.get("run_id")
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "run_id": run_id,
        "analyzed_at": report.get("analyzed_at"),
        "target_date": report.get("target_date"),
        "research_only": True,
        "affects_v12_selection": False,
        "canonicalization": "latest settled pre-game snapshot per game_pk",
        "progress": _progress(optimizer, predictive),
        "variants": _variant_table(predictive),
        "ablations": _ablations(predictive, optimizer),
        "optimizer": {
            "status": optimizer.get("status") or "COLLECTING",
            "stage": optimizer.get("stage") or "COLLECT",
            "weights": optimizer.get("weights") or {},
            "walk_forward": optimizer.get("walk_forward") or {},
            "automatic_promotion": bool((optimizer.get("promotion") or {}).get("automatic", False)),
        },
        "v115": _v115_summary(report.get("shadow_challenger") or {}),
        "evolution": _evolution(predictive, previous_report),
        "current_run_disagreements": _disagreements(rows or [], run_id),
        "convergence": convergence_v124.build(rows or [], run_id=run_id, limit=12),
        "guardrails": {
            "production_engine": (report.get("production") or {}).get("engine") or "V12.3.2",
            "selector_unchanged": True,
            "staking_unchanged": True,
            "discord_monitor_non_blocking": True,
            "automatic_promotion": False,
            "convergence_research_only": True,
        },
    }


def install():
    """Canonicalize all V12.4 research metrics/optimizer evidence without touching production."""
    global _INSTALLED
    if _INSTALLED:
        return True
    from . import predictive_v124 as v124
    from . import v124_weight_optimizer as optimizer
    if getattr(v124, "_research_monitor_v124_installed", False):
        _INSTALLED = True
        return True

    original_examples = optimizer.examples
    original_metrics = v124.metrics

    def canonical_examples(rows):
        return original_examples(canonical_rows(rows))

    def metrics(rows):
        canonical = canonical_rows(rows)
        report = original_metrics(canonical)
        by_market = _variant_market_metrics(canonical)
        for name, payload in (report.get("variants") or {}).items():
            payload["by_market"] = by_market.get(name) or {}
        report["settled_games"] = len(canonical)
        report["canonicalization"] = {
            "unit": "game_pk",
            "snapshot": "latest settled pre-game row",
            "duplicate_snapshots_count_once": True,
        }
        return report

    optimizer.examples = canonical_examples
    v124.metrics = metrics
    v124._research_monitor_v124_installed = True
    _INSTALLED = True
    return True
