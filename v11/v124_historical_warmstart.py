from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from pathlib import Path

VERSION = "v12.4-historical-warmstart-v1"
SCHEMA = "v12-4-historical-warmstart-v1"
MODEL_FILE = Path(os.getenv("V124_HIST_MODEL", "data/v124_historical_warmstart.json"))
_INSTALLED = False


def _num(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def load_artifact(path=MODEL_FILE):
    path = Path(path)
    if not path.exists():
        return {
            "schema": SCHEMA, "version": VERSION, "status": "ABSENT",
            "eligible_for_warm_start": False, "historical_reconstructed_games": 0,
            "weights": {}, "guardrails": {"research_only": True, "affects_v12_selection": False},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema": SCHEMA, "version": VERSION, "status": "INVALID",
            "eligible_for_warm_start": False, "historical_reconstructed_games": 0,
            "weights": {}, "error": f"{type(exc).__name__}: {exc}",
            "guardrails": {"research_only": True, "affects_v12_selection": False},
        }
    if payload.get("schema") != SCHEMA:
        return {
            "schema": SCHEMA, "version": VERSION, "status": "INCOMPATIBLE",
            "eligible_for_warm_start": False, "historical_reconstructed_games": 0,
            "weights": {}, "error": "schema_mismatch",
            "guardrails": {"research_only": True, "affects_v12_selection": False},
        }
    payload.setdefault("status", "ELIGIBLE" if payload.get("eligible_for_warm_start") else "DIAGNOSTIC_ONLY")
    return payload


def _valid_weights(weights, modules, max_weight):
    out = {}
    for name in modules:
        out[name] = max(0.0, min(max_weight, _num((weights or {}).get(name), 0.0)))
    return out


def compose(native_model, historical, modules, max_weight, native_min, native_full):
    """Compose shadow weights while keeping the native evidence counter untouched."""
    model = deepcopy(native_model or {})
    native_n = int(_num(model.get("settled_games"), 0) or 0)
    hist_n = int(_num((historical or {}).get("historical_reconstructed_games"), 0) or 0)
    hist_eligible = bool((historical or {}).get("eligible_for_warm_start"))
    hist_weights = _valid_weights((historical or {}).get("weights"), modules, max_weight)
    native_weights = _valid_weights(model.get("weights"), modules, max_weight)

    if not hist_eligible:
        effective = native_weights
        source = "NATIVE_ONLY" if native_n >= native_min else "NO_ELIGIBLE_WARM_START"
        native_share = 1.0 if native_n >= native_min else 0.0
    elif native_n < native_min:
        effective = hist_weights
        source = "HISTORICAL_WARM_START"
        native_share = 0.0
    elif native_n < native_full:
        native_share = max(0.0, min(1.0, native_n/max(1.0, float(native_full))))
        effective = {
            name: round((1-native_share)*hist_weights[name] + native_share*native_weights[name], 4)
            for name in modules
        }
        source = "BLENDED_HISTORICAL_NATIVE"
    else:
        effective = native_weights
        source = "NATIVE_DOMINANT"
        native_share = 1.0

    model["native_settled_games"] = native_n
    model["historical_reconstructed_games"] = hist_n
    model["historical_warm_start_eligible"] = hist_eligible
    model["historical_warm_start"] = {
        "schema": (historical or {}).get("schema"),
        "status": (historical or {}).get("status"),
        "games": hist_n,
        "eligible": hist_eligible,
        "weights": hist_weights,
        "coverage": (historical or {}).get("coverage") or {},
        "walk_forward": (historical or {}).get("walk_forward") or {},
        "frozen_test": (historical or {}).get("frozen_test") or {},
        "evidence_boundary": (historical or {}).get("evidence_boundary"),
    }
    model["native_weights"] = native_weights
    model["weights"] = effective
    model["weight_source"] = source
    model["native_weight_share"] = native_share
    model["historical_weight_share"] = 1-native_share if hist_eligible else 0.0
    model["active_for_v124_shadow"] = bool(hist_eligible or native_n >= native_min)
    model["research_only"] = True
    model["affects_v12_selection"] = False
    model.setdefault("promotion", {})["automatic"] = False
    model["promotion"]["historical_cannot_promote_production"] = True
    if native_n < native_min:
        model["modules"] = (historical or {}).get("modules") or model.get("modules") or {}
        model["historical_walk_forward"] = (historical or {}).get("walk_forward") or {}
    return model


def install():
    global _INSTALLED
    if _INSTALLED:
        return True
    from . import predictive_v124 as v124
    from . import v124_weight_optimizer as optimizer
    from . import v124_research_monitor as monitor
    if getattr(optimizer, "_historical_warmstart_installed", False):
        _INSTALLED = True
        return True

    native_current_model = optimizer.current_model
    native_reset_cache = optimizer.reset_cache
    original_metrics = v124.metrics
    original_monitor_build = monitor.build
    cache = {"model": None}

    def composed_from_rows(rows):
        native = optimizer.build_model(rows)
        hist = load_artifact()
        return compose(native, hist, optimizer.MODULES, optimizer.MAX_WEIGHT, optimizer.MIN_GAMES, optimizer.WALK_FORWARD_READY_GAMES)

    def current_model():
        if cache["model"] is not None:
            return cache["model"]
        try:
            from . import journal
            cache["model"] = composed_from_rows(journal.load_rows())
        except Exception:
            cache["model"] = native_current_model()
        return cache["model"]

    def reset_cache():
        cache["model"] = None
        native_reset_cache()

    def metrics(rows):
        report = original_metrics(rows)
        native = report.get("weight_optimizer") or optimizer.build_model(rows)
        hist = load_artifact()
        report["weight_optimizer_native"] = native
        report["weight_optimizer"] = compose(native, hist, optimizer.MODULES, optimizer.MAX_WEIGHT, optimizer.MIN_GAMES, optimizer.WALK_FORWARD_READY_GAMES)
        report.setdefault("activation", {})["historical_warmstart_affects_v12_selection"] = False
        return report

    def monitor_build(report, previous_report=None, rows=None):
        payload = original_monitor_build(report, previous_report, rows)
        composed = ((report.get("predictive_v124") or {}).get("weight_optimizer") or {})
        hist = composed.get("historical_warm_start") or {}
        payload["historical_warm_start"] = {
            "games": int(_num(composed.get("historical_reconstructed_games"), 0) or 0),
            "eligible": bool(composed.get("historical_warm_start_eligible")),
            "weight_source": composed.get("weight_source"),
            "historical_weight_share": _num(composed.get("historical_weight_share"), 0.0),
            "native_weight_share": _num(composed.get("native_weight_share"), 0.0),
            "frozen_test": hist.get("frozen_test") or {},
            "coverage": hist.get("coverage") or {},
            "evidence_boundary": hist.get("evidence_boundary"),
        }
        progress = payload.setdefault("progress", {})
        progress["historical_reconstructed_games"] = payload["historical_warm_start"]["games"]
        progress["historical_warm_start_eligible"] = payload["historical_warm_start"]["eligible"]
        progress["weight_source"] = composed.get("weight_source")
        # Presentation-only suffix: native status/counter remains the actual gate.
        if payload["historical_warm_start"]["games"]:
            status = str(progress.get("status") or "COLLECTING")
            tag = "HIST-WARM" if payload["historical_warm_start"]["eligible"] else "HIST-DIAG"
            progress["status"] = f"{status} • {tag} {payload['historical_warm_start']['games']}"
        return payload

    optimizer.current_model = current_model
    optimizer.reset_cache = reset_cache
    v124.metrics = metrics
    monitor.build = monitor_build
    optimizer._historical_warmstart_installed = True
    _INSTALLED = True
    return True
