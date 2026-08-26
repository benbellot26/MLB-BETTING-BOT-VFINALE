from __future__ import annotations

"""Conservative portfolio staking for statistically certified Pulsar bets.

Sizing uses the LOWER probability confidence bound and quarter Kelly. Caps are
applied to the whole slate, not independently inside each game: per-bet, per-game
(correlation proxy), per-market and per-day exposure are all fail-closed.
"""

import math
from typing import Any

KELLY_FRACTION = 0.25
MAX_BET_BANKROLL_FRACTION = 0.010
MAX_GAME_BANKROLL_FRACTION = 0.015
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


def _game_key(row:dict[str,Any])->str:
    return str(row.get("game_pk") or row.get("_game_pk") or "UNKNOWN_GAME")


def _market_key(row:dict[str,Any])->str:
    # Broad market exposure is intentional: both run-line orientations share RL.
    return str(row.get("market") or "UNKNOWN")


def size_portfolio(candidates:list[dict[str,Any]],*,certified:bool)->list[dict[str,Any]]:
    """Size an entire slate in one pass.

    `candidates` may include helper metadata such as `_result_index`; it is
    preserved in the returned rows so callers can map allocations back to games.
    The global sort ensures the strongest robust edges consume scarce portfolio
    capacity first.
    """
    sized=[]; daily_used=0.0; market_used:dict[str,float]={}; game_used:dict[str,float]={}
    ordered=sorted(candidates,key=lambda r:(float(r.get("robust_edge_pp") or -999),float(r.get("model_edge_pp") or -999)),reverse=True)
    for row in ordered:
        out=dict(row); desired=conservative_stake_fraction(row,certified=certified); game=_game_key(row); market=_market_key(row)
        remaining_day=max(0.0,MAX_DAILY_BANKROLL_FRACTION-daily_used)
        remaining_market=max(0.0,MAX_MARKET_BANKROLL_FRACTION-market_used.get(market,0.0))
        remaining_game=max(0.0,MAX_GAME_BANKROLL_FRACTION-game_used.get(game,0.0))
        stake=min(desired,remaining_day,remaining_market,remaining_game)
        out["stake_fraction"]=stake; out["unit_tier"]=unit_tier(stake)
        out["staking_method"]="lower-bound quarter-Kelly with per-bet/game/market/day portfolio caps" if stake>0 else "zero-stake fail-closed"
        out["staking_limits"]={"per_bet":MAX_BET_BANKROLL_FRACTION,"per_game":MAX_GAME_BANKROLL_FRACTION,"per_market":MAX_MARKET_BANKROLL_FRACTION,"per_day":MAX_DAILY_BANKROLL_FRACTION}
        out["portfolio_exposure_after"]={"day":daily_used+stake,"game":game_used.get(game,0.0)+stake,"market":market_used.get(market,0.0)+stake}
        sized.append(out); daily_used+=stake; game_used[game]=game_used.get(game,0.0)+stake; market_used[market]=market_used.get(market,0.0)+stake
    return sized


def size_candidates(candidates: list[dict[str, Any]], *, certified: bool) -> list[dict[str, Any]]:
    """Compatibility wrapper for a single-game candidate set.

    New production code should use `size_portfolio` across the whole slate.
    Treating this list as one game also prevents correlated same-game markets
    from exceeding the same-game cap in legacy callers.
    """
    prepared=[]
    for row in candidates:
        item=dict(row); item.setdefault("_game_pk","__SINGLE_GAME_CALL__"); prepared.append(item)
    return size_portfolio(prepared,certified=certified)
