from __future__ import annotations

import math
from . import config, core, data_quality, storage


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def conservative_probability(rec):
    """Probability used for execution decisions, after an uncertainty haircut."""
    p = max(.001, min(.999, _num(rec.get("p_effective", rec.get("p_model")), .5)))
    unc = max(0.0, _num(rec.get("model_uncertainty"), config.FALLBACK_MODEL_UNCERTAINTY))
    return max(.001, p - config.UNCERTAINTY_EDGE_MULTIPLIER*unc)


def required_price(rec):
    p_cond = conservative_probability(rec)
    push = max(0.0, min(.95, _num(rec.get("p_push"), 0)))
    pwin = rec.get("p_win")
    if pwin is None:
        pwin = p_cond * (1-push)
    else:
        raw_cond = max(.001, min(.999, _num(rec.get("p_effective"), .5)))
        if raw_cond > 0:
            pwin = _num(pwin) * (p_cond/raw_cond)
    pwin = max(.001, min(1-push, _num(pwin, p_cond*(1-push))))
    fair = (1-push)/pwin
    ev_floor = (1+config.MIN_EV-push)/pwin
    conditional_edge = max(.001, p_cond-config.MIN_EDGE)
    edge_floor = 1/conditional_edge
    return max(fair, ev_floor, edge_floor, 1.01)


def value_gate(rec):
    e = rec.get("winamax_eval") or {}; price = _num(e.get("price"), 0); minimum = required_price(rec)
    push = max(0.0, min(.95, _num(rec.get("p_push"), 0)))
    raw_p = max(.001, min(.999, _num(rec.get("p_effective"), .5))); p_cons = conservative_probability(rec)
    pwin = rec.get("p_win")
    if pwin is None:
        pwin = p_cons*(1-push)
    else:
        pwin = _num(pwin) * (p_cons/raw_p) if raw_p > 0 else _num(pwin)
    pwin = max(0.0, min(1-push, pwin)); ploss = max(0.0, 1-pwin-push)
    ev = pwin*(price-1)-ploss if price > 1 else None
    return {"ok": price > 1 and price+1e-12 >= minimum, "price": price if price > 1 else None,
            "required_price": round(minimum, 4), "ev_at_price": round(ev, 6) if ev is not None else None,
            "p_win": round(pwin, 6), "p_push": round(push, 6), "p_conservative": round(p_cons, 6),
            "uncertainty": round(_num(rec.get("model_uncertainty"), config.FALLBACK_MODEL_UNCERTAINTY), 6)}


def full_kelly(rec, gate=None):
    gate = value_gate(rec) if gate is None else gate
    price = _num(gate.get("price"), 0); pw = max(0.0, min(1.0, _num(gate.get("p_win"))))
    pp = max(0.0, min(1-pw, _num(gate.get("p_push")))); pl = max(0.0, 1-pw-pp)
    if price <= 1 or pw+pl <= 0:
        return 0.0
    p = pw/(pw+pl); q = pl/(pw+pl); b = price-1
    return max(0.0, min(1.0, (b*p-q)/b)) if b > 0 else 0.0


def _score(result, rec, gate, dq):
    ev = max(-.20, min(.30, _num(gate.get("ev_at_price"), -.20)))
    edge = max(0.0, _num(gate.get("p_conservative"), .5)-.5)
    unc = max(0.0, _num(gate.get("uncertainty"), config.FALLBACK_MODEL_UNCERTAINTY))
    s = 45 + 165*max(0.0, ev) + 45*edge + 18*(dq["score"]-.65) - 80*unc
    return max(0.0, min(100.0, s))


def _combo_math(legs):
    if len(legs) != 2:
        return {"ev": None}
    parts = []
    for c in legs:
        g = c["gate"]; pw = max(0.0, min(1.0, _num(g.get("p_win")))); pp = max(0.0, min(1-pw, _num(g.get("p_push"))))
        price = _num(g.get("price"), 0)
        if price <= 1:
            return {"ev": None}
        parts.append((pw, pp, price))
    w1, p1, q1 = parts[0]; w2, p2, q2 = parts[1]
    expected_return = w1*w2*q1*q2 + w1*p2*q1 + p1*w2*q2 + p1*p2
    return {"ev": expected_return-1, "full_win_probability": w1*w2,
            "positive_profit_probability": w1*w2+w1*p2+p1*w2,
            "no_loss_probability": (w1+p1)*(w2+p2), "display_price": q1*q2}


def allocate(results, unit_eur=.5, bankroll_eur=10.0, existing=None):
    existing = storage.open_exposure() if existing is None else existing
    existing_game_ids = {str(v.get("game_pk")) for v in existing.values() if v.get("game_pk") and v.get("status") in {"PLACED", "PENDING"}}
    existing_keys = set(existing); pool = []
    for r in results:
        for rec in r.get("options") or []:
            e = rec.setdefault("winamax_eval", {}); dq = data_quality.assess(r, rec); rec["data_quality"] = dq
            gate = value_gate(rec); score = _score(r, rec, gate, dq)
            key = storage.bet_key(r.get("game_pk"), rec.get("market"), rec.get("name"), rec.get("point"))
            duplicate = key in existing_keys or str(r.get("game_pk")) in existing_game_ids
            e.update({"v11_price_gate": gate, "official_selected": False, "official_units": 0,
                      "selected": False, "units": 0.0, "stake_eur": 0.0,
                      "official_reason": "non retenu par V12", "bet_key": key})
            rec["selection_score"] = round(score, 2)
            eligible = gate["ok"] and dq["eligible"] and not duplicate
            if eligible:
                pool.append({"result": r, "rec": rec, "score": score, "gate": gate, "dq": dq,
                             "profile": str(rec.get("market") or "OTHER"), "bet_key": key})
            elif duplicate:
                e["official_reason"] = "position déjà ouverte sur ce match"
            elif not dq["eligible"]:
                e["official_reason"] = "qualité de données insuffisante: " + ", ".join(dq["blockers"] or [f"score {dq['score']:.2f}"])

    pool.sort(key=lambda x: (x["score"], _num(x["gate"].get("ev_at_price")), x["dq"]["score"]), reverse=True)
    chosen = []; used_games = set(existing_game_ids); profiles = {}; used_units = 0.0
    bankroll_eur = max(unit_eur, _num(bankroll_eur, unit_eur))
    for c in pool:
        if len(chosen) >= config.MAX_OFFICIAL_BETS:
            break
        gid = str(c["result"].get("game_pk"))
        if gid in used_games or profiles.get(c["profile"], 0) >= 2:
            continue
        threshold = config.OFFICIAL_SCORE_THRESHOLDS[min(len(chosen), len(config.OFFICIAL_SCORE_THRESHOLDS)-1)]
        if c["score"] < threshold:
            continue
        kelly = full_kelly(c["rec"], c["gate"]); stake_eur = bankroll_eur * kelly * config.FRACTIONAL_KELLY
        units = stake_eur/max(.01, unit_eur); units = max(config.MIN_STAKE_UNITS, min(config.MAX_BET_UNITS, units)); units = round(units*4)/4.0
        if used_units+units > config.MAX_DAILY_UNITS:
            units = math.floor(max(0.0, config.MAX_DAILY_UNITS-used_units)*4)/4.0
        if units < config.MIN_STAKE_UNITS:
            continue
        e = c["rec"]["winamax_eval"]
        e.update({"official_selected": True, "official_units": units, "selected": True, "units": units,
                  "stake_eur": round(units*unit_eur, 2), "kelly_full": round(kelly, 6),
                  "kelly_fraction": config.FRACTIONAL_KELLY,
                  "official_reason": f"V12 value: score {c['score']:.1f}/100, DQ {c['dq']['score']:.2f}, cote {c['gate']['price']:.2f} >= mini {c['gate']['required_price']:.2f}, EV prudent {100*_num(c['gate'].get('ev_at_price')):+.1f}%"})
        chosen.append(c); used_games.add(gid); profiles[c["profile"]] = profiles.get(c["profile"], 0)+1; used_units += units

    combo_candidates = [c for c in pool if str(c["result"].get("game_pk")) not in used_games and c["score"] >= 72 and _num(c["gate"].get("ev_at_price")) >= config.MIN_EV]
    legs = []; seen = set()
    for c in combo_candidates:
        gid = str(c["result"].get("game_pk"))
        if gid in seen:
            continue
        legs.append(c); seen.add(gid)
        if len(legs) == 2:
            break
    combo = {"available": False, "official": False, "legs": [], "units": 0.0, "reason": "moins de 2 legs indépendants qualifiés"}
    if len(legs) == 2:
        cm = _combo_math(legs); ev = _num(cm.get("ev"), -9); room = config.MAX_DAILY_UNITS-used_units
        official = ev >= config.MIN_COMBO_EV and room+1e-9 >= config.COMBO_UNITS
        combo = {"available": True, "official": official, "legs": legs,
                 "units": config.COMBO_UNITS if official else 0.0,
                 "probability": cm.get("full_win_probability"), "positive_profit_probability": cm.get("positive_profit_probability"),
                 "no_loss_probability": cm.get("no_loss_probability"), "winamax_price": cm.get("display_price"),
                 "ev": ev, "push_aware": True,
                 "reason": "retenu V12" if official else ("EV combiné insuffisante" if ev < config.MIN_COMBO_EV else "plafond exposition")}
    total_units = used_units+(combo["units"] if combo.get("official") else 0)
    portfolio = {"daily_cap": round(config.MAX_DAILY_UNITS*unit_eur, 2), "allocated": round(total_units*unit_eur, 2),
                 "remaining": round(max(0, (config.MAX_DAILY_UNITS-total_units)*unit_eur), 2),
                 "official_count": len(chosen), "official_units": used_units,
                 "combo_official": bool(combo.get("official")), "combo_units": _num(combo.get("units"), 0),
                 "bankroll_eur": bankroll_eur, "staking": f"{config.FRACTIONAL_KELLY:g} Kelly fraction",
                 "selector_version": "V12-professional-portfolio-v1"}
    return portfolio, chosen, combo, pool
