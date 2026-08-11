import math


def clamp(x, a=.001, b=.999):
    return max(a, min(b, x))


def num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


LEAGUE = {"rpg": 4.45, "era": 4.35, "ops": .710, "obp": .320, "slg": .390, "whip": 1.32}


def safe_ratio(v, base, lo=.65, hi=1.55):
    if base <= 0:
        return 1.0
    return clamp(v / base, lo, hi)


def expected_starter_ip(sp):
    gs = max(0.0, num(sp.get("gs"), 0))
    ip = max(0.0, num(sp.get("ip"), 0))
    raw = ip / gs if gs >= 3 and ip > 0 else 5.3
    w = gs / (gs + 8.0)
    return clamp(5.3 + w * (raw - 5.3), 4.0, 6.5)


def advanced_base_runs(own_h, opp_p, own_recent, opp_sp, opp_bp, lineup, split, statcast, park, wx, home, lg=LEAGUE):
    """V10 deterministic baseball baseline. All advanced inputs affect mu before residual ML."""
    lg_rpg = lg["rpg"]
    lg_ops = lg["ops"]
    lg_era = lg["era"]
    lg_whip = lg["whip"]

    rpg = num(own_h.get("runsPerGame"), lg_rpg)
    ops = num(own_h.get("ops"), lg_ops)
    recent_r = num((own_recent or {}).get("runs_pg"), rpg)
    recent_games = int(num((own_recent or {}).get("games"), 0))

    gp = max(1.0, num(opp_p.get("gamesPlayed"), 0))
    runs_allowed = num(opp_p.get("runs"), 0)
    opp_ra = runs_allowed / gp if runs_allowed > 0 else lg_rpg * safe_ratio(num(opp_p.get("era"), lg_era), lg_era, .72, 1.35)

    log_mu = math.log(lg_rpg)
    log_mu += .34 * math.log(safe_ratio(rpg, lg_rpg, .70, 1.35))
    log_mu += .20 * math.log(safe_ratio(ops, lg_ops, .82, 1.18))
    log_mu += .14 * math.log(safe_ratio(opp_ra, lg_rpg, .72, 1.38))
    if recent_games >= 5:
        log_mu += .08 * math.log(safe_ratio(recent_r, lg_rpg, .72, 1.38))

    sip = expected_starter_ip(opp_sp)
    starter_share = sip / 9.0
    bullpen_share = 1.0 - starter_share
    sp_era = num(opp_sp.get("era"), lg_era)
    sp_whip = num(opp_sp.get("whip"), lg_whip)
    sp_k9 = num(opp_sp.get("k9"), 8.3)
    sp_bb9 = num(opp_sp.get("bb9"), 3.2)
    sp_quality = (sp_era - lg_era) / 1.45 + .45 * (sp_whip - lg_whip) / .28 + .18 * ((sp_bb9 - 3.2) / 1.4 - (sp_k9 - 8.3) / 2.4)
    log_mu += starter_share * clamp(sp_quality, -1.10, 1.10) * .23

    bp_era = num((opp_bp or {}).get("era"), lg_era)
    bp_whip = num((opp_bp or {}).get("whip"), lg_whip)
    bp_load = num((opp_bp or {}).get("load"), .5)
    bp_quality = (bp_era - lg_era) / 1.55 + .35 * (bp_whip - lg_whip) / .30 + .35 * (bp_load - .5) / .60
    log_mu += bullpen_share * clamp(bp_quality, -1.0, 1.2) * .22

    lineup_ops = (lineup or {}).get("weighted_ops")
    lineup_count = int(num((lineup or {}).get("count"), 0))
    if lineup_ops is not None and lineup_count >= 7:
        completeness = clamp(lineup_count / 9.0, 0, 1)
        log_mu += completeness * .18 * clamp((num(lineup_ops, ops) - ops) / .080, -1.0, 1.0)

    split_ops = (split or {}).get("_shrunk_ops")
    split_pa = num((split or {}).get("_pa"), 0)
    if split_ops is not None and split_pa >= 40:
        reliability = clamp(split_pa / 250.0, .20, 1.0)
        log_mu += reliability * .13 * clamp((num(split_ops, ops) - ops) / .080, -1.0, 1.0)

    xwoba = (statcast or {}).get("xwoba")
    pa = num((statcast or {}).get("pa"), 0)
    if xwoba is not None:
        reliability = clamp(pa / 1800.0, .25, 1.0)
        log_mu += reliability * .12 * clamp((num(xwoba, .317) - .317) / .045, -1.0, 1.0)

    log_mu += .55 * math.log(clamp(num(park, 1.0), .88, 1.16))
    log_mu += clamp(num((wx or {}).get("run_adj"), 0), -.25, .30) * .10

    mu = math.exp(log_mu) + (0.08 if home else 0.0)
    return clamp(mu, 2.0, 8.2)


def _base_inputs():
    own = {"runsPerGame": 4.45, "ops": .710}
    opp = {"gamesPlayed": 100, "runs": 445, "era": 4.35}
    recent = {"games": 10, "runs_pg": 4.45}
    sp = {"gs": 20, "ip": 106, "era": 4.35, "whip": 1.32, "k9": 8.3, "bb9": 3.2}
    bp = {"era": 4.35, "whip": 1.32, "load": .5}
    lineup = {"count": 9, "weighted_ops": .710}
    split = {"_shrunk_ops": .710, "_pa": 300}
    statcast = {"xwoba": .317, "pa": 2000}
    wx = {"run_adj": 0}
    return own, opp, recent, sp, bp, lineup, split, statcast, 1.0, wx


def self_test():
    x = _base_inputs()
    neutral = advanced_base_runs(*x, False)
    assert 4.1 < neutral < 4.8, neutral

    ace = dict(x[3])
    ace.update({"era": 2.30, "whip": 1.00, "k9": 11.0, "bb9": 2.0})
    weak = dict(x[3])
    weak.update({"era": 6.20, "whip": 1.65, "k9": 6.2, "bb9": 5.0})
    ace_mu = advanced_base_runs(x[0], x[1], x[2], ace, x[4], x[5], x[6], x[7], x[8], x[9], False)
    weak_mu = advanced_base_runs(x[0], x[1], x[2], weak, x[4], x[5], x[6], x[7], x[8], x[9], False)
    assert ace_mu < neutral < weak_mu, (ace_mu, neutral, weak_mu)
    assert weak_mu - ace_mu > .55, (ace_mu, weak_mu)

    hot_lineup = dict(x[5])
    hot_lineup["weighted_ops"] = .790
    cold_lineup = dict(x[5])
    cold_lineup["weighted_ops"] = .630
    hot = advanced_base_runs(x[0], x[1], x[2], x[3], x[4], hot_lineup, x[6], x[7], x[8], x[9], False)
    cold = advanced_base_runs(x[0], x[1], x[2], x[3], x[4], cold_lineup, x[6], x[7], x[8], x[9], False)
    assert hot > neutral > cold

    tired = dict(x[4])
    tired.update({"era": 5.8, "whip": 1.55, "load": 1.25})
    fresh = dict(x[4])
    fresh.update({"era": 3.1, "whip": 1.10, "load": .15})
    t = advanced_base_runs(x[0], x[1], x[2], x[3], tired, x[5], x[6], x[7], x[8], x[9], False)
    f = advanced_base_runs(x[0], x[1], x[2], x[3], fresh, x[5], x[6], x[7], x[8], x[9], False)
    assert t > f

    strong_sc = dict(x[7])
    strong_sc["xwoba"] = .355
    weak_sc = dict(x[7])
    weak_sc["xwoba"] = .285
    s = advanced_base_runs(x[0], x[1], x[2], x[3], x[4], x[5], x[6], strong_sc, x[8], x[9], False)
    w = advanced_base_runs(x[0], x[1], x[2], x[3], x[4], x[5], x[6], weak_sc, x[8], x[9], False)
    assert s > w

    print("V10 STEP1 ENGINE TEST OK", {"neutral": neutral, "ace": ace_mu, "weak": weak_mu, "hot": hot, "cold": cold, "tired_bp": t, "fresh_bp": f})


if __name__ == "__main__":
    self_test()
