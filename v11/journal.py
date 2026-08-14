from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from . import config, core, pro_model


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def load_rows(path=config.LIVE_FILE):
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
            core.logging.warning("Journal V12: ligne JSON invalide ignorée")
    return out


def write_rows(rows, path=config.LIVE_FILE):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in rows)+("\n" if rows else ""), encoding="utf-8")


def _is_final(g):
    s = g.get("status") or {}
    return (
        str(s.get("abstractGameState") or "").lower() == "final"
        or str(s.get("codedGameState") or "").upper() == "F"
        or str(s.get("detailedState") or "").lower() in {"final", "game over", "completed early"}
    )


def settle_option(opt, row):
    if opt.get("result") in {"WIN", "LOSS", "PUSH"}:
        return
    hs, aps = _num(row.get("home_score")), _num(row.get("away_score"))
    home, away = str(row.get("home")), str(row.get("away"))
    m, name, point = opt.get("market"), str(opt.get("name") or ""), _num(opt.get("point"))
    if m == "ML":
        winner = home if hs > aps else away if aps > hs else None
        res = "WIN" if winner and _norm(name) == _norm(winner) else "LOSS" if winner else "PUSH"
    elif m == "RUNLINE":
        margin = hs-aps+point if _norm(name) == _norm(home) else aps-hs+point if _norm(name) == _norm(away) else None
        if margin is None:
            return
        res = "WIN" if margin > 1e-9 else "LOSS" if margin < -1e-9 else "PUSH"
    elif m == "TOTAL":
        d = hs+aps-point
        if abs(d) <= 1e-9:
            res = "PUSH"
        elif name.lower() == "over":
            res = "WIN" if d > 0 else "LOSS"
        elif name.lower() == "under":
            res = "WIN" if d < 0 else "LOSS"
        else:
            return
    else:
        return
    opt["result"] = res
    if res != "PUSH":
        y = 1 if res == "WIN" else 0
        p = max(.001, min(.999, _num(opt.get("p_effective"), .5)))
        opt["brier"] = round((p-y)**2, 8)
        opt["logloss"] = round(-(y*math.log(p)+(1-y)*math.log(1-p)), 8)
        sp = opt.get("p_market")
        if sp is not None:
            sp = max(.001, min(.999, _num(sp, .5)))
            opt["sharp_brier"] = round((sp-y)**2, 8)
            opt["sharp_logloss"] = round(-(y*math.log(sp)+(1-y)*math.log(1-sp)), 8)


def settle_bet(b, row):
    if b.get("status") in {"WIN", "LOSS", "PUSH"}:
        return False
    fake = {"market": b.get("market"), "name": b.get("pick"), "point": b.get("point"), "p_effective": b.get("p_effective")}
    settle_option(fake, row)
    res = fake.get("result")
    if not res:
        return False
    u, price = max(0, _num(b.get("units"))), _num(b.get("winamax_price"))
    pnl = u*(price-1) if res == "WIN" and price > 1 else -u if res == "LOSS" else 0.0
    b.update({"status": res, "profit_units": round(pnl, 4), "settled_at": datetime.now(timezone.utc).isoformat()})
    return True


def settle_rows(rows):
    dates = sorted({str(r.get("target_date")) for r in rows if r.get("result_status") != "FINAL" and r.get("target_date")})
    games = {}
    for day in dates:
        try:
            for g in core.mlb_schedule(day):
                games[str(g.get("gamePk"))] = g
        except Exception:
            core.logging.exception("Settlement V12 impossible %s", day)
    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        if r.get("result_status") == "FINAL" or not r.get("game_pk"):
            continue
        g = games.get(str(r.get("game_pk")))
        if not g or not _is_final(g):
            continue
        teams = g.get("teams") or {}
        hs = int(_num((teams.get("home") or {}).get("score")))
        aps = int(_num((teams.get("away") or {}).get("score")))
        if hs == aps:
            continue
        r.update({
            "result_status": "FINAL", "home_score": hs, "away_score": aps,
            "winner": r.get("home") if hs > aps else r.get("away"), "settled_at": now,
        })
        for o in r.get("options") or []:
            settle_option(o, r)
        for b in r.get("official_bets") or []:
            settle_bet(b, r)
        changed += 1

    finals = {}
    for r in rows:
        if r.get("result_status") == "FINAL" and r.get("game_pk"):
            gid, rank = str(r.get("game_pk")), str(r.get("analyzed_at") or "")
            if gid not in finals or rank > finals[gid][0]:
                finals[gid] = (rank, r)
    finals = {k: v[1] for k, v in finals.items()}
    for r in rows:
        if r.get("bet_type") != "COMBO" or r.get("result_status") == "FINAL":
            continue
        graded, ready = [], True
        for leg in r.get("combo_legs") or []:
            fr = finals.get(str(leg.get("game_pk")))
            if not fr:
                ready = False
                break
            b = {
                "market": leg.get("market"), "pick": leg.get("pick"), "point": leg.get("point"),
                "p_effective": leg.get("p_effective"), "status": "PENDING", "units": 1,
                "winamax_price": leg.get("winamax_price"),
            }
            settle_bet(b, fr)
            if b.get("status") not in {"WIN", "LOSS", "PUSH"}:
                ready = False
                break
            graded.append(b)
        if not ready:
            continue
        if any(x["status"] == "LOSS" for x in graded):
            status, settled_price = "LOSS", None
        else:
            winning_prices = [_num(x.get("winamax_price"), 0) for x in graded if x["status"] == "WIN"]
            if not winning_prices:
                status, settled_price = "PUSH", 1.0
            elif all(p > 1 for p in winning_prices):
                status, settled_price = "WIN", math.prod(winning_prices)
            else:
                status, settled_price = "WIN", None
        u = _num(r.get("units"))
        pnl = u*(settled_price-1) if status == "WIN" and settled_price is not None else -u if status == "LOSS" else 0.0
        r.update({
            "result_status": "FINAL", "result": status,
            "settled_price": round(settled_price, 4) if settled_price is not None else None,
            "profit_units": round(pnl, 4), "settled_at": now,
            "leg_results": [x["status"] for x in graded],
        })
        changed += 1
    return changed


def capture_bets(result):
    out = []
    for rec in result.get("options") or []:
        e = rec.get("winamax_eval") or {}
        if not e.get("official_selected"):
            continue
        out.append({
            "market": rec.get("market"), "pick": rec.get("name"), "point": rec.get("point"),
            "units": _num(e.get("official_units")), "winamax_price": e.get("price"),
            "p_effective": rec.get("p_effective"), "status": "PENDING", "profit_units": None,
            "price_gate": e.get("v11_price_gate"),
        })
    return out


def combo_row(combo, run_id, analyzed_at, target_date):
    if not combo or not combo.get("official"):
        return None
    legs = []
    for c in combo.get("legs") or []:
        r, rec = c["result"], c["rec"]
        e = rec.get("winamax_eval") or {}
        legs.append({
            "game_pk": r.get("game_pk"), "home": r["ctx"]["home"], "away": r["ctx"]["away"],
            "market": rec.get("market"), "pick": rec.get("name"), "point": rec.get("point"),
            "p_effective": rec.get("p_effective"), "winamax_price": e.get("price"),
        })
    return {
        "schema": config.SCHEMA_VERSION, "bet_type": "COMBO", "run_id": run_id,
        "analyzed_at": analyzed_at, "target_date": target_date, "game_pk": None,
        "combo_legs": legs, "units": combo.get("units"), "winamax_price": combo.get("winamax_price"),
        "probability": combo.get("probability"), "ev": combo.get("ev"),
        "result_status": "PENDING", "profit_units": None,
    }


def _canonical_games(rows):
    best = {}
    for r in rows:
        if r.get("bet_type") == "COMBO" or r.get("result_status") != "FINAL" or not r.get("game_pk") or not r.get("options"):
            continue
        gid, rank = str(r["game_pk"]), str(r.get("analyzed_at") or "")
        if gid not in best or rank > best[gid][0]:
            best[gid] = (rank, r)
    return [x[1] for x in best.values()]


def metrics(rows):
    games = _canonical_games(rows)
    markets = {}
    for m in ("ML", "RUNLINE", "TOTAL"):
        xs = []
        for r in games:
            o = pro_model.canonical_market_option(r, m)
            if o and o.get("result") in {"WIN", "LOSS"}:
                xs.append(o)
        if xs:
            wins = sum(o.get("result") == "WIN" for o in xs)
            br = sum(_num(o.get("brier")) for o in xs)/len(xs)
            ll = sum(_num(o.get("logloss")) for o in xs)/len(xs)
            sb = [o for o in xs if o.get("sharp_brier") is not None]
            markets[m] = {
                "n": len(xs), "wins": wins, "accuracy": wins/len(xs),
                "brier": br, "logloss": ll,
                "sharp_brier": sum(_num(o.get("sharp_brier")) for o in sb)/len(sb) if sb else None,
                "sharp_logloss": sum(_num(o.get("sharp_logloss")) for o in sb)/len(sb) if sb else None,
                "selection": "canonical main line",
            }
    return {"settled_games": len(games), "by_market": markets}


def finance_summary(rows):
    """Legacy journal finance view; the event ledger is the production source of truth."""
    bets, combos = [], []
    for r in rows:
        if r.get("result_status") != "FINAL":
            continue
        if r.get("bet_type") == "COMBO":
            combos.append(r)
        else:
            bets.extend([b for b in r.get("official_bets") or [] if b.get("status") in {"WIN", "LOSS", "PUSH"}])
    events = []
    for b in bets:
        if b.get("profit_units") is not None:
            events.append((str(b.get("settled_at") or ""), _num(b.get("profit_units"))))
    for c in combos:
        if c.get("profit_units") is not None:
            events.append((str(c.get("settled_at") or ""), _num(c.get("profit_units"))))
    events.sort(key=lambda x: x[0])
    eq = peak = dd = 0.0
    losing = cur = 0
    for _, x in events:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak-eq)
        if x < 0:
            cur += 1
            losing = max(losing, cur)
        elif x > 0:
            cur = 0
    stake = sum(_num(b.get("units")) for b in bets if b.get("status") != "PUSH")+sum(_num(c.get("units")) for c in combos if c.get("result") != "PUSH")
    pnl = sum(_num(b.get("profit_units")) for b in bets)+sum(_num(c.get("profit_units")) for c in combos)
    return {
        "settled_singles": len(bets), "settled_combos": len(combos),
        "wins": sum(b.get("status") == "WIN" for b in bets)+sum(c.get("result") == "WIN" for c in combos),
        "losses": sum(b.get("status") == "LOSS" for b in bets)+sum(c.get("result") == "LOSS" for c in combos),
        "pushes": sum(b.get("status") == "PUSH" for b in bets)+sum(c.get("result") == "PUSH" for c in combos),
        "staked_units": round(stake, 4), "profit_units": round(pnl, 4),
        "roi": pnl/stake if stake else None, "max_drawdown_units": round(dd, 4),
        "longest_losing_streak": losing,
    }


def write_report(rep, path=config.REPORT_FILE):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
