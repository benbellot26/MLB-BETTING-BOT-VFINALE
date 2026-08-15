from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import urllib.request
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

SOURCE_FILE = Path(os.getenv("V124_HIST_SOURCE", "data/mlb_backtest_2026.jsonl"))
OUTPUT_FILE = Path(os.getenv("V124_HIST_ROWS", "data/v124_historical_reconstructed.jsonl"))
MODEL_FILE = Path(os.getenv("V124_HIST_MODEL", "data/v124_historical_warmstart.json"))
SCHEMA = "v12-4-historical-reconstruction-v1"
MODEL_SCHEMA = "v12-4-historical-warmstart-v1"
VERSION = "v12.4-historical-reconstruction-v1"
HIST_MIN_GAMES = int(os.getenv("V124_HIST_MIN_GAMES", "600") or 600)
FROZEN_FRACTION = float(os.getenv("V124_HIST_FROZEN_FRACTION", ".15") or .15)
BOX_WORKERS = int(os.getenv("V124_HIST_BOX_WORKERS", "12") or 12)
MODULES = ("platoon", "statcast", "bullpen_player", "lineup_player", "starter_ip", "weather_park")


def _num(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _ip(value):
    text = str(value or "0")
    if "." not in text:
        return _num(text, 0.0)
    whole, frac = text.split(".", 1)
    outs = int(frac[:1]) if frac[:1].isdigit() else 0
    return max(0.0, _num(whole, 0.0) + min(2, outs) / 3.0)


def _norm(value):
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _load_rows(path=SOURCE_FILE):
    rows = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("game_pk") is None or row.get("game_date") is None:
                continue
            if row.get("home_score") is None or row.get("away_score") is None:
                continue
            if not (row.get("v10") or {}).get("home_struct") or not (row.get("v10") or {}).get("away_struct"):
                continue
            rows.append(row)
    rows.sort(key=lambda r: (str(r.get("game_date")), int(r.get("game_pk") or 0)))
    return rows


def _http_box(game_pk):
    url = f"https://statsapi.mlb.com/api/v1/game/{int(game_pk)}/boxscore"
    req = urllib.request.Request(url, headers={"User-Agent": "MLB-V12.4-historical-reconstruction"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _prefetch_boxes(rows):
    boxes = {}
    failures = {}
    def one(row):
        gid = str(row["game_pk"])
        try:
            return gid, _http_box(gid), None
        except Exception as exc:
            return gid, None, f"{type(exc).__name__}: {exc}"
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, BOX_WORKERS)) as pool:
        futures = [pool.submit(one, row) for row in rows]
        for future in concurrent.futures.as_completed(futures):
            gid, box, error = future.result()
            if box is not None:
                boxes[gid] = box
            else:
                failures[gid] = error
    return boxes, failures


def _bat_counters():
    return {k: 0.0 for k in ("atBats", "hits", "doubles", "triples", "homeRuns", "baseOnBalls", "hitByPitch", "sacFlies")}


def _pitch_counters():
    return {k: 0.0 for k in ("innings", "earnedRuns", "hits", "baseOnBalls", "homeRuns", "strikeOuts", "gamesPitched", "gamesStarted")}


def _add_batting(target, stats):
    for key in target:
        target[key] += max(0.0, _num((stats or {}).get(key), 0.0))


def _add_pitching(target, stats, started=False):
    target["innings"] += _ip((stats or {}).get("inningsPitched"))
    for key in ("earnedRuns", "hits", "baseOnBalls", "homeRuns", "strikeOuts"):
        target[key] += max(0.0, _num((stats or {}).get(key), 0.0))
    target["gamesPitched"] += 1.0
    if started:
        target["gamesStarted"] += 1.0


def _ops(c):
    ab = c.get("atBats", 0.0)
    h = c.get("hits", 0.0)
    bb = c.get("baseOnBalls", 0.0)
    hbp = c.get("hitByPitch", 0.0)
    sf = c.get("sacFlies", 0.0)
    denom = ab + bb + hbp + sf
    obp = (h + bb + hbp) / denom if denom > 0 else None
    tb = h + c.get("doubles", 0.0) + 2*c.get("triples", 0.0) + 3*c.get("homeRuns", 0.0)
    slg = tb / ab if ab > 0 else None
    return (obp + slg) if obp is not None and slg is not None else None


def _bat_stats(c):
    value = _ops(c)
    pa = c.get("atBats", 0.0) + c.get("baseOnBalls", 0.0) + c.get("hitByPitch", 0.0) + c.get("sacFlies", 0.0)
    return {"ops": value, "plateAppearances": pa, **c}


def _pitch_stats(c):
    ip = c.get("innings", 0.0)
    era = 9*c.get("earnedRuns", 0.0)/ip if ip > 0 else None
    whip = (c.get("hits", 0.0)+c.get("baseOnBalls", 0.0))/ip if ip > 0 else None
    return {
        "inningsPitched": ip,
        "gamesPitched": c.get("gamesPitched", 0.0),
        "gamesStarted": c.get("gamesStarted", 0.0),
        "era": era,
        "whip": whip,
        "strikeoutsPer9Inn": 9*c.get("strikeOuts", 0.0)/ip if ip > 0 else None,
        "walksPer9Inn": 9*c.get("baseOnBalls", 0.0)/ip if ip > 0 else None,
        "homeRunsPer9": 9*c.get("homeRuns", 0.0)/ip if ip > 0 else None,
    }


def _team_pitch_stats(c):
    p = _pitch_stats(c)
    return {"era": p.get("era"), "whip": p.get("whip"), "inningsPitched": p.get("inningsPitched")}


def _team_id(box, side):
    return (((box.get("teams") or {}).get(side) or {}).get("team") or {}).get("id")


def _starting_lineup(box, side):
    team = (box.get("teams") or {}).get(side) or {}
    candidates = {}
    for player in (team.get("players") or {}).values():
        raw = player.get("battingOrder")
        try:
            order = int(raw)
        except Exception:
            continue
        slot = order // 100
        if not 1 <= slot <= 9:
            continue
        current = candidates.get(slot)
        if current is None or order < current[0]:
            candidates[slot] = (order, player)
    out = []
    for slot in range(1, 10):
        if slot not in candidates:
            continue
        player = candidates[slot][1]
        person = player.get("person") or {}
        out.append({"id": person.get("id"), "name": person.get("fullName"), "slot": slot})
    return out


def _box_players(box, side):
    return list((((box.get("teams") or {}).get(side) or {}).get("players") or {}).values())


def _starter_id(row, side):
    return ((row.get("starters") or {}).get(f"{side}_id"))


def _starter_hand(row, side):
    value = str((row.get("starters") or {}).get(f"{side}_hand") or "").upper()
    return value if value in {"R", "L"} else None


def _date_key(row):
    return str(row.get("game_date") or "")[:10]


class State:
    def __init__(self):
        self.batting = defaultdict(_bat_counters)
        self.splits = {"vr": defaultdict(_bat_counters), "vl": defaultdict(_bat_counters)}
        self.pitching = defaultdict(_pitch_counters)
        self.team_pitching = defaultdict(_pitch_counters)
        self.team_relievers = defaultdict(set)
        self.recent = defaultdict(list)

    def lineup(self, raw):
        out = []
        for player in raw:
            pid = player.get("id")
            value = _ops(self.batting[pid]) if pid else None
            out.append({"id": pid, "name": player.get("name"), "ops": value})
        return out

    def starter(self, pid, name=None):
        st = _pitch_stats(self.pitching[pid]) if pid else {}
        return {
            "id": pid, "name": name,
            "era": st.get("era"), "whip": st.get("whip"),
            "k9": st.get("strikeoutsPer9Inn"), "bb9": st.get("walksPer9Inn"),
            "hr9": st.get("homeRunsPer9"), "innings": st.get("inningsPitched"),
        }

    def bullpen(self, team_id, starter_id, game_date):
        ids = [pid for pid in self.team_relievers.get(team_id, set()) if pid != starter_id]
        ids.sort(key=lambda pid: (self.recent.get(pid, [])[-1][0] if self.recent.get(pid) else "", self.pitching[pid].get("innings", 0.0)), reverse=True)
        relievers = []
        current = datetime.fromisoformat(game_date.replace("Z", "+00:00")).date()
        for pid in ids[:10]:
            uses = []
            for d, pitches in self.recent.get(pid, []):
                try:
                    dt = datetime.fromisoformat(d.replace("Z", "+00:00")).date()
                except Exception:
                    continue
                if 0 < (current-dt).days <= 3:
                    uses.append((d, pitches))
            relievers.append({
                "id": pid,
                "pitches_3d": sum(x[1] for x in uses),
                "days_used": len({x[0][:10] for x in uses}),
            })
        return {"relievers": relievers, "coverage": min(1.0, len(relievers)/7.0)}

    def update(self, row, box):
        date = str(row.get("game_date") or "")
        for side, opp in (("home", "away"), ("away", "home")):
            starter_id = _starter_id(row, side)
            opp_hand = _starter_hand(row, opp)
            sit = "vr" if opp_hand == "R" else "vl" if opp_hand == "L" else None
            team_id = _team_id(box, side)
            for player in _box_players(box, side):
                person = player.get("person") or {}
                pid = person.get("id")
                stats = player.get("stats") or {}
                bat = stats.get("batting") or {}
                pitch = stats.get("pitching") or {}
                if pid and bat and any(_num(v, 0.0) for v in bat.values() if isinstance(v, (int, float, str))):
                    _add_batting(self.batting[pid], bat)
                    if sit:
                        _add_batting(self.splits[sit][pid], bat)
                if pid and pitch and _ip(pitch.get("inningsPitched")) >= 0:
                    started = str(pid) == str(starter_id)
                    _add_pitching(self.pitching[pid], pitch, started=started)
                    if team_id:
                        _add_pitching(self.team_pitching[team_id], pitch, started=started)
                    if team_id and not started:
                        self.team_relievers[team_id].add(pid)
                        pitches = _num(pitch.get("numberOfPitches"), _num(pitch.get("pitchesThrown"), 0.0))
                        self.recent[pid].append((date, pitches))
            for pid in list(self.recent):
                if len(self.recent[pid]) > 12:
                    self.recent[pid] = self.recent[pid][-12:]


def _variant_options(result, hmu, amu):
    from . import engine_v12 as engine
    home = (result.get("ctx") or {}).get("home")
    out = []
    for opt in result.get("options") or []:
        market = opt.get("market")
        if market == "ML":
            p = engine.prob_home_win(hmu, amu)
        elif market == "RUNLINE":
            side = "home" if _norm(opt.get("name")) == _norm(home) else "away"
            win, push = engine.prob_cover_parts(hmu, amu, side, _num(opt.get("point"), 0.0))
            p = win/max(1e-9, 1-push)
        else:
            continue
        out.append({"market": market, "name": opt.get("name"), "point": opt.get("point"), "p_effective": max(.001, min(.999, p))})
    return out


def _historical_options(row):
    home = row.get("home")
    hs, aws = _num(row.get("home_score")), _num(row.get("away_score"))
    out = [{"market": "ML", "name": home, "point": None, "result": "WIN" if hs > aws else "LOSS"}]
    proxy = row.get("rl_proxy") or {}
    if proxy.get("name") and proxy.get("point") is not None and proxy.get("result") in {"W", "L"}:
        out.append({"market": "RUNLINE", "name": proxy.get("name"), "point": _num(proxy.get("point")), "result": "WIN" if proxy.get("result") == "W" else "LOSS"})
    return out


def _build_result(row, box, state):
    home_id, away_id = _team_id(box, "home"), _team_id(box, "away")
    home_line = state.lineup(_starting_lineup(box, "home"))
    away_line = state.lineup(_starting_lineup(box, "away"))
    hp, ap = _starter_id(row, "home"), _starter_id(row, "away")
    home_name = next((p.get("name") for p in _starting_lineup(box, "home") if p.get("id") == hp), None)
    away_name = next((p.get("name") for p in _starting_lineup(box, "away") if p.get("id") == ap), None)
    return {
        "game": {"gameDate": row.get("game_date")},
        "game_pk": row.get("game_pk"),
        "phase": "FINAL_RECONSTRUCTED",
        "ctx": {
            "home": row.get("home"), "away": row.get("away"),
            "home_id": home_id, "away_id": away_id,
            "home_lineup": {"players": home_line}, "away_lineup": {"players": away_line},
            "home_starter": state.starter(hp, home_name), "away_starter": state.starter(ap, away_name),
        },
        "features": {
            "bullpen": {
                "home": state.bullpen(home_id, hp, str(row.get("game_date"))),
                "away": state.bullpen(away_id, ap, str(row.get("game_date"))),
            },
            "weather": {"available": False, "reason": "no archived pregame forecast"},
            "park_factor": 1.0,
            "run_dispersion": 7.5,
            "run_environment_sigma": .08,
        },
        "options": _historical_options(row),
    }


def _modules(result, row, state, use_statcast=True):
    from . import core, predictive_v124 as v124
    originals = {
        "league": core.league_baselines,
        "player": core.player_stats,
        "season": core.season_stats,
        "split": v124._split_stats,
        "person": v124._person,
    }
    league = row.get("league") or {}
    team_by_id = {}
    for side in ("home", "away"):
        tid = (result.get("ctx") or {}).get(f"{side}_id")
        if tid:
            team_by_id[str(tid)] = _team_pitch_stats(state.team_pitching[tid])
    person = {}
    for side in ("home", "away"):
        pid = _starter_id(row, side)
        if pid:
            person[str(pid)] = {"id": pid, "pitch_hand": _starter_hand(row, side)}
    try:
        core.league_baselines = lambda: {"ops": _num(league.get("ops"), .710), "era": _num(league.get("era"), 4.35), "whip": 1.32}
        core.player_stats = lambda pid, group: _pitch_stats(state.pitching[pid]) if pid and group == "pitching" else {}
        core.season_stats = lambda team_id, group: team_by_id.get(str(team_id), {}) if group == "pitching" else {}
        v124._split_stats = lambda pid, group, sit: _bat_stats(state.splits.get(sit, {}).get(pid, _bat_counters())) if pid and group == "hitting" and sit in {"vr", "vl"} else {}
        v124._person = lambda pid: person.get(str(pid), {"id": pid, "pitch_hand": None})
        modules = {
            "platoon": v124.platoon_module(result, True),
            "lineup_player": v124.lineup_player_module(result, True),
            "starter_ip": v124.starter_ip_module(result, True),
            "bullpen_player": v124.bullpen_player_module(result, True),
            "statcast": v124.statcast_module(result, bool(use_statcast)),
            "weather_park": {"name": "weather_park", "enabled": True, "status": "UNAVAILABLE", "coverage": 0.0, "home_factor": 1.0, "away_factor": 1.0, "details": {"reason": "no archived pregame forecast"}},
        }
        # The historical platoon reconstruction buckets a full game's batting line by
        # opposing starter hand. It is point-in-time but only a proxy for exact PA splits,
        # so down-weight its coverage instead of pretending it is native quality.
        modules["platoon"]["coverage"] = .65 * _num(modules["platoon"].get("coverage"), 0.0)
        modules["platoon"].setdefault("details", {})["historical_split_proxy"] = "game batting line bucketed by opposing starter hand"
        return modules
    finally:
        core.league_baselines = originals["league"]
        core.player_stats = originals["player"]
        core.season_stats = originals["season"]
        v124._split_stats = originals["split"]
        v124._person = originals["person"]


def reconstruct(source_rows, boxes, use_statcast=True):
    from . import core
    from .v124_statcast_provider import install as install_statcast
    install_statcast()
    core.SEASON = 2026
    state = State()
    reconstructed = []
    failures = []
    for idx, row in enumerate(source_rows):
        gid = str(row.get("game_pk"))
        box = boxes.get(gid)
        if not box:
            failures.append({"game_pk": row.get("game_pk"), "reason": "missing_boxscore"})
            continue
        try:
            result = _build_result(row, box, state)
            base_h = max(1.6, min(8.0, _num((row.get("v10") or {}).get("home_struct"), 4.4)))
            base_a = max(1.6, min(8.0, _num((row.get("v10") or {}).get("away_struct"), 4.2)))
            modules = _modules(result, row, state, use_statcast=use_statcast)
            variants = {
                "baseline_historical_proxy": {"home_mu": base_h, "away_mu": base_a, "options": _variant_options(result, base_h, base_a)},
            }
            for name in MODULES:
                mod = modules.get(name) or {}
                hf = max(.80, min(1.20, _num(mod.get("home_factor"), 1.0)))
                af = max(.80, min(1.20, _num(mod.get("away_factor"), 1.0)))
                h, a = base_h*hf, base_a*af
                variants[f"only_{name}"] = {"home_mu": h, "away_mu": a, "home_factor": hf, "away_factor": af, "options": _variant_options(result, h, a)}
            reconstructed.append({
                "schema": SCHEMA, "version": VERSION,
                "game_pk": row.get("game_pk"), "game_date": row.get("game_date"),
                "home": row.get("home"), "away": row.get("away"),
                "home_score": row.get("home_score"), "away_score": row.get("away_score"),
                "options": result.get("options") or [],
                "shadow_v124": {
                    "enabled": True, "status": "HISTORICAL_RECONSTRUCTED", "research_only": True,
                    "affects_v12_selection": False, "base_home_mu": base_h, "base_away_mu": base_a,
                    "modules": modules, "variants": variants,
                },
                "historical_reconstruction": {
                    "source_index": idx,
                    "baseline_source": "legacy V10 structural means used only as warm-start proxy",
                    "market_scope": ["ML", "RUNLINE"],
                    "historical_odds_used": False, "roi_trainable": False,
                    "lineup_identity": "posthoc starting-lineup identity for FINAL-phase counterfactual",
                    "player_stats": "chronological state updated only after each game",
                    "weather": "excluded: no archived pregame forecast",
                    "statcast": "Baseball Savant point-in-time cutoff" if use_statcast else "disabled",
                    "native_v124_evidence": False,
                },
            })
        except Exception as exc:
            failures.append({"game_pk": row.get("game_pk"), "reason": f"{type(exc).__name__}: {exc}"})
        finally:
            state.update(row, box)
    return reconstructed, failures


def build_warmstart(rows):
    from . import v124_weight_optimizer as opt
    # Historical rows use an explicitly named proxy baseline; temporarily adapt
    # only the historical copies to the native optimizer schema.
    adapted = []
    for row in rows:
        clone = deepcopy(row)
        variants = ((clone.get("shadow_v124") or {}).get("variants") or {})
        if "baseline_v1232" not in variants and "baseline_historical_proxy" in variants:
            variants["baseline_v1232"] = variants["baseline_historical_proxy"]
        adapted.append(clone)
    exs = opt.examples(adapted)
    n = len(exs)
    frozen_n = max(100, int(round(n*FROZEN_FRACTION))) if n >= 200 else max(1, n//5)
    train = exs[:-frozen_n] if n > frozen_n else []
    frozen = exs[-frozen_n:] if n > frozen_n else []
    weights = opt.fit_weights(train) if len(train) >= opt.MIN_GAMES else {name: 0.0 for name in opt.MODULES}
    zero = {name: 0.0 for name in opt.MODULES}
    base = opt.evaluate(frozen, zero)
    candidate = opt.evaluate(frozen, weights)
    wf = opt.walk_forward(train)
    b_gain = (_num(base.get("brier"), 999)-_num(candidate.get("brier"), 999)) if frozen else None
    ll_gain = (_num(base.get("logloss"), 999)-_num(candidate.get("logloss"), 999)) if frozen else None
    run_gain = (_num(base.get("team_run_mae"), 999)-_num(candidate.get("team_run_mae"), 999)) if frozen else None
    coverage = {}
    for name in opt.MODULES:
        vals = [_num((ex.get("effects") or {}).get(name, {}).get("coverage"), 0.0) for ex in train]
        coverage[name] = sum(vals)/len(vals) if vals else 0.0
    eligible = bool(
        n >= HIST_MIN_GAMES
        and len(train) >= opt.MIN_GAMES
        and wf.get("status") == "ACTIVE"
        and b_gain is not None and b_gain >= 0
        and ll_gain is not None and ll_gain >= 0
        and run_gain is not None and run_gain >= -.02
    )
    return {
        "schema": MODEL_SCHEMA, "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "historical_reconstructed_games": n, "minimum_games": HIST_MIN_GAMES,
        "train_games": len(train), "frozen_test_games": len(frozen),
        "eligible_for_warm_start": eligible,
        "weights": weights,
        "coverage": coverage,
        "walk_forward": wf,
        "frozen_test": {
            "baseline": base, "optimized": candidate,
            "brier_improvement": b_gain, "logloss_improvement": ll_gain,
            "team_run_mae_improvement": run_gain,
            "used_for_weight_fitting": False,
        },
        "modules": opt.module_diagnostics(train, weights) if train else {},
        "guardrails": {
            "research_only": True, "affects_v12_selection": False,
            "historical_odds_used": False, "roi_used_for_training": False,
            "weather_weight_forced_by_coverage": coverage.get("weather_park", 0.0),
            "native_75_game_gate_unchanged": True,
            "automatic_promotion": False,
        },
        "evidence_boundary": "Reconstructed V10-baseline counterfactual used only to warm-start V12.4 shadow module weights. It is not V12.3.2-native evidence and not profitability evidence.",
    }


def write_outputs(rows, model, rows_path=OUTPUT_FILE, model_path=MODEL_FILE):
    rows_path, model_path = Path(rows_path), Path(model_path)
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    rows_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"))+"\n" for row in rows), encoding="utf-8")
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE_FILE))
    parser.add_argument("--rows-out", default=str(OUTPUT_FILE))
    parser.add_argument("--model-out", default=str(MODEL_FILE))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-statcast", action="store_true")
    parser.add_argument("--offline-dry-run", action="store_true")
    args = parser.parse_args(argv)
    source = _load_rows(args.source)
    if args.limit > 0:
        source = source[:args.limit]
    if args.offline_dry_run:
        print(json.dumps({"schema": SCHEMA, "source_games": len(source), "first": source[0].get("game_pk") if source else None, "last": source[-1].get("game_pk") if source else None}, sort_keys=True))
        return 0
    boxes, box_failures = _prefetch_boxes(source)
    rows, failures = reconstruct(source, boxes, use_statcast=not args.no_statcast)
    model = build_warmstart(rows)
    model["source_games"] = len(source)
    model["boxscores_loaded"] = len(boxes)
    model["failures"] = (list(box_failures.items())[:20] + failures[:20])
    write_outputs(rows, model, args.rows_out, args.model_out)
    print(json.dumps({
        "source_games": len(source), "reconstructed_games": len(rows),
        "eligible_for_warm_start": model.get("eligible_for_warm_start"),
        "weights": model.get("weights"), "frozen_test": model.get("frozen_test"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
