from __future__ import annotations

"""Conservative staking policy for statistically certified Pulsar bets.

Sizing uses the LOWER probability confidence bound, quarter Kelly, and hard
portfolio caps. It returns zero stake for every non-BET / uncertified decision.
"""

import math
from typing import Any

KELLY_FRACTION = 0.25
MAX_BET_BANKROLL_FRACTION = 0.010
MAX_DAILY_BANKROLL_FRACTION = 0.030
MAX_MARKET_BANKROLL_FRACTION = 0.020


def _num(value: Any) -> float | None:
    try:
        out=float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def full_kelly(probability: float, decimal_odds: float) -> float:
    p=float(probability); odds=float(decimal_odds); b=odds-1.0
    if not 0 < p < 1 or b <= 0: return 0.0
    return max(0.0,(b*p-(1-p))/b)


def conservative_stake_fraction(candidate: dict[str, Any], *, certified: bool) -> float:
    if not certified or candidate.get("status") != "BET": return 0.0
    p=_num(candidate.get("lower_probability")); odds=_num(candidate.get("price"))
    if p is None or odds is None or odds <= 1: return 0.0
    raw=KELLY_FRACTION*full_kelly(p,odds)
    return min(MAX_BET_BANKROLL_FRACTION,max(0.0,raw))


def unit_tier(stake_fraction: float) -> int:
    """Map conservative bankroll fraction to the existing 1U/2U/3U display."""
    f=max(0.0,float(stake_fraction))
    if f <= 0: return 0
    if f < 0.004: return 1
    if f < 0.007: return 2
    return 3


def size_candidates(candidates: list[dict[str, Any]], *, certified: bool) -> list[dict[str, Any]]:
    sized=[]; daily_used=0.0; market_used: dict[str,float]={}
    for row in sorted(candidates,key=lambda r:float(r.get("robust_edge_pp") or -999),reverse=True):
        out=dict(row); desired=conservative_stake_fraction(row,certified=certified); market=str(row.get("market") or "UNKNOWN"); remaining_day=max(0.0,MAX_DAILY_BANKROLL_FRACTION-daily_used); remaining_market=max(0.0,MAX_MARKET_BANKROLL_FRACTION-market_used.get(market,0.0)); stake=min(desired,remaining_day,remaining_market); out["stake_fraction"]=stake; out["unit_tier"]=unit_tier(stake); out["staking_method"]="lower-bound quarter-Kelly with per-bet/market/day caps" if stake>0 else "zero-stake fail-closed"; sized.append(out); daily_used+=stake; market_used[market]=market_used.get(market,0.0)+stake
    return sized
