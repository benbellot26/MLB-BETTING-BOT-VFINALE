from __future__ import annotations

import math
from . import config, data_quality, storage, pro_model


def _num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def conservative_probability(rec):
    p = max(.001, min(.999, _num(rec.get("p_effective", rec.get("p_model")), .5)))
    unc = max(0.0, _num(rec.get("model_uncertainty"), config.FALLBACK_MODEL_UNCERTAINTY))
    return max(.001, p-config.UNCERTAINTY_EDGE_MULTIPLIER*unc)


def required_price(rec):
    p_cond = conservative_probability(rec)
    push = max(0.0, min(.95, _num(rec.get("p_push"), 0)))
    raw_cond = max(.001, min(.999, _num(rec.get("p_effective"), .5)))
    raw_win = _num(rec.get("p_win"), raw_cond*(1-push))
    pwin = raw_win*(p_cond/raw_cond) if raw_cond > 0 else raw_win
    pwin = max(.001, min(1-push, pwin))
    fair = (1-push)/pwin
    ev_floor = (1+config.MIN_EV-push)/pwin
    edge_floor = 1/max(.001, p_cond-config.MIN_EDGE)
    return max(fair, ev_floor, edge_floor, 1.01)


def value_gate(rec):
    e = rec.get("winamax_eval") or {}
    price = _num(e.get("price"), 0)
    minimum = required_price(rec)
    push = max(0.0, min(.95, _num(rec.get("p_push"), 0)))
    raw_p = max(.001, min(.999, _num(rec.get("p_effective"), .5)))
    p_cons = conservative_probability(rec)
    raw_win = _num(rec.get("p_win"), raw_p*(1-push))
    pwin = max(0.0, min(1-push, raw_win*(p_cons/raw_p)))
    ploss = max(0.0, 1-pwin-push)
    ev = pwin*(price-1)-ploss if price > 1 else None
    return {"ok": price > 1 and price+1e-12 >= minimum, "price": price if price > 1 else None,
            "required_price": round(minimum, 4), "ev_at_price": round(ev, 6) if ev is not None else None,
            "p_win": round(pwin, 6), "p_push": round(push, 6), "p_conservative": round(p_cons, 6),
            "uncertainty": round(_num(rec.get("model_uncertainty"), config.FALLBACK_MODEL_UNCERTAINTY), 6)}


def full_kelly(rec, gate=None):
    gate = value_gate(rec) if gate is None else gate
    price = _num(gate.get("price"), 0)
    pw = max(0.0, min(1.0, _num(gate.get("p_win"))))
    pp = max(0.0, min(1-pw, _num(gate.get("p_push"))))
    pl = max(0.0, 1-pw-pp)
    if price <= 1 or pw+pl <= 0:
        return 0.0
    p, q, b = pw/(pw+pl), pl/(pw+pl), price-1
    return max(0.0, min(1.0, (b*p-q)/b)) if b > 0 else 0.0


def stake_units(rec, gate, unit_eur, bankroll_eur):
    kelly = full_kelly(rec, gate)
    raw = min(config.MAX_BET_UNITS, max(0.0, bankroll_eur*kelly*config.FRACTIONAL_KELLY/max(.01, unit_eur)))
    if raw+1e-12 < config.MIN_STAKE_UNITS:
        return 0.0, kelly, raw
    units = math.floor(raw*4+1e-12)/4.0
    return (units, kelly, raw) if units+1e-12 >= config.MIN_STAKE_UNITS else (0.0, kelly, raw)


def _score(rec, gate, dq):
    ev = max(-.20, min(.30, _num(gate.get("ev_at_price"), -.20)))
    edge = max(0.0, _num(gate.get("p_conservative"), .5)-.5)
    unc = max(0.0, _num(gate.get("uncertainty"), config.FALLBACK_MODEL_UNCERTAINTY))
    return max(0.0, min(100.0, 45+165*max(0.0, ev)+45*edge+18*(dq["score"]-.65)-80*unc))


def _combo_math(legs):
    if len(legs) != 2:
        return {"ev": None}
    parts = []
    for c in legs:
        g = c["gate"]
        pw, pp, price = _num(g.get("p_win")), _num(g.get("p_push")), _num(g.get("price"))
        if price <= 1:
            return {"ev": None}
        parts.append((pw, pp, price))
    w1, p1, q1 = parts[0]; w2, p2, q2 = parts[1]
    expected_return = w1*w2*q1*q2+w1*p2*q1+p1*w2*q2+p1*p2
    return {"ev": expected_return-1, "full_win_probability": w1*w2,
            "positive_profit_probability": w1*w2+w1*p2+p1*w2,
            "no_loss_probability": (w1+p1)*(w2+p2), "display_price": q1*q2,
            "independence_assumption": True}


def _same_slate(v, target_date):
    td = str(v.get("target_date") or "")
    return not target_date or not td or td == str(target_date)


def allocate(results, unit_eur=.5, bankroll_eur=10.0, existing=None, target_date=None):
    existing = storage.open_recommendations() if existing is None else existing
    daily = [v for v in existing.values() if v.get("status") in storage.OPEN_RECOMMENDATION_STATUSES and _same_slate(v, target_date)]
    existing_units = sum(max(0.0, _num(v.get("units"))) for v in daily)
    existing_singles = sum(v.get("bet_type") != "COMBO" for v in daily)
    existing_profiles, existing_game_ids = {}, set()
    for v in daily:
        if v.get("bet_type") == "COMBO":
            for leg in v.get("combo_legs") or []:
                if leg.get("game_pk") is not None:
                    existing_game_ids.add(str(leg.get("game_pk")))
        elif v.get("game_pk") is not None:
            existing_game_ids.add(str(v.get("game_pk")))
            m = str(v.get("market") or "OTHER")
            existing_profiles[m] = existing_profiles.get(m, 0)+1
    existing_keys = set(existing)
    champ = pro_model.load_model()
    pool = []
    for r in results:
        for rec in r.get("options") or []:
            e = rec.setdefault("winamax_eval", {})
            dq = data_quality.assess(r, rec)
            rec["data_quality"] = dq
            rec["model_uncertainty"] = round(pro_model.model_uncertainty(
                str(rec.get("market") or "ML"), _num(rec.get("p_effective"), .5), str(r.get("phase") or "EARLY"),
                rec.get("sharp_dispersion"), dq.get("score"), champ), 6)
            gate = value_gate(rec)
            score = _score(rec, gate, dq)
            key = storage.bet_key(r.get("game_pk"), rec.get("market"), rec.get("name"), rec.get("point"))
            duplicate = key in existing_keys or str(r.get("game_pk")) in existing_game_ids
            e.update({"v11_price_gate": gate, "official_selected": False, "official_units": 0, "selected": False,
                      "units": 0.0, "stake_eur": 0.0, "official_reason": "non retenu par V12.2", "bet_key": key})
            rec["selection_score"] = round(score, 2)
            if gate["ok"] and dq["eligible"] and not duplicate:
                pool.append({"result": r, "rec": rec, "score": score, "gate": gate, "dq": dq,
                             "profile": str(rec.get("market") or "OTHER"), "bet_key": key})
            elif duplicate:
                e["official_reason"] = "recommandation déjà publiée sur ce match"
            elif not dq["eligible"]:
                e["official_reason"] = "qualité de données insuffisante: "+", ".join(dq["blockers"] or [f"score {dq['score']:.2f}"])
    pool.sort(key=lambda x: (x["score"], _num(x["gate"].get("ev_at_price")), x["dq"]["score"]), reverse=True)
    chosen, used_games, profiles, used_units = [], set(existing_game_ids), dict(existing_profiles), existing_units
    bankroll_eur = max(unit_eur, _num(bankroll_eur, unit_eur))
    for c in pool:
        if existing_singles+len(chosen) >= config.MAX_OFFICIAL_BETS:
            break
        gid = str(c["result"].get("game_pk"))
        if gid in used_games or profiles.get(c["profile"], 0) >= 2:
            continue
        threshold = config.OFFICIAL_SCORE_THRESHOLDS[min(existing_singles+len(chosen), len(config.OFFICIAL_SCORE_THRESHOLDS)-1)]
        if c["score"] < threshold:
            continue
        units, kelly, raw_units = stake_units(c["rec"], c["gate"], unit_eur, bankroll_eur)
        room = max(0.0, config.MAX_DAILY_UNITS-used_units)
        units = min(units, math.floor(room*4+1e-12)/4.0)
        if units+1e-12 < config.MIN_STAKE_UNITS:
            c["rec"]["winamax_eval"]["official_reason"] = "Kelly prudent sous la mise minimale ou plafond journalier"
            continue
        e = c["rec"]["winamax_eval"]
        e.update({"official_selected": True, "official_units": units, "selected": True, "units": units,
                  "stake_eur": round(units*unit_eur, 2), "kelly_full": round(kelly, 6),
                  "kelly_fraction": config.FRACTIONAL_KELLY, "kelly_raw_units": round(raw_units, 4),
                  "official_reason": f"V12.2 value: score {c['score']:.1f}/100, DQ {c['dq']['score']:.2f}, EV prudent {100*_num(c['gate'].get('ev_at_price')):+.1f}%"})
        chosen.append(c); used_games.add(gid); profiles[c["profile"]] = profiles.get(c["profile"], 0)+1; used_units += units

    combo_candidates = [c for c in pool if str(c["result"].get("game_pk")) not in used_games and c["score"] >= 72 and _num(c["gate"].get("ev_at_price")) >= config.MIN_EV]
    legs, seen = [], set()
    for c in combo_candidates:
        gid = str(c["result"].get("game_pk"))
        if gid not in seen:
            legs.append(c); seen.add(gid)
        if len(legs) == 2:
            break
    combo = {"available": len(legs) == 2, "official": False, "legs": legs, "units": 0.0,
             "reason": "combinés officiels désactivés tant que le modèle de dépendance n'est pas validé"}
    if len(legs) == 2:
        combo.update(_combo_math(legs))
        combo["winamax_price"] = combo.get("display_price")
        if config.ENABLE_OFFICIAL_COMBOS:
            combo["reason"] = "activation manuelle refusée: modèle de dépendance non certifié en V12.2"

    new_units = sum(_num((c["rec"].get("winamax_eval") or {}).get("official_units")) for c in chosen)
    total_units = existing_units+new_units
    portfolio = {"daily_cap": round(config.MAX_DAILY_UNITS*unit_eur, 2), "existing_allocated": round(existing_units*unit_eur, 2),
                 "new_allocated": round(new_units*unit_eur, 2), "allocated": round(total_units*unit_eur, 2),
                 "remaining": round(max(0, (config.MAX_DAILY_UNITS-total_units)*unit_eur), 2),
                 "official_count": existing_singles+len(chosen), "new_official_count": len(chosen),
                 "official_units": total_units, "new_official_units": new_units, "combo_official": False,
                 "combo_units": 0.0, "bankroll_eur": bankroll_eur, "staking": f"{config.FRACTIONAL_KELLY:g} Kelly fraction",
                 "selector_version": "V12.2-professional-portfolio-v3"}
    return portfolio, chosen, combo, pool
