from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from . import config, core

RUNTIME_DIR = Path(os.getenv("V11_RUNTIME_DIR", "runtime/v11"))
SNAPSHOT_DIR = RUNTIME_DIR / "snapshots"
MARKET_SNAPSHOT_FILE = Path(os.getenv("V11_MARKET_SNAPSHOT_FILE", "data/v11_market_snapshots.jsonl"))
BET_LEDGER_FILE = Path(os.getenv("V11_BET_LEDGER_FILE", "data/v11_bet_ledger.jsonl"))


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _append_jsonl(path, rows):
    rows = list(rows)
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            core.logging.warning("JSONL invalide ignoré: %s", p)
    return out


def snapshot_run(games, events, run_id, analyzed_at, target_date):
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{target_date}_{run_id}.json"
    payload = {"schema": "v11-raw-snapshot-v1", "run_id": run_id, "analyzed_at": analyzed_at,
               "target_date": target_date, "games": games, "odds_events": events}
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def capture_market_snapshot(events, run_id, analyzed_at, target_date):
    rows = []
    for event in events or []:
        event_id = event.get("id")
        for book in event.get("bookmakers") or []:
            for market in book.get("markets") or []:
                rows.append({"schema": "v11-market-snapshot-v1", "run_id": run_id, "analyzed_at": analyzed_at,
                             "target_date": target_date, "event_id": event_id, "home_team": event.get("home_team"),
                             "away_team": event.get("away_team"), "commence_time": event.get("commence_time"),
                             "book": book.get("key"), "book_last_update": book.get("last_update") or book.get("lastUpdate"),
                             "market": market.get("key"), "market_last_update": market.get("last_update") or market.get("lastUpdate"),
                             "outcomes": market.get("outcomes") or []})
    _append_jsonl(MARKET_SNAPSHOT_FILE, rows)
    return len(rows)


def bet_key(game_pk, market, pick, point):
    point_key = "" if point is None else f"{_num(point):+.3f}"
    return f"{game_pk}|{str(market).upper()}|{core.norm_name(pick)}|{point_key}"


def load_ledger_events(path=None):
    return _read_jsonl(BET_LEDGER_FILE if path is None else path)


def fold_ledger(events=None):
    events = load_ledger_events() if events is None else events
    state = {}
    for e in events:
        key = e.get("bet_key")
        if not key:
            continue
        current = state.setdefault(key, {})
        current.update(e)
    return state


def open_exposure():
    return {k: v for k, v in fold_ledger().items() if v.get("status") in {"PLACED", "PENDING"}}


def record_selected_bets(chosen, combo, run_id, analyzed_at, target_date):
    existing = fold_ledger(); rows = []
    for c in chosen:
        r, rec = c["result"], c["rec"]; e = rec.get("winamax_eval") or {}
        key = bet_key(r.get("game_pk"), rec.get("market"), rec.get("name"), rec.get("point"))
        if existing.get(key, {}).get("status") in {"PLACED", "PENDING", "WIN", "LOSS", "PUSH"}:
            continue
        rows.append({"schema": "v11-bet-ledger-v1", "event_type": "PLACED", "bet_key": key, "status": "PLACED",
                     "run_id": run_id, "analyzed_at": analyzed_at, "target_date": target_date,
                     "game_pk": r.get("game_pk"), "home": r.get("ctx", {}).get("home"), "away": r.get("ctx", {}).get("away"),
                     "market": rec.get("market"), "pick": rec.get("name"), "point": rec.get("point"),
                     "units": e.get("official_units"), "stake_eur": e.get("stake_eur"), "bet_price": e.get("price"),
                     "p_effective": rec.get("p_effective"), "p_win": rec.get("p_win"), "p_push": rec.get("p_push"),
                     "data_quality": rec.get("data_quality"), "model_uncertainty": rec.get("model_uncertainty")})
    if combo and combo.get("official"):
        sig = "||".join(sorted(bet_key(c["result"].get("game_pk"), c["rec"].get("market"), c["rec"].get("name"), c["rec"].get("point")) for c in combo.get("legs") or []))
        key = "COMBO|" + sig
        if key not in existing:
            rows.append({"schema": "v11-bet-ledger-v1", "event_type": "PLACED", "bet_key": key, "status": "PLACED",
                         "run_id": run_id, "analyzed_at": analyzed_at, "target_date": target_date, "bet_type": "COMBO",
                         "units": combo.get("units"), "bet_price": combo.get("winamax_price"),
                         "combo_legs": [{"game_pk": c["result"].get("game_pk"), "market": c["rec"].get("market"),
                                         "pick": c["rec"].get("name"), "point": c["rec"].get("point"),
                                         "price": (c["rec"].get("winamax_eval") or {}).get("price")}
                                        for c in combo.get("legs") or []]})
    _append_jsonl(BET_LEDGER_FILE, rows)
    return len(rows)


def update_clv(results, analyzed_at=None):
    analyzed_at = analyzed_at or datetime.now(timezone.utc).isoformat()
    open_bets = open_exposure(); rows = []; by_game = {str(r.get("game_pk")): r for r in results}
    for key, bet in open_bets.items():
        if bet.get("bet_type") == "COMBO":
            continue
        r = by_game.get(str(bet.get("game_pk")))
        if not r:
            continue
        rec = next((o for o in r.get("options") or [] if bet_key(r.get("game_pk"), o.get("market"), o.get("name"), o.get("point")) == key), None)
        if not rec:
            continue
        price = _num((rec.get("winamax_eval") or {}).get("price"), 0)
        if price <= 1:
            continue
        placed = _num(bet.get("bet_price"), 0)
        row = {"schema": "v11-bet-ledger-v1", "event_type": "PRICE_OBSERVATION", "bet_key": key,
               "status": bet.get("status", "PLACED"), "observed_at": analyzed_at, "latest_price": price,
               "latest_clv_pct": round(placed/price-1, 6) if placed > 1 else None}
        if str(r.get("phase") or "").upper() == "FINAL":
            row["closing_price"] = price; row["clv_pct"] = round(placed/price-1, 6) if placed > 1 else None
        rows.append(row)
    _append_jsonl(BET_LEDGER_FILE, rows)
    return len(rows)


def settle_from_journal(rows, settled_at=None):
    settled_at = settled_at or datetime.now(timezone.utc).isoformat(); state = fold_ledger(); finals = {}
    for r in rows:
        if r.get("result_status") == "FINAL" and r.get("game_pk"):
            rank = str(r.get("analyzed_at") or ""); gid = str(r.get("game_pk"))
            if gid not in finals or rank > finals[gid][0]:
                finals[gid] = (rank, r)
    out = []; from . import journal
    for key, bet in state.items():
        if bet.get("status") not in {"PLACED", "PENDING"}:
            continue
        if bet.get("bet_type") == "COMBO":
            leg_status = []; win_prices = []; ready = True
            for leg in bet.get("combo_legs") or []:
                r = (finals.get(str(leg.get("game_pk"))) or (None, None))[1]
                if not r:
                    ready = False; break
                opt = {"market": leg.get("market"), "name": leg.get("pick"), "point": leg.get("point"), "p_effective": .5}
                journal.settle_option(opt, r); st = opt.get("result")
                if st not in {"WIN", "LOSS", "PUSH"}:
                    ready = False; break
                leg_status.append(st)
                if st == "WIN":
                    win_prices.append(_num(leg.get("price"), 0))
            if not ready:
                continue
            if "LOSS" in leg_status:
                status, settled_price = "LOSS", None
            elif not win_prices:
                status, settled_price = "PUSH", 1.0
            elif all(x > 1 for x in win_prices):
                import math
                status, settled_price = "WIN", math.prod(win_prices)
            else:
                status, settled_price = "WIN", None
            units = _num(bet.get("units")); pnl = units*(settled_price-1) if status == "WIN" and settled_price is not None else -units if status == "LOSS" else 0.0
            out.append({"schema": "v11-bet-ledger-v1", "event_type": "SETTLED", "bet_key": key, "status": status,
                        "settled_at": settled_at, "profit_units": round(pnl, 4), "settled_price": settled_price, "leg_results": leg_status})
            continue
        r = (finals.get(str(bet.get("game_pk"))) or (None, None))[1]
        if not r:
            continue
        opt = {"market": bet.get("market"), "name": bet.get("pick"), "point": bet.get("point"), "p_effective": bet.get("p_effective")}
        journal.settle_option(opt, r); status = opt.get("result")
        if status not in {"WIN", "LOSS", "PUSH"}:
            continue
        units = _num(bet.get("units")); price = _num(bet.get("bet_price"))
        pnl = units*(price-1) if status == "WIN" and price > 1 else -units if status == "LOSS" else 0.0
        out.append({"schema": "v11-bet-ledger-v1", "event_type": "SETTLED", "bet_key": key, "status": status,
                    "settled_at": settled_at, "profit_units": round(pnl, 4)})
    _append_jsonl(BET_LEDGER_FILE, out)
    return len(out)


def ledger_summary(events=None):
    state = fold_ledger(events); settled = [v for v in state.values() if v.get("status") in {"WIN", "LOSS", "PUSH"}]
    stake = sum(_num(x.get("units")) for x in settled if x.get("status") != "PUSH"); pnl = sum(_num(x.get("profit_units")) for x in settled)
    clv = [x.get("clv_pct") for x in state.values() if x.get("clv_pct") is not None and x.get("bet_type") != "COMBO"]
    ordered = sorted([x for x in settled if x.get("profit_units") is not None], key=lambda x: str(x.get("settled_at") or ""))
    eq = peak = max_dd = 0.0; losing = cur = 0
    for x in ordered:
        v = _num(x.get("profit_units")); eq += v; peak = max(peak, eq); max_dd = max(max_dd, peak-eq)
        if v < 0:
            cur += 1; losing = max(losing, cur)
        elif v > 0:
            cur = 0
    by_market = {}
    for market in ("ML", "RUNLINE", "TOTAL"):
        xs = [x for x in settled if x.get("bet_type") != "COMBO" and x.get("market") == market]
        st = sum(_num(x.get("units")) for x in xs if x.get("status") != "PUSH"); pu = sum(_num(x.get("profit_units")) for x in xs)
        if xs:
            by_market[market] = {"n": len(xs), "wins": sum(x.get("status") == "WIN" for x in xs),
                                 "losses": sum(x.get("status") == "LOSS" for x in xs), "pushes": sum(x.get("status") == "PUSH" for x in xs),
                                 "profit_units": round(pu, 4), "roi": pu/st if st else None}
    return {"settled_singles": sum(x.get("bet_type") != "COMBO" for x in settled),
            "settled_combos": sum(x.get("bet_type") == "COMBO" for x in settled),
            "wins": sum(x.get("status") == "WIN" for x in settled), "losses": sum(x.get("status") == "LOSS" for x in settled),
            "pushes": sum(x.get("status") == "PUSH" for x in settled), "staked_units": round(stake, 4),
            "profit_units": round(pnl, 4), "roi": pnl/stake if stake else None, "by_market": by_market,
            "max_drawdown_units": round(max_dd, 4), "longest_losing_streak": losing,
            "mean_clv_pct": sum(clv)/len(clv) if clv else None,
            "positive_clv_rate": sum(x > 0 for x in clv)/len(clv) if clv else None,
            "clv_n": len(clv), "open_bets": sum(v.get("status") in {"PLACED", "PENDING"} for v in state.values())}
