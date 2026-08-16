from __future__ import annotations

from collections import defaultdict

from . import v124_historical_reconstruction as base

VERSION = "v12.4-historical-daily-freeze-v2"


def _starter_name(box, side, starter_id):
    if starter_id is None:
        return None
    for player in base._box_players(box, side):
        person = player.get("person") or {}
        if str(person.get("id")) == str(starter_id):
            return person.get("fullName")
    return None


def _hydrate_starter_names(result, row, box):
    ctx = result.get("ctx") or {}
    for side in ("home", "away"):
        pid = base._starter_id(row, side)
        starter = ctx.get(f"{side}_starter") or {}
        if pid is not None and not starter.get("name"):
            starter["name"] = _starter_name(box, side, pid)
            ctx[f"{side}_starter"] = starter
    return result


def reconstruct(source_rows, boxes, use_statcast=True):
    """Strict J-1 reconstruction: all games on a date see the same prior-day state."""
    from . import core
    from .v124_statcast_provider import install as install_statcast
    from .v124_starter_ip_v2 import install as install_starter_ip_v2
    from .v1233_audit_hardening import neutralize_posthoc_identity_modules

    install_statcast()
    install_starter_ip_v2()
    core.SEASON = 2026
    state = base.State()
    reconstructed = []
    failures = []
    by_date = defaultdict(list)
    for idx, row in enumerate(source_rows):
        by_date[base._date_key(row)].append((idx, row))

    for day in sorted(by_date):
        pending_updates = []
        for idx, row in by_date[day]:
            gid = str(row.get("game_pk"))
            box = boxes.get(gid)
            if not box:
                failures.append({"game_pk": row.get("game_pk"), "reason": "missing_boxscore"})
                continue
            pending_updates.append((row, box))
            try:
                result = _hydrate_starter_names(base._build_result(row, box, state), row, box)
                base_h = max(1.6, min(8.0, base._num((row.get("v10") or {}).get("home_struct"), 4.4)))
                base_a = max(1.6, min(8.0, base._num((row.get("v10") or {}).get("away_struct"), 4.2)))
                modules = base._modules(result, row, state, use_statcast=use_statcast)
                # Starting-lineup identities come from the final boxscore. They remain
                # useful diagnostics but can no longer train lineup/platoon weights.
                modules = neutralize_posthoc_identity_modules(modules)
                variants = {
                    "baseline_historical_proxy": {
                        "home_mu": base_h, "away_mu": base_a,
                        "options": base._variant_options(result, base_h, base_a),
                    },
                }
                for name in base.MODULES:
                    mod = modules.get(name) or {}
                    hf = max(.80, min(1.20, base._num(mod.get("home_factor"), 1.0)))
                    af = max(.80, min(1.20, base._num(mod.get("away_factor"), 1.0)))
                    h, a = base_h*hf, base_a*af
                    variants[f"only_{name}"] = {
                        "home_mu": h, "away_mu": a,
                        "home_factor": hf, "away_factor": af,
                        "options": base._variant_options(result, h, a),
                    }
                reconstructed.append({
                    "schema": base.SCHEMA,
                    "version": base.VERSION,
                    "game_pk": row.get("game_pk"),
                    "game_date": row.get("game_date"),
                    "home": row.get("home"), "away": row.get("away"),
                    "home_score": row.get("home_score"), "away_score": row.get("away_score"),
                    "options": result.get("options") or [],
                    "shadow_v124": {
                        "enabled": True, "status": "HISTORICAL_RECONSTRUCTED",
                        "research_only": True, "affects_v12_selection": False,
                        "base_home_mu": base_h, "base_away_mu": base_a,
                        "modules": modules, "variants": variants,
                    },
                    "historical_reconstruction": {
                        "source_index": idx,
                        "baseline_source": "legacy V10 structural means used only as warm-start proxy",
                        "market_scope": ["ML", "RUNLINE"],
                        "historical_odds_used": False,
                        "roi_trainable": False,
                        "lineup_identity": "posthoc starting-lineup identity; lineup/platoon coverage forced to zero for fitting",
                        "starter_identity": "boxscore starter id/name used only for identity; performance state is strict J-1",
                        "player_stats": "strict J-1 state; current calendar date applied only after every game on that date is predicted",
                        "same_day_results_visible": False,
                        "posthoc_identity_trainable": False,
                        "starter_ip_version": "v2-duration-quality-decoupled",
                        "weather": "excluded: no archived pregame forecast",
                        "statcast": "Baseball Savant point-in-time cutoff" if use_statcast else "disabled",
                        "native_v124_evidence": False,
                    },
                })
            except Exception as exc:
                failures.append({"game_pk": row.get("game_pk"), "reason": f"{type(exc).__name__}: {exc}"})

        # Only after every prediction for this date is frozen may the date enter state.
        for row, box in pending_updates:
            state.update(row, box)

    reconstructed.sort(key=lambda r: (str(r.get("game_date") or ""), int(r.get("game_pk") or 0)))
    return reconstructed, failures


def main(argv=None):
    original = base.reconstruct
    from . import v124_weight_optimizer as opt
    from .v1233_audit_hardening import day_block_walk_forward
    original_wf = opt.walk_forward
    try:
        base.reconstruct = reconstruct
        opt.walk_forward = lambda exs: day_block_walk_forward(exs, opt)
        return base.main(argv)
    finally:
        base.reconstruct = original
        opt.walk_forward = original_wf


if __name__ == "__main__":
    raise SystemExit(main())
