"""Runtime observability hook for the V11.3 live runner only.

Active only for a real ``python v11_3_live.py`` execution.

Responsibilities:
- capture every official V10-selector bet after V11.3 has patched Moneyline;
- persist those selections inside data/v11_3_live.jsonl;
- settle ML / Run Line / Total from official MLB final scores already stored there;
- compute simulated units / P&L / ROI using the recorded Winamax price;
- collect V11.4 shadow-only features (no effect on production predictions);
- enrich data/v11_3_live_report.json and send one compact Discord recap.
"""
from __future__ import annotations

import atexit
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_START_NS = time.time_ns()
_CAPTURED = {}
_CORE = None


def _is_live_v113_run() -> bool:
    try:
        return Path(sys.argv[0]).name == "v11_3_live.py" and "--self-test" not in sys.argv
    except Exception:
        return False


def _f(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _pct(value):
    if value is None:
        return "—"
    try:
        return f"{100*float(value):.1f}%"
    except Exception:
        return "—"


def _num(value, digits=4):
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "—"


def _read_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _official_bets_from_results(results):
    out = {}
    core = _CORE
    if core is None:
        return out
    for result in results or []:
        gid = str(result.get("game_pk") or "")
        if not gid:
            continue
        bets = []
        try:
            options = core.v1011_iter_options(result)
        except Exception:
            options = []
        for rec in options:
            e = rec.get("winamax_eval") or {}
            if not e.get("official_selected"):
                continue
            market = str(rec.get("market") or "").upper()
            if market not in {"ML", "RUNLINE", "TOTAL"}:
                continue
            units = max(0.0, _f(e.get("official_units", e.get("units", 0))))
            price = _f(e.get("price"), 0)
            bets.append({
                "market": market,
                "pick": rec.get("name"),
                "point": rec.get("point"),
                "units": round(units, 4),
                "stake_eur": round(units * _f(getattr(core, "UNIT", 0.5), 0.5), 2),
                "winamax_price": round(price, 4) if price > 1 else None,
                "p_effective": round(_f(rec.get("p_effective", rec.get("p_model")), .5), 6),
                "confidence": round(_f(rec.get("confidence")), 4),
                "official_score": (
                    round(_f(rec.get("selection_official_score")), 4)
                    if rec.get("selection_official_score") is not None else None
                ),
                "status": "PENDING",
                "profit_units": None,
                "profit_eur": None,
                "settled_at": None,
            })

        x = result.get("v11_3") or {}
        ctx = result.get("ctx") or {}
        con = result.get("con") or {}
        game = result.get("game") or {}
        out[gid] = {
            "official_bets": bets,
            "shadow_v11_4": {
                "version": "11.4-shadow-data-v1",
                "official_effect": False,
                "status": "DATA_COLLECTION_ONLY",
                "v11_3_pick": x.get("v11_3_pick"),
                "v11_3_direction_score": x.get("v11_3_direction_score"),
                "v11_2_probability_for_pick": x.get("v11_2_probability_for_pick"),
                "quality": round(_f(result.get("quality")), 4),
                "phase": result.get("phase"),
                "projected_home_runs": round(_f(result.get("hmu")), 4),
                "projected_away_runs": round(_f(result.get("amu")), 4),
                "projected_run_diff_home": round(_f(result.get("hmu")) - _f(result.get("amu")), 4),
                "market_home_probability": (
                    round(_f(con.get("p")), 6) if con.get("p") is not None else None
                ),
                "market_reference_books": int(_f(con.get("n"), 0)),
                "home_team_id": ctx.get("home_id"),
                "away_team_id": ctx.get("away_id"),
                "current_venue_id": (game.get("venue") or {}).get("id"),
                "starter_home": ctx.get("home_sp"),
                "starter_away": ctx.get("away_sp"),
                "lineup_features": x.get("features") or {},
                "rest_home_days": None,
                "rest_away_days": None,
                "home_travel_venue_change": None,
                "away_travel_venue_change": None,
                "home_previous_extra_innings": None,
                "away_previous_extra_innings": None,
            },
        }
    return out


def _install_capture_hook():
    global _CORE
    if not _is_live_v113_run():
        return
    try:
        import bot as core
    except Exception:
        return
    _CORE = core
    original = getattr(core, "allocate_portfolio", None)
    if not callable(original):
        return

    def wrapped(results, *args, **kwargs):
        portfolio = original(results, *args, **kwargs)
        try:
            _CAPTURED.update(_official_bets_from_results(results))
        except Exception:
            pass
        return portfolio

    core.allocate_portfolio = wrapped


def _previous_game_context(target_date, team_ids):
    core = _CORE
    if core is None or not team_ids:
        return {}
    try:
        target = date.fromisoformat(str(target_date))
    except Exception:
        return {}
    wanted = {str(x) for x in team_ids if x}
    found = {}
    for back in range(1, 5):
        day = (target - timedelta(days=back)).isoformat()
        try:
            games = core.mlb_schedule(day, hydrate="probablePitcher,linescore")
        except Exception:
            continue
        for g in games:
            teams = g.get("teams") or {}
            venue_id = (g.get("venue") or {}).get("id")
            linescore = g.get("linescore") or {}
            innings = int(_f(linescore.get("currentInning"), 9))
            for side in ("home", "away"):
                tid = str(((teams.get(side) or {}).get("team") or {}).get("id") or "")
                if tid in wanted and tid not in found:
                    found[tid] = {
                        "days_back": back,
                        "venue_id": venue_id,
                        "extra_innings": innings > 9,
                    }
        if wanted.issubset(found.keys()):
            break
    return found


def _attach_capture(rows, report):
    run_id = str(report.get("run_id") or "")
    if not run_id or not _CAPTURED:
        return
    for row in rows:
        if str(row.get("run_id") or "") != run_id:
            continue
        captured = _CAPTURED.get(str(row.get("game_pk") or ""))
        if not captured:
            continue
        row["official_bets"] = captured["official_bets"]
        row["shadow_v11_4"] = captured["shadow_v11_4"]


def _enrich_shadow_rest(rows, report):
    run_id = str(report.get("run_id") or "")
    current = [
        r for r in rows
        if str(r.get("run_id") or "") == run_id and isinstance(r.get("shadow_v11_4"), dict)
    ]
    if not current:
        return
    team_ids = set()
    for r in current:
        s = r["shadow_v11_4"]
        team_ids.add(s.get("home_team_id"))
        team_ids.add(s.get("away_team_id"))
    previous = _previous_game_context(report.get("target_date"), team_ids)
    for r in current:
        s = r["shadow_v11_4"]
        current_venue = s.get("current_venue_id")
        for side in ("home", "away"):
            tid = str(s.get(f"{side}_team_id") or "")
            prev = previous.get(tid)
            if not prev:
                continue
            s[f"rest_{side}_days"] = max(0, int(prev["days_back"]) - 1)
            s[f"{side}_travel_venue_change"] = (
                None if current_venue is None or prev.get("venue_id") is None
                else str(current_venue) != str(prev.get("venue_id"))
            )
            s[f"{side}_previous_extra_innings"] = bool(prev.get("extra_innings"))


def _settle_one_bet(bet, row):
    if bet.get("status") in {"WIN", "LOSS", "PUSH"} or row.get("result_status") != "FINAL":
        return False
    if row.get("home_score") is None or row.get("away_score") is None:
        return False
    hs, aps = _f(row.get("home_score")), _f(row.get("away_score"))
    home, away = str(row.get("home") or ""), str(row.get("away") or "")
    market = str(bet.get("market") or "").upper()
    pick = str(bet.get("pick") or "")
    point = _f(bet.get("point"), 0)

    if market == "ML":
        winner = home if hs > aps else away if aps > hs else None
        result = "WIN" if winner and _norm(pick) == _norm(winner) else "LOSS" if winner else "PUSH"
    elif market == "RUNLINE":
        if _norm(pick) == _norm(home):
            margin = hs - aps + point
        elif _norm(pick) == _norm(away):
            margin = aps - hs + point
        else:
            return False
        result = "WIN" if margin > 1e-9 else "LOSS" if margin < -1e-9 else "PUSH"
    elif market == "TOTAL":
        total = hs + aps
        diff = total - point
        if abs(diff) <= 1e-9:
            result = "PUSH"
        elif pick.lower() == "over":
            result = "WIN" if diff > 0 else "LOSS"
        elif pick.lower() == "under":
            result = "WIN" if diff < 0 else "LOSS"
        else:
            return False
    else:
        return False

    units = max(0.0, _f(bet.get("units"), 0))
    price = _f(bet.get("winamax_price"), 0)
    if result == "WIN":
        pnl_u = units * (price - 1) if price > 1 else None
    elif result == "LOSS":
        pnl_u = -units
    else:
        pnl_u = 0.0

    bet["status"] = result
    bet["profit_units"] = round(pnl_u, 4) if pnl_u is not None else None
    unit_eur = _f(getattr(_CORE, "UNIT", 0.5), 0.5) if _CORE is not None else 0.5
    bet["profit_eur"] = round(pnl_u * unit_eur, 2) if pnl_u is not None else None
    bet["settled_at"] = datetime.now(timezone.utc).isoformat()
    return True


def _settle_finance(rows):
    changed = 0
    for row in rows:
        bets = row.get("official_bets")
        if not isinstance(bets, list):
            continue
        for bet in bets:
            changed += int(_settle_one_bet(bet, row))
    return changed


def _canonical_financial_bets(rows):
    by_game = {}
    for row in rows:
        bets = row.get("official_bets")
        if not isinstance(bets, list) or not bets:
            continue
        gid = str(row.get("game_pk") or "")
        if not gid:
            continue
        key = str(row.get("analyzed_at") or "")
        if gid not in by_game or key > by_game[gid][0]:
            by_game[gid] = (key, row)
    out = []
    for _, row in by_game.values():
        for bet in row.get("official_bets") or []:
            item = dict(bet)
            item["game_pk"] = row.get("game_pk")
            item["home"] = row.get("home")
            item["away"] = row.get("away")
            item["analyzed_at"] = row.get("analyzed_at")
            out.append(item)
    return out


def _finance_summary(rows):
    bets = _canonical_financial_bets(rows)
    settled = [b for b in bets if b.get("status") in {"WIN", "LOSS", "PUSH"}]
    wins = sum(b.get("status") == "WIN" for b in settled)
    losses = sum(b.get("status") == "LOSS" for b in settled)
    pushes = sum(b.get("status") == "PUSH" for b in settled)
    staked = sum(_f(b.get("units")) for b in settled if b.get("status") != "PUSH")
    pnl_known = [b for b in settled if b.get("profit_units") is not None]
    pnl_u = sum(_f(b.get("profit_units")) for b in pnl_known)
    roi = pnl_u / staked if staked > 0 and len(pnl_known) == len(settled) else None

    by_market = {}
    for market in ("ML", "RUNLINE", "TOTAL"):
        xs = [b for b in settled if b.get("market") == market]
        if not xs:
            continue
        stake = sum(_f(b.get("units")) for b in xs if b.get("status") != "PUSH")
        known = [b for b in xs if b.get("profit_units") is not None]
        pu = sum(_f(b.get("profit_units")) for b in known)
        by_market[market] = {
            "n": len(xs),
            "wins": sum(b.get("status") == "WIN" for b in xs),
            "losses": sum(b.get("status") == "LOSS" for b in xs),
            "pushes": sum(b.get("status") == "PUSH" for b in xs),
            "staked_units": round(stake, 4),
            "profit_units": round(pu, 4) if known else None,
            "roi": round(pu / stake, 6) if stake > 0 and len(known) == len(xs) else None,
        }

    return {
        "definition": "latest recorded official plan per game; simulated at recorded Winamax price",
        "bets_recorded": len(bets),
        "settled": len(settled),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "staked_units": round(staked, 4),
        "profit_units": round(pnl_u, 4) if pnl_known else None,
        "roi": round(roi, 6) if roi is not None else None,
        "by_market": by_market,
    }


def _shadow_summary(rows):
    seen = set()
    n = 0
    for row in sorted(rows, key=lambda r: str(r.get("analyzed_at") or ""), reverse=True):
        gid = str(row.get("game_pk") or "")
        if gid in seen or row.get("result_status") != "FINAL":
            continue
        if isinstance(row.get("shadow_v11_4"), dict):
            seen.add(gid)
            n += 1
    return {
        "version": "11.4-shadow-data-v1",
        "official_effect": False,
        "status": "DATA_COLLECTION_ONLY",
        "settled_games_with_shadow_features": n,
        "features_collected": [
            "lineup_features", "projected_run_diff_home", "market_home_probability",
            "rest_home_days", "rest_away_days", "home_travel_venue_change",
            "away_travel_venue_change", "home_previous_extra_innings",
            "away_previous_extra_innings", "starter_home", "starter_away",
        ],
        "note": "No V11.4 prediction is promoted or used for Discord picks until a walk-forward challenger is validated.",
    }


def _post_discord(report):
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    settled_now = int(report.get("settled_comparison_rows_this_run") or 0)
    finance = report.get("official_finance") or {}
    finance_settled_now = int(report.get("official_bets_settled_this_run") or 0)
    if settled_now <= 0 and finance_settled_now <= 0:
        return

    c = report.get("comparison") or {}
    n = int(c.get("settled_games") or 0)
    v10w = int(c.get("v10_wins") or 0)
    v11w = int(c.get("v11_3_wins") or 0)
    net = int(c.get("v11_net_corrections") or 0)

    grade_lines = []
    for grade in ("FORT", "BON", "PRUDENCE", "FAIBLE"):
        g = (c.get("by_grade") or {}).get(grade)
        if g:
            grade_lines.append(
                f"**{grade}** : {int(g.get('wins') or 0)}/{int(g.get('n') or 0)} ({_pct(g.get('accuracy'))})"
            )
    if not grade_lines:
        grade_lines = ["Pas encore assez de matchs réglés par grade."]

    if net > 0:
        verdict = f"🟢 V11.3 apporte **+{net} bonne prédiction nette** vs V10."
        color = 5763719
    elif net < 0:
        verdict = f"🔴 V11.3 est à **{net} prédiction nette** vs V10."
        color = 15548997
    else:
        verdict = "🟡 V11.3 et V10 sont à égalité en corrections nettes."
        color = 16766720

    pnl = finance.get("profit_units")
    pnl_txt = "—" if pnl is None else f"{float(pnl):+.2f}u"
    fin_lines = [
        f"Résultats : **{int(finance.get('wins') or 0)}V / {int(finance.get('losses') or 0)}D / {int(finance.get('pushes') or 0)}P**",
        f"Mise cumulée : **{_num(finance.get('staked_units'), 2)}u**",
        f"P/L simulé : **{pnl_txt}**",
        f"ROI simulé : **{_pct(finance.get('roi'))}**",
        "*Dernier Plan Officiel enregistré par match, aux cotes Winamax enregistrées.*",
    ]
    labels = {"ML": "ML", "RUNLINE": "RL", "TOTAL": "Total"}
    for market in ("ML", "RUNLINE", "TOTAL"):
        m = (finance.get("by_market") or {}).get(market)
        if not m:
            continue
        pu = m.get("profit_units")
        pu_txt = "—" if pu is None else f"{float(pu):+.2f}u"
        fin_lines.append(
            f"**{labels[market]}** : {int(m.get('wins') or 0)}V-{int(m.get('losses') or 0)}D-"
            f"{int(m.get('pushes') or 0)}P • {pu_txt} • ROI {_pct(m.get('roi'))}"
        )

    fields = [
        {
            "name": "🏆 Direction — cumulé live",
            "value": (
                f"V10 : **{v10w}/{n} ({_pct(c.get('v10_accuracy'))})**\n"
                f"V11.3 : **{v11w}/{n} ({_pct(c.get('v11_3_accuracy'))})**\n"
                f"Corrections : **{int(c.get('v11_corrections') or 0)}** • "
                f"régressions : **{int(c.get('v11_regressions') or 0)}** • net **{net:+d}**"
            ),
            "inline": False,
        },
        {
            "name": "🎯 Calibration ML",
            "value": (
                f"Brier V10 **{_num(c.get('v10_brier'))}** → V11.2 **{_num(c.get('v11_2_brier'))}**\n"
                f"LogLoss V10 **{_num(c.get('v10_logloss'))}** → V11.2 **{_num(c.get('v11_2_logloss'))}**"
            ),
            "inline": False,
        },
        {"name": "⭐ V11.3 par grade", "value": "\n".join(grade_lines), "inline": False},
        {"name": "💰 Plan Officiel — suivi financier", "value": "\n".join(fin_lines), "inline": False},
        {
            "name": "🧪 V11.4 shadow",
            "value": (
                "Collecte active : lineups, projection runs, marché, repos, changement de stade, "
                "extra innings précédent et starters.\n**Aucun effet sur les picks officiels.**"
            ),
            "inline": False,
        },
        {
            "name": "📌 Verdict provisoire",
            "value": verdict + "\nAucune promotion automatique : validation walk-forward + live obligatoire.",
            "inline": False,
        },
    ]
    payload = {
        "embeds": [{
            "title": "📊 BILAN LIVE — V10 vs V11.3",
            "description": (
                f"**{settled_now}** ligne(s) comparaison et **{finance_settled_now}** pari(s) officiel(s) "
                f"réglé(s) sur ce run."
            ),
            "color": color,
            "fields": fields,
            "footer": {"text": "V11.3 live • V11.4 shadow • résultats officiels MLB"},
        }]
    }
    try:
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "MLB-Betting-Bot-V11.3"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return


def _finalize():
    live_path = Path(os.getenv("V11_3_LIVE_FILE", "data/v11_3_live.jsonl"))
    report_path = Path(os.getenv("V11_3_LIVE_REPORT", "data/v11_3_live_report.json"))
    try:
        if not report_path.exists() or report_path.stat().st_mtime_ns < _START_NS:
            return
        report = json.loads(report_path.read_text(encoding="utf-8"))
        rows = _read_jsonl(live_path)
    except Exception:
        return

    try:
        _attach_capture(rows, report)
        _enrich_shadow_rest(rows, report)
        settled_finance = _settle_finance(rows)
        _write_jsonl(live_path, rows)

        report["official_bets_settled_this_run"] = settled_finance
        report["official_finance"] = _finance_summary(rows)
        report["v11_4_shadow"] = _shadow_summary(rows)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _post_discord(report)
    except Exception:
        return


if _is_live_v113_run():
    _install_capture_hook()
    atexit.register(_finalize)
