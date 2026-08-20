from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import math
from statistics import mean
from typing import Any, Callable
import urllib.parse
import urllib.request

from .constants import LINEUP_WEIGHTS, STATIC_PARK, TEAM_COORD
from .structural import LeagueBaselines, Starter, StructuralInputs, TeamInputs, enhance_starter, historical_pitcher_prior

MLB_API = "https://statsapi.mlb.com/api/"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _default_fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "MLB-Betting-Bot-V14", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read().decode("utf-8", "replace")
    return json.loads(raw) if raw else {}


def _stat_split(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        splits = (payload.get("stats") or [{}])[0].get("splits") or []
        return splits[0].get("stat", {}) if splits else {}
    except Exception:
        return {}


def _distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float | None:
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2-lat1)/2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2-lon1)/2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


class MLBDataClient:
    """Small V14-owned MLB Stats API data provider.

    The provider deliberately reproduces only inputs used by the working V13.10
    structural champion. It does not collect market prices, weather, Statcast or
    rich research modules. `fetch_json` is injectable so historical replay/tests
    can use immutable recorded responses instead of the live network.
    """

    def __init__(self, *, season: int, target_date: str, as_of: str,
                 fetch_json: Callable[[str], dict[str, Any]] | None = None,
                 source_timestamp_attested: bool = False) -> None:
        self.season = int(season)
        self.target_date = str(target_date)
        self.as_of = str(as_of)
        self.fetch_json = fetch_json or _default_fetch
        self.source_timestamp_attested = bool(source_timestamp_attested)
        self._cache: dict[tuple[Any, ...], Any] = {}
        self.calls: list[dict[str, Any]] = []

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode(params or {}, safe=",")
        url = MLB_API + path.lstrip("/") + (("?" + query) if query else "")
        key = (path, tuple(sorted((params or {}).items())))
        if key in self._cache:
            return self._cache[key]
        payload = self.fetch_json(url) or {}
        self._cache[key] = payload
        self.calls.append({
            "url": url,
            "observed_at": self.as_of,
            "timestamp_basis": "recorded_retrieval_time" if self.source_timestamp_attested else "live_retrieval_time",
            "source_timestamp_attested": self.source_timestamp_attested,
            "point_in_time": True,
        })
        return payload

    def schedule(self, day: str, team_id: int | str | None = None,
                 hydrate: str = "probablePitcher,linescore") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"sportId": 1, "date": str(day), "hydrate": hydrate}
        if team_id:
            params["teamId"] = team_id
        payload = self._get("v1/schedule", params)
        return [game for block in payload.get("dates", []) for game in block.get("games", [])]

    def team_stats(self, team_id: int | str, group: str) -> dict[str, Any]:
        return _stat_split(self._get(
            f"v1/teams/{team_id}/stats",
            {"stats": "season", "group": group, "season": self.season},
        ))

    def player_stats(self, player_id: int | str | None, group: str = "pitching") -> dict[str, Any]:
        if not player_id:
            return {}
        return _stat_split(self._get(
            f"v1/people/{player_id}/stats",
            {"stats": "season", "group": group, "season": self.season},
        ))

    def league_baselines(self) -> LeagueBaselines:
        key = ("league-baselines", self.season)
        if key in self._cache:
            return self._cache[key]
        values = {"rpg": 4.45, "ops": .710, "era": 4.35, "whip": 1.32}
        hitting = self._get("v1/teams/stats", {"stats": "season", "group": "hitting", "season": self.season, "sportIds": 1})
        pitching = self._get("v1/teams/stats", {"stats": "season", "group": "pitching", "season": self.season, "sportIds": 1})
        hs = (hitting.get("stats") or [{}])[0].get("splits") or []
        ps = (pitching.get("stats") or [{}])[0].get("splits") or []
        if hs:
            values["rpg"] = mean(_num(row.get("stat", {}).get("runsPerGame"), 4.45) for row in hs)
            values["ops"] = mean(_num(row.get("stat", {}).get("ops"), .710) for row in hs)
        if ps:
            values["era"] = mean(_num(row.get("stat", {}).get("era"), 4.35) for row in ps)
            values["whip"] = mean(_num(row.get("stat", {}).get("whip"), 1.32) for row in ps)
        result = LeagueBaselines(**values)
        self._cache[key] = result
        return result

    def lineup(self, game_pk: int | str) -> dict[str, Any]:
        box = self._get(f"v1/game/{game_pk}/boxscore")
        out: dict[str, Any] = {}
        for side in ("home", "away"):
            team = (box.get("teams") or {}).get(side) or {}
            hitters: list[dict[str, Any]] = []
            for player in (team.get("players") or {}).values():
                batting_order = player.get("battingOrder")
                if batting_order is None:
                    continue
                person = player.get("person") or {}
                player_id = person.get("id")
                stats = self.player_stats(player_id, "hitting") if player_id else {}
                ops = _num(stats.get("ops"), 0.0)
                hitters.append({
                    "id": player_id,
                    "name": person.get("fullName"),
                    "batting_order": batting_order,
                    "ops": ops if .3 <= ops <= 1.5 else None,
                })
            hitters.sort(key=lambda row: int(_num(row.get("batting_order"), 999)))
            weighted = [
                (row["ops"], LINEUP_WEIGHTS[min(index, 8)])
                for index, row in enumerate(hitters[:9]) if row.get("ops") is not None
            ]
            weighted_ops = (
                sum(value*weight for value, weight in weighted) / sum(weight for _value, weight in weighted)
                if len(weighted) >= 5 else None
            )
            out[side] = {"count": len(hitters), "players": hitters, "weighted_ops": weighted_ops}
        return out

    def starter(self, game: dict[str, Any], side: str, league: LeagueBaselines) -> tuple[Starter, dict[str, Any]]:
        probable = (((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {})
        player_id = probable.get("id")
        stats = self.player_stats(player_id, "pitching") if player_id else {}
        innings = _num(stats.get("inningsPitched"), 0.0)
        weight = max(0.0, min(1.0, innings/70.0))
        raw_era = _num(stats.get("era"), league.era)
        raw_whip = _num(stats.get("whip"), league.whip)
        starter = Starter(
            era=weight*raw_era + (1-weight)*league.era,
            whip=weight*raw_whip + (1-weight)*league.whip,
            k9=_num(stats.get("strikeoutsPer9Inn"), 0.0) if stats.get("strikeoutsPer9Inn") is not None else None,
            bb9=_num(stats.get("walksPer9Inn"), 0.0) if stats.get("walksPer9Inn") is not None else None,
            hr9=_num(stats.get("homeRunsPer9"), 0.0) if stats.get("homeRunsPer9") is not None else None,
            innings=innings,
            sample_weight=weight,
        )
        return starter, {"id": player_id, "name": probable.get("fullName"), "current": stats}

    def pitcher_prior(self, player_id: int | str | None) -> dict[str, float]:
        if not player_id:
            return {}
        payload = self._get(
            f"v1/people/{player_id}/stats",
            {"stats": "yearByYear", "group": "pitching"},
        )
        splits = (payload.get("stats") or [{}])[0].get("splits") or []
        by = {
            int(_num(row.get("season"), 0)): row.get("stat") or {}
            for row in splits if _num(row.get("season"), 0)
        }
        return historical_pitcher_prior([
            (by.get(self.season-1) or {}, .65),
            (by.get(self.season-2) or {}, .35),
        ])

    def previous_game(self, team_id: int | str) -> dict[str, Any] | None:
        target = date.fromisoformat(self.target_date)
        for back in range(1, 5):
            day = (target - timedelta(days=back)).isoformat()
            finals = []
            for game in self.schedule(day, team_id=team_id, hydrate="linescore"):
                status = game.get("status") or {}
                if str(status.get("abstractGameState") or "").lower() == "final" or str(status.get("codedGameState") or "").upper() == "F":
                    finals.append(game)
            if finals:
                game = finals[-1]
                teams = game.get("teams") or {}
                venue_home_team = ((teams.get("home") or {}).get("team") or {}).get("name")
                innings = int(_num((game.get("linescore") or {}).get("currentInning"), 9))
                return {
                    "game_pk": game.get("gamePk"),
                    "days_back": back,
                    "venue_home_team": venue_home_team,
                    "extra_innings": innings > 9,
                    "doubleheader": str(game.get("doubleHeader") or "N") != "N",
                }
        return None

    def bullpen_usage(self, team_id: int | str, previous: dict[str, Any] | None) -> dict[str, int]:
        if not previous or not previous.get("game_pk"):
            return {"relief_pitches": 0, "heavy_relievers": 0, "relievers_used": 0}
        box = self._get(f"v1/game/{previous['game_pk']}/boxscore")
        team = None
        for side in ("home", "away"):
            candidate = (box.get("teams") or {}).get(side) or {}
            if str((candidate.get("team") or {}).get("id") or "") == str(team_id):
                team = candidate
                break
        if not team:
            return {"relief_pitches": 0, "heavy_relievers": 0, "relievers_used": 0}
        pitcher_ids = list(team.get("pitchers") or [])
        relievers = pitcher_ids[1:] if len(pitcher_ids) > 1 else []
        players = team.get("players") or {}
        counts = []
        for player_id in relievers:
            stats = (((players.get(f"ID{player_id}") or {}).get("stats") or {}).get("pitching") or {})
            counts.append(int(_num(stats.get("pitchesThrown"), 0)))
        return {
            "relief_pitches": sum(counts),
            "heavy_relievers": sum(value >= 20 for value in counts),
            "relievers_used": len(counts),
        }

    def operational(self, game: dict[str, Any], *, home_name: str, home_id: int | str,
                    away_id: int | str) -> dict[str, Any]:
        current_coord = TEAM_COORD.get(home_name)
        out: dict[str, Any] = {"current_doubleheader": str(game.get("doubleHeader") or "N") != "N"}
        for side, team_id in (("home", home_id), ("away", away_id)):
            previous = self.previous_game(team_id)
            previous_coord = TEAM_COORD.get(previous.get("venue_home_team")) if previous else None
            distance = _distance_km(previous_coord, current_coord)
            bullpen = self.bullpen_usage(team_id, previous)
            out[side] = {
                "rest_days": max(0, int(previous.get("days_back", 1))-1) if previous else None,
                "travel_km": round(distance, 1) if distance is not None else None,
                "timezone_shift_hours_approx": round((current_coord[1]-previous_coord[1])/15, 2) if current_coord and previous_coord else None,
                "previous_extra_innings": bool(previous.get("extra_innings")) if previous else None,
                "previous_doubleheader": bool(previous.get("doubleheader")) if previous else None,
                "bullpen_previous_game": bullpen,
            }
        return out

    def structural_inputs(self, game: dict[str, Any]) -> tuple[StructuralInputs, dict[str, Any]]:
        game_time = _dt(game.get("gameDate"))
        if _dt(self.as_of) >= game_time:
            raise ValueError("V14 native data snapshot must be strictly pregame")
        teams = game.get("teams") or {}
        home_team = ((teams.get("home") or {}).get("team") or {})
        away_team = ((teams.get("away") or {}).get("team") or {})
        home_id, away_id = home_team.get("id"), away_team.get("id")
        home_name, away_name = str(home_team.get("name") or ""), str(away_team.get("name") or "")
        if not home_id or not away_id or not home_name or not away_name:
            raise ValueError("incomplete MLB game team identity")

        league = self.league_baselines()
        home_hit, away_hit = self.team_stats(home_id, "hitting"), self.team_stats(away_id, "hitting")
        home_pitch, away_pitch = self.team_stats(home_id, "pitching"), self.team_stats(away_id, "pitching")
        lineups = self.lineup(game.get("gamePk"))
        old_home, home_meta = self.starter(game, "home", league)
        old_away, away_meta = self.starter(game, "away", league)
        home_prior = self.pitcher_prior(home_meta.get("id"))
        away_prior = self.pitcher_prior(away_meta.get("id"))
        enhanced_home = enhance_starter(home_meta.get("current") or {}, home_prior, old_home)
        enhanced_away = enhance_starter(away_meta.get("current") or {}, away_prior, old_away)
        operational = self.operational(game, home_name=home_name, home_id=home_id, away_id=away_id)

        home_ops = _num(home_hit.get("ops"), league.ops)
        away_ops = _num(away_hit.get("ops"), league.ops)
        home_lineup_ops = _num((lineups.get("home") or {}).get("weighted_ops"), home_ops)
        away_lineup_ops = _num((lineups.get("away") or {}).get("weighted_ops"), away_ops)
        inputs = StructuralInputs(
            league=league,
            home=TeamInputs(
                runs_per_game=_num(home_hit.get("runsPerGame"), league.rpg),
                ops=home_ops,
                lineup_ops=home_lineup_ops,
                team_era=_num(home_pitch.get("era"), league.era),
                starter=old_home,
                enhanced_starter=enhanced_home,
                operational=operational.get("home") or {},
            ),
            away=TeamInputs(
                runs_per_game=_num(away_hit.get("runsPerGame"), league.rpg),
                ops=away_ops,
                lineup_ops=away_lineup_ops,
                team_era=_num(away_pitch.get("era"), league.era),
                starter=old_away,
                enhanced_starter=enhanced_away,
                operational=operational.get("away") or {},
            ),
            static_park_factor=float(STATIC_PARK.get(home_name, 1.0)),
            current_doubleheader=bool(operational.get("current_doubleheader")),
        )
        meta = {
            "game_pk": str(game.get("gamePk") or ""),
            "game_date": game.get("gameDate"),
            "home": home_name,
            "away": away_name,
            "venue": ((game.get("venue") or {}).get("name")),
            "home_id": home_id,
            "away_id": away_id,
            "lineups": lineups,
            "home_starter": home_meta,
            "away_starter": away_meta,
            "home_starter_prior": home_prior,
            "away_starter_prior": away_prior,
            "operational": operational,
            "as_of": self.as_of,
            "source_timestamp_attested": self.source_timestamp_attested,
            "source_calls": list(self.calls),
            "market_data_used": False,
        }
        return inputs, meta
