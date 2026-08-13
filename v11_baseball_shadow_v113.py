#!/usr/bin/env python3
"""V11.1.3 data-quality hardening for the baseball shadow layer.

Keeps prior shadow versions immutable while fixing two remaining live-data
quality issues discovered in run #38:
- suspicious non-pitchers leaking into bullpen candidates;
- projected hitters falling back to league-average OPS when boxscores do not
  expose season hitting stats pregame.
"""
from __future__ import annotations

import bot as core
import v11_baseball_shadow_v112 as v112

base = v112.base
SHADOW_VERSION = "11.1.3-baseball-shadow-v4"
MIN_LINEUP_STATS_COVERAGE = 0.55

_old_recent_context = v112._recent_context
_old_lineup = base._lineup
_old_self_test = v112.self_test

_POSITION_CACHE = {}
_HITTING_CACHE = {}


def _normalize_stat_payload(value):
    if not isinstance(value, dict):
        return {}
    if isinstance(value.get("stat"), dict):
        return value["stat"]
    return value


def _meaningful_hitting(st):
    st = _normalize_stat_payload(st)
    pa = core.num(st.get("plateAppearances"), 0)
    if pa <= 0:
        return False
    raw_ops = core.num(st.get("ops"), 0)
    if .2 <= raw_ops <= 1.5:
        return True
    obp = core.num(st.get("onBasePercentage"), 0)
    slg = core.num(st.get("sluggingPercentage"), 0)
    return obp > 0 and slg > 0


def _player_hitting(pid):
    pid = int(pid)
    if pid in _HITTING_CACHE:
        return _HITTING_CACHE[pid]
    st = {}
    try:
        st = _normalize_stat_payload(core.player_stats(pid, "hitting") or {})
    except Exception:
        st = {}
    _HITTING_CACHE[pid] = st if _meaningful_hitting(st) else {}
    return _HITTING_CACHE[pid]


def _primary_role(pid):
    pid = int(pid)
    if pid in _POSITION_CACHE:
        return _POSITION_CACHE[pid]
    info = {}
    try:
        info = core.person_info(pid) or {}
    except Exception:
        info = {}
    pos = info.get("primaryPosition") or {}
    text = " ".join(str(pos.get(k) or "") for k in ("type", "name", "abbreviation", "code")).lower()
    if "two-way" in text or "two way" in text:
        role = "TWO_WAY"
    elif "pitcher" in text or str(pos.get("abbreviation") or "").upper() == "P" or str(pos.get("code") or "") == "1":
        role = "PITCHER"
    elif text.strip():
        role = "POSITION_PLAYER"
    else:
        role = "UNKNOWN"
    _POSITION_CACHE[pid] = role
    return role


def _needs_role_check(info):
    st = info.get("season") or {}
    ip = base._innings(st.get("inningsPitched"))
    saves = core.num(st.get("saves"), 0)
    holds = core.num(st.get("holds"), 0)
    seen = core.num(info.get("seen"), 0)
    # Established relievers do not need an extra person lookup. Low-volume,
    # no-leverage profiles are checked against MLB's primary position.
    return ip < 15.0 and saves + holds <= 0 and seen <= 3


def _recent_context(team_ids, target):
    ctx = _old_recent_context(team_ids, target)
    for team_ctx in ctx.values():
        relievers = team_ctx.get("relievers") or {}
        filt = dict(team_ctx.get("bullpen_filter") or {})
        removed_non_pitcher = 0
        checked_roles = 0
        for pid, info in list(relievers.items()):
            if not _needs_role_check(info):
                continue
            checked_roles += 1
            if _primary_role(pid) == "POSITION_PLAYER":
                relievers.pop(pid, None)
                removed_non_pitcher += 1
        filt["checked_primary_positions"] = checked_roles
        filt["removed_non_pitcher_primary_position"] = removed_non_pitcher
        filt["remaining_candidates"] = len(relievers)
        team_ctx["bullpen_filter"] = filt
    return ctx


def _candidate_lineup_ids(box, team_ctx):
    ids = []
    for pid in base._current_order(box)[:9]:
        if pid not in ids:
            ids.append(pid)
    hitters = team_ctx.get("hitters") or {}
    regular = sorted(
        (
            -core.num(info.get("appearances"), 0),
            core.num(info.get("order_sum"), 0) / max(core.num(info.get("appearances"), 0), 1),
            int(pid),
        )
        for pid, info in hitters.items()
        if core.num(info.get("appearances"), 0) > 0
    )
    for _, _, pid in regular[:9]:
        if pid not in ids:
            ids.append(pid)
    return ids


def _enrich_lineup_stats(box, team_ctx):
    hitters = team_ctx.get("hitters") or {}
    requested = 0
    filled = 0
    for pid in _candidate_lineup_ids(box, team_ctx):
        info = hitters.setdefault(pid, {"appearances": 0, "order_sum": 0.0, "season": {}, "name": str(pid), "bat_side": ""})
        if _meaningful_hitting(info.get("season") or {}):
            continue
        entry = base._entry(box, pid)
        current = v112._bstat(entry)
        if _meaningful_hitting(current):
            info["season"] = current
            filled += 1
            continue
        requested += 1
        current = _player_hitting(pid)
        if current:
            info["season"] = current
            filled += 1
    return {"fallback_requests": requested, "fallback_filled": filled}


def _lineup(box, feed, team_ctx):
    enrichment = _enrich_lineup_stats(box, team_ctx)
    out = _old_lineup(box, feed, team_ctx)
    hitters_ctx = team_ctx.get("hitters") or {}
    real = 0
    total = 0
    for hitter in out.get("hitters") or []:
        pid = int(hitter.get("id") or 0)
        if not pid:
            continue
        total += 1
        entry = base._entry(box, pid)
        st = v112._bstat(entry) or (hitters_ctx.get(pid, {}) or {}).get("season") or {}
        if _meaningful_hitting(st):
            real += 1
    coverage = real / total if total else 0.0
    order_available = bool(out.get("available"))
    quality_available = coverage >= MIN_LINEUP_STATS_COVERAGE
    out["order_available"] = order_available
    out["stats_coverage"] = round(coverage, 4)
    out["real_ops_hitters"] = real
    out["quality_available"] = quality_available
    out["stats_source"] = "boxscore-season-or-player-stats-v113"
    out["fallback_requests"] = enrichment["fallback_requests"]
    out["fallback_filled"] = enrichment["fallback_filled"]
    out["available"] = bool(order_available and quality_available)
    if not quality_available:
        # Do not let a mostly league-average fallback produce a confident
        # lineup signal. The projected order remains journaled separately.
        out["score"] = 0.0
    return out


def _bullpen(team_ctx, starter):
    out = v112._bullpen(team_ctx, starter)
    out["source"] = "recent-final-games-role-filtered-v113"
    out["filter"] = dict(team_ctx.get("bullpen_filter") or {})
    return out


def install():
    v112.install()
    base.SHADOW_VERSION = SHADOW_VERSION
    base._recent_context = _recent_context
    base._bullpen = _bullpen
    base._lineup = _lineup


def self_test():
    install()
    assert _meaningful_hitting({"plateAppearances": 100, "ops": .812})
    assert not _meaningful_hitting({"plateAppearances": 0, "ops": .812})
    assert not _meaningful_hitting({})
    assert _needs_role_check({"season": {"inningsPitched": "2.0", "saves": 0, "holds": 0}, "seen": 2})
    assert not _needs_role_check({"season": {"inningsPitched": "40.0", "saves": 0, "holds": 0}, "seen": 10})
    _old_self_test()
    print("SELF-TEST V11.1.3 DATA QUALITY OK")


def main():
    install()
    base.main()


if __name__ == "__main__":
    main()
