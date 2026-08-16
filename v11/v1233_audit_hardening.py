from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

VERSION = "v12.3.3-audit-hardening-v1"
DELIVERY_FILE = Path("data/v11_discord_delivery.json")
_INSTALLED = False


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _floor_quarter(x):
    return math.floor(max(0.0, _num(x))*4.0 + 1e-12)/4.0


def _dq_without_execution_dependency(result, rec, original_assess, config):
    payload = original_assess(result, rec)
    if rec is None:
        return payload
    components = dict(payload.get("components") or {})
    blockers = [x for x in payload.get("blockers") or [] if x != "execution_price_missing"]
    # Selection is informational and sharp-reference based. Winamax/execution
    # availability is deliberately excluded from DQ score and blockers.
    weights = {"starter_identity": .09, "starter_stats": .14, "lineup_identity": .08, "lineup_stats": .14,
               "team_stats": .11, "weather": .06, "bullpen": .11, "sharp_coverage": .13,
               "sharp_recency": .08}
    used = [(k, v) for k, v in components.items() if k in weights]
    denom = sum(weights[k] for k, _ in used) or 1.0
    score = sum(weights[k]*_num(v) for k, v in used)/denom
    payload["score"] = round(max(0.0, min(1.0, score)), 4)
    payload["blockers"] = blockers
    payload["eligible"] = payload["score"] >= config.MIN_DATA_QUALITY and not blockers
    payload["execution_price_required_for_selection"] = False
    return payload


def _gate_hardening(rec, original_gate, config):
    gate = dict(original_gate(rec))
    if not gate.get("ok"):
        gate.setdefault("sharp_gap_ok", False if gate.get("sharp_disagreement") is not None else True)
        gate.setdefault("reference_depth_ok", int(_num(gate.get("reference_quote_count"), 0)) >= 1)
        return gate

    gap = gate.get("sharp_disagreement")
    free = max(0.0, _num(getattr(config, "V123_SHARP_GAP_FREE", .08), .08))
    gap_excess = max(0.0, _num(gap, 0.0)-free) if gap is not None else 0.0
    # A large model-vs-sharp disagreement can be genuine edge, but it must earn
    # extra EV instead of surviving on the same gate as a market-consensus pick.
    extra_ev_gap = min(.04, .40*gap_excess)

    quotes = int(_num(gate.get("reference_quote_count"), 0))
    # One exact sharp quote remains usable for analysis, but an official pick
    # needs an extra 2pp EV and 2pp model confidence because outlier risk is higher.
    single_quote = quotes == 1
    extra_ev_depth = .02 if single_quote else 0.0
    extra_conf_depth = .02 if single_quote else 0.0

    required_ev = _num(config.MIN_EV, .03) + extra_ev_gap + extra_ev_depth
    ev = _num(gate.get("ev_at_price"), -1.0)
    raw_p = max(.001, min(.999, _num(rec.get("p_effective"), .5)))
    base_conf = _num(gate.get("min_confidence"), .55)
    required_conf = min(.75, base_conf + extra_conf_depth)

    sharp_gap_ok = ev + 1e-12 >= (_num(config.MIN_EV, .03) + extra_ev_gap)
    reference_depth_ok = quotes >= 2 or (quotes == 1 and ev + 1e-12 >= required_ev and raw_p + 1e-12 >= required_conf)
    gate.update({
        "sharp_gap_ok": sharp_gap_ok,
        "reference_depth_ok": reference_depth_ok,
        "single_sharp_quote": single_quote,
        "required_ev_hardened": round(required_ev, 6),
        "required_confidence_hardened": round(required_conf, 6),
        "ok": bool(gate.get("ok") and sharp_gap_ok and reference_depth_ok),
    })
    return gate


def _portfolio_haircut(portfolio, chosen, unit_eur, bankroll_eur, config):
    """Conservative portfolio risk budget without inventing a covariance model."""
    if not chosen:
        return portfolio, chosen
    bankroll = max(_num(bankroll_eur, unit_eur), _num(unit_eur, .5))
    existing_eur = max(0.0, _num((portfolio or {}).get("existing_allocated"), 0.0))
    risk_used = existing_eur
    market_counts = defaultdict(int)
    new_units = 0.0
    for item in chosen:
        rec = item["rec"]
        e = rec.get("winamax_eval") or {}
        original_units = max(0.0, _num(e.get("official_units"), 0.0))
        market = str(rec.get("market") or "OTHER").upper()
        residual_multiplier = max(.60, min(1.0, (bankroll-risk_used)/bankroll))
        concentration_multiplier = .85 ** market_counts[market]
        adjusted = _floor_quarter(original_units*residual_multiplier*concentration_multiplier)
        if original_units >= config.MIN_STAKE_UNITS:
            adjusted = max(config.MIN_STAKE_UNITS, adjusted)
        adjusted = min(original_units, adjusted)
        e["portfolio_risk_multiplier"] = round(residual_multiplier*concentration_multiplier, 4)
        e["portfolio_same_market_prior"] = market_counts[market]
        e["official_units_pre_portfolio"] = original_units
        e["official_units"] = adjusted
        e["units"] = adjusted
        e["stake_eur"] = round(adjusted*unit_eur, 2)
        rec["winamax_eval"] = e
        risk_used += adjusted*unit_eur
        new_units += adjusted
        market_counts[market] += 1
    out = dict(portfolio or {})
    total_units = _num(out.get("existing_allocated"), 0.0)/max(.01, unit_eur) + new_units
    out["new_allocated"] = round(new_units*unit_eur, 2)
    out["allocated"] = round(total_units*unit_eur, 2)
    out["remaining"] = round(max(0.0, (config.MAX_DAILY_UNITS-total_units)*unit_eur), 2)
    out["official_units"] = round(total_units, 4)
    out["new_official_units"] = round(new_units, 4)
    out["portfolio_risk_haircut"] = "residual-bankroll x same-market concentration; no fabricated covariance"
    return out, chosen


def _date_key(ex):
    return str(ex.get("sort_key") or "")[:10]


def day_block_walk_forward(exs, opt):
    """Expanding walk-forward where no result from a test calendar day can enter its fit."""
    if len(exs) < opt.MIN_GAMES + 1:
        return {"status": "COLLECTING", "windows": 0, "test_games": 0, "boundary": "calendar_day"}
    by_day = defaultdict(list)
    for ex in exs:
        by_day[_date_key(ex)].append(ex)
    days = sorted(by_day)
    train = []
    windows = []
    frozen = []
    i = 0
    while i < len(days) and len(train) < opt.MIN_GAMES:
        train.extend(by_day[days[i]])
        i += 1
    if len(train) < opt.MIN_GAMES or i >= len(days):
        return {"status": "COLLECTING", "windows": 0, "test_games": 0, "boundary": "calendar_day"}
    zero = {name: 0.0 for name in opt.MODULES}
    while i < len(days):
        test = []
        test_days = []
        while i < len(days) and (len(test) < opt.WF_TEST_GAMES or not test):
            test_days.append(days[i])
            test.extend(by_day[days[i]])
            i += 1
        weights = opt.fit_weights(train)
        b, o = opt.evaluate(test, zero), opt.evaluate(test, weights)
        windows.append({
            "train_games": len(train), "test_games": len(test), "train_through": _date_key(train[-1]),
            "test_days": test_days, "weights": weights,
            "brier_improvement": _num(b.get("brier"))-_num(o.get("brier")),
            "logloss_improvement": _num(b.get("logloss"))-_num(o.get("logloss")),
            "team_run_mae_improvement": _num(b.get("team_run_mae"))-_num(o.get("team_run_mae")),
        })
        frozen.append((list(test), weights))
        train.extend(test)

    # Aggregate the untouched day-block predictions.
    option_n = game_n = 0
    bb = bo = lb = lo = team_b = team_o = total_b = total_o = 0.0
    for test, weights in frozen:
        mb, mo = opt.evaluate(test, zero), opt.evaluate(test, weights)
        on, gn = int(mb.get("options") or 0), int(mb.get("games") or 0)
        option_n += on; game_n += gn
        bb += _num(mb.get("brier"))*on; bo += _num(mo.get("brier"))*on
        lb += _num(mb.get("logloss"))*on; lo += _num(mo.get("logloss"))*on
        team_b += _num(mb.get("team_run_mae"))*gn; team_o += _num(mo.get("team_run_mae"))*gn
        total_b += _num(mb.get("total_run_mae"))*gn; total_o += _num(mo.get("total_run_mae"))*gn
    return {
        "status": "ACTIVE", "windows": len(windows), "test_games": game_n, "boundary": "calendar_day",
        "baseline": {"brier": bb/max(1, option_n), "logloss": lb/max(1, option_n),
                     "team_run_mae": team_b/max(1, game_n), "total_run_mae": total_b/max(1, game_n)},
        "optimized": {"brier": bo/max(1, option_n), "logloss": lo/max(1, option_n),
                      "team_run_mae": team_o/max(1, game_n), "total_run_mae": total_o/max(1, game_n)},
        "windows_detail": windows[-6:],
    }


def neutralize_posthoc_identity_modules(modules):
    """Historical final-boxscore identities may be diagnostic, never trainable evidence."""
    for name in ("lineup_player", "platoon"):
        mod = modules.get(name) or {}
        mod["coverage"] = 0.0
        mod["status"] = "POSTHOC_IDENTITY_DIAGNOSTIC_ONLY"
        mod.setdefault("details", {})["trainable"] = False
        mod["details"]["reason"] = "starting lineup identity comes from final boxscore, not archived pregame lineup"
        modules[name] = mod
    return modules


def _load_delivery():
    try:
        value = json.loads(DELIVERY_FILE.read_text(encoding="utf-8")) if DELIVERY_FILE.exists() else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_delivery(value):
    DELIVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    DELIVERY_FILE.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _install_delivery_checkpoint(runner):
    def send(results, portfolio, chosen, combo, health, report):
        if not runner.core.discord_test():
            return False
        run_id = str((report or {}).get("run_id") or "unknown")
        state = _load_delivery()
        sent = set((state.get(run_id) or {}).get("sent") or [])

        def once(key, fn):
            if key in sent:
                return True
            ok = bool(fn())
            if ok:
                sent.add(key)
                state[run_id] = {"sent": sorted(sent)}
                _save_delivery(state)
            return ok

        if results:
            for r in results:
                gid = str(r.get("game_pk") or (r.get("game") or {}).get("gamePk") or "unknown")
                if not once(f"game:{gid}", lambda r=r: runner.discord.send_game(r, portfolio)):
                    return False
            if not once("top", lambda: runner.discord.send_top(results)):
                return False
            if not once("plan", lambda: runner.discord.send_plan(chosen, combo, portfolio, [])):
                return False
            if not once("health", lambda: runner.discord.send_health(health)):
                return False
        if not once("summary", lambda: runner._summary(report)):
            return False
        return True

    runner._send = send


def install():
    global _INSTALLED
    if _INSTALLED:
        return True
    from . import config, data_quality, selector, runner, v124_weight_optimizer as opt

    original_assess = data_quality.assess
    data_quality.assess = lambda result, rec=None: _dq_without_execution_dependency(result, rec, original_assess, config)

    original_gate = selector.value_gate
    selector.value_gate = lambda rec: _gate_hardening(rec, original_gate, config)

    original_allocate = selector.allocate
    def allocate(*args, **kwargs):
        portfolio, chosen, combo, pool = original_allocate(*args, **kwargs)
        unit = kwargs.get("unit_eur", args[1] if len(args) > 1 else .5)
        bankroll = kwargs.get("bankroll_eur", args[2] if len(args) > 2 else 10.0)
        portfolio, chosen = _portfolio_haircut(portfolio, chosen, unit, bankroll, config)
        return portfolio, chosen, combo, pool
    selector.allocate = allocate

    opt.walk_forward = lambda exs: day_block_walk_forward(exs, opt)
    opt.reset_cache()
    _install_delivery_checkpoint(runner)
    config.VERSION = "12.3.3-audit-hardening-v1"
    _INSTALLED = True
    return True
