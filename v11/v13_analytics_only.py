from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ANALYTICS_ONLY_REASON = "V13 analytics-only: betting action disabled"


def _scrub_option(option: dict[str, Any] | None) -> None:
    if not isinstance(option, dict):
        return
    execution = option.get("winamax_eval")
    if not isinstance(execution, dict):
        return
    # Keep reference prices, value gates, DQ and selection scores for analytics,
    # but remove every state that can represent an actionable recommendation.
    execution["official_selected"] = False
    execution["selected"] = False
    execution["official_units"] = 0.0
    execution["units"] = 0.0
    execution["stake_eur"] = 0.0
    execution["official_reason"] = ANALYTICS_ONLY_REASON


def suppress_allocation(results, allocation):
    """Keep selector diagnostics but make the V13 output non-actionable.

    The legacy selector is still allowed to calculate price gates, conservative
    EV, DQ and selection scores because Discord analytics uses those fields.
    Any betting decision produced by that legacy layer is then scrubbed before
    runner/storage can consume it.
    """
    try:
        portfolio, _chosen, _combo, pool = allocation
    except Exception as exc:
        raise RuntimeError(f"Unexpected selector allocation contract: {exc}") from exc

    for result in results or []:
        for option in (result or {}).get("options") or []:
            _scrub_option(option)
    for item in pool or []:
        if isinstance(item, dict):
            _scrub_option(item.get("rec"))

    clean_portfolio = dict(portfolio or {})
    clean_portfolio.update({
        "analytics_only": True,
        "betting_actions_disabled": True,
        "new_allocated": 0.0,
        "allocated": 0.0,
        "new_official_count": 0,
        "official_count": 0,
        "new_official_units": 0.0,
        "official_units": 0.0,
        "combo_official": False,
        "combo_units": 0.0,
        "staking": "disabled: V13 predictive analytics only",
    })
    return clean_portfolio, [], {}, pool


def disabled_record_selected_bets(*_args, **_kwargs) -> int:
    """Fail-closed storage guard for V13 analytics-only runs."""
    return 0


def assert_payload(payload: dict[str, Any]) -> bool:
    """Reject any persisted V13 Discord payload that contains betting actions."""
    if payload.get("chosen"):
        raise RuntimeError("V13 analytics-only payload contains chosen recommendations")
    if (payload.get("combo") or {}).get("official"):
        raise RuntimeError("V13 analytics-only payload contains an official combo")
    for result in payload.get("results") or []:
        for option in (result or {}).get("options") or []:
            execution = option.get("winamax_eval") or {}
            if execution.get("official_selected") or execution.get("selected"):
                raise RuntimeError(
                    f"V13 analytics-only payload contains an actionable option game={result.get('game_pk')}"
                )
            if float(execution.get("official_units") or 0.0) != 0.0:
                raise RuntimeError(
                    f"V13 analytics-only payload contains non-zero official units game={result.get('game_pk')}"
                )
    return True


def assert_payload_file(path: str | Path) -> bool:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"V13 analytics-only payload missing: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    return assert_payload(payload)
