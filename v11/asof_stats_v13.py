from __future__ import annotations

from typing import Any


class HistoricalStatsUnavailable(RuntimeError):
    pass


def require_as_of(as_of: str | None) -> str:
    if not as_of:
        raise ValueError("explicit as_of is required by V13 feature builders")
    return str(as_of)


def live_or_replay_season_stats(core, team_id: Any, group: str, *, as_of: str,
                                historical: bool = False) -> dict[str,Any]:
    """Access season aggregates without silently leaking future information.

    Current/replayed production calls are safe because the HTTP source itself is
    captured at the requested pregame as_of. A historical reconstruction is
    refused unless it runs from a source replay/snapshot; V13 never calls today's
    season endpoint and pretends it was historical.
    """
    require_as_of(as_of)
    if historical and core.replay_as_of() is None:
        raise HistoricalStatsUnavailable(
            "historical season aggregate requires recorded source replay/snapshot"
        )
    return core.season_stats(team_id, group)


def live_or_replay_player_stats(core, player_id: Any, group: str, *, as_of: str,
                                historical: bool = False) -> dict[str,Any]:
    require_as_of(as_of)
    if historical and core.replay_as_of() is None:
        raise HistoricalStatsUnavailable(
            "historical player aggregate requires recorded source replay/snapshot"
        )
    return core.player_stats(player_id, group)
