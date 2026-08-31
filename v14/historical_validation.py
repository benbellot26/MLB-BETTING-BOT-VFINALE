from __future__ import annotations

"""V14.5 historical validation laboratory.

Evidence tiers are deliberately separated:
- Tier A: 14k+ strict J-1 team-history games, suitable for team-run priors.
- Tier B: 1,801+ richer growing 2026 reconstructions, suitable for rolling audit/ranking only.
- Tier C: exact recorded pregame replays, market-rich but currently small.
Native V14 prospective data remains mandatory before a champion change and
before betting certification. Growing 2026 data is explicitly NOT a blind or
sealed frozen holdout.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, VERSION
from .champion_contract import CHAMPION_DISPERSION, CHAMPION_ENVIRONMENT_SIGMA, validated_extra_innings_home_probability
from .distribution import probability_surface
from .historical_dataset import load_verified, split_by_season
from .historical_distribution_validation import build as build_distribution_validation
from .historical_team_challenger import baseline_runs, candidate_runs, evaluate_split, historical_gate, tune
from .model import RunProjection

OUTPUT = Path("data/v14_historical_validation.json")
RICH_REPORT = Path("data/mlb_backtest_2026_report.json")
REPLAY_REPORT = Path("data/v13_historical_backfill_report.json")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _clip(p: float) -> float:
    return max(1e-9, min(1.0 - 1e-9, float(p)))


def _mean_ci(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95_lower": None, "ci95_upper": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"n": len(values), "mean": mean, "ci95_lower": None, "ci95_upper": None}
    var = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    se = math.sqrt(var / len(values))
    return {"n": len(values), "mean": mean, "ci95_lower": mean - 1.96 * se, "ci95_upper": mean + 1.96 * se}


def _ece(y: list[int], p: list[float], bins: int = 10) -> float | None:
    if not y:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, q in enumerate(p) if lo <= q < hi or (b == bins - 1 and q == 1.0)]
        if not idx:
            continue
        mp = sum(p[i] for i in idx) / len(idx); oy = sum(y[i] for i in idx) / len(idx)
        total += len(idx) / len(y) * abs(mp - oy)
    return total


def _prob_metrics(y: list[int], p: list[float]) -> dict[str, Any]:
    if not y:
        return {"n": 0, "brier": None, "logloss": None, "ece": None}
    return {
        "n": len(y),
        "brier": sum((q - z) ** 2 for q, z in zip(p, y)) / len(y),
        "logloss": -sum(z * math.log(_clip(q)) + (1 - z) * math.log(_clip(1 - q)) for q, z in zip(p, y)) / len(y),
        "ece": _ece(y, p),
    }


def _home_ml(game_pk: str, game_date: str, analyzed_at: str, home_mu: float, away_mu: float) -> float:
    extra, _ = validated_extra_innings_home_probability()
    projection = RunProjection(game_pk=game_pk, game_date=game_date, analyzed_at=analyzed_at, home="HOME", away="AWAY", home_mu=home_mu, away_mu=away_mu, total_line=8.5, dispersion=CHAMPION_DISPERSION, environment_sigma=CHAMPION_ENVIRONMENT_SIGMA, extra_innings_home_probability=extra, source_generation="v14.5-historical-team-validation")
    surface, _ = probability_surface(projection)
    return float(surface.home_ml)


def probability_translation(pairs: list[tuple[dict[str, Any], dict[str, Any]]], params: dict[str, float]) -> dict[str, Any]:
    # Every row in the declared temporal slice is evaluated: no outcome-based
    # subsampling. Keep the legacy `full_holdout` key temporarily for workflow
    # compatibility, but define it strictly as slice completeness, NOT blindness.
    # Scientific independence is stated separately by `blind_holdout=False`.
    sampled = list(pairs); y: list[int] = []; pb: list[float] = []; pc: list[float] = []; bd: list[float] = []; ld: list[float] = []
    for feature, label in sampled:
        gid = str(feature.get("game_pk") or ""); game_date = str(feature.get("game_date") or ""); analyzed_at = str(feature.get("as_of") or game_date)
        bh, ba = baseline_runs(feature); ch, ca = candidate_runs(feature, params); b = _home_ml(gid, game_date, analyzed_at, bh, ba); c = _home_ml(gid, game_date, analyzed_at, ch, ca); z = int(_num(label.get("home_score")) > _num(label.get("away_score")))
        y.append(z); pb.append(b); pc.append(c); bd.append((b-z)**2-(c-z)**2)
        bl=-(z*math.log(_clip(b))+(1-z)*math.log(_clip(1-b))); cl=-(z*math.log(_clip(c))+(1-z)*math.log(_clip(1-c))); ld.append(bl-cl)
    return {
        "sample_policy":"complete temporal audit slice; no outcome-dependent subsampling",
        "full_slice":True,
        "blind_holdout":False,
        "full_holdout":True,
        "full_holdout_key_deprecated":True,
        "full_holdout_semantics":"legacy compatibility: complete temporal slice only; does not mean blind or sealed",
        "baseline":_prob_metrics(y,pb),
        "candidate":_prob_metrics(y,pc),
        "paired_brier_gain":_mean_ci(bd),
        "paired_logloss_gain":_mean_ci(ld),
        "distribution":{"dispersion":CHAMPION_DISPERSION,"environment_sigma":CHAMPION_ENVIRONMENT_SIGMA},
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists(): return {}
    try: value=json.loads(path.read_text(encoding="utf-8"))
    except Exception: return {}
    return value if isinstance(value,dict) else {}


def evidence_registry() -> dict[str, Any]:
    rich=_load_json(RICH_REPORT); replay=_load_json(REPLAY_REPORT); rich_games=int(rich.get("games") or 0); replay_games=int(replay.get("canonical_games") or 0); methodology=rich.get("methodology") or {}
    return {
        "tier_a_team_history":{"status":"VALIDATED_BY_THIS_RUN","use":"team-level run priors, recent-form shrinkage, run-distribution research"},
        "tier_b_rich_2026_reconstruction":{"status":"ROLLING_AUDIT_ONLY" if rich_games else "UNAVAILABLE","games":rich_games,"walk_forward":methodology.get("walk_forward"),"future_game_stats_used":methodology.get("future_game_stats_used"),"statcast_used":methodology.get("statcast_used"),"weather_used":methodology.get("weather_used"),"final_lineup_identity_with_prior_stats":methodology.get("actual_final_lineup_used_with_prior_player_stats"),"blind_holdout":False,"use":"starter/lineup/run-prior ranking and regression detection; cannot certify alpha or champion promotion"},
        "tier_c_exact_pregame_replays":{"status":"SMALL_EXACT_REPLAY_EVIDENCE" if replay_games else "UNAVAILABLE","games":replay_games,"replay_pass":replay.get("replay_pass"),"replay_fail":replay.get("replay_fail"),"use":"feature-semantic parity and market/probability diagnostics; insufficient for promotion floors"},
        "native_v14_prospective":{"status":"FINAL_AUTHORITY","use":"mandatory sealed prospective confirmation before champion promotion and only source that can satisfy betting certification"},
    }


def build() -> dict[str, Any]:
    pairs,dataset=load_verified(); split=split_by_season(pairs); tuning=tune(split["tuning"])
    audit_2026=split["frozen_test"]
    base={"schema":"pulsar-v14-historical-validation-v4","software_version":VERSION,"model_generation":MODEL_GENERATION,"role":"RESEARCH_EVIDENCE_ONLY","auto_activation":False,"generated_at":datetime.now(timezone.utc).isoformat(),"dataset":dataset,"split":{"tuning_2021_2024":len(split["tuning"]),"validation_2025":len(split["validation"]),"audit_2026":len(audit_2026),"frozen_test_2026":len(audit_2026),"frozen_test_2026_key_deprecated":True,"audit_2026_role":"ROLLING_AUDIT_NOT_BLIND_HOLDOUT","audit_2026_used_for_parameter_selection":False,"frozen_2026_used_for_parameter_selection":False},"evidence_registry":evidence_registry()}
    if tuning.get("status")!="TUNED_RESEARCH_ONLY": return {**base,"status":"COLLECTING","team_run_challenger":{"tuning":tuning}}
    params=tuning["parameters"]; validation=evaluate_split(split["validation"],params); audit=evaluate_split(audit_2026,params); gate=historical_gate(validation,audit); pval=probability_translation(split["validation"],params); paudit=probability_translation(audit_2026,params)
    vb=pval["paired_brier_gain"]; vl=pval["paired_logloss_gain"]; ab=paudit["paired_brier_gain"]; al=paudit["paired_logloss_gain"]
    downstream_validation=bool(vb.get("ci95_lower") is not None and float(vb["ci95_lower"])>=-.0015 and vl.get("ci95_lower") is not None and float(vl["ci95_lower"])>=-.003)
    downstream_audit=bool(ab.get("mean") is not None and float(ab["mean"])>=-.001 and al.get("mean") is not None and float(al["mean"])>=-.002)
    historical_candidate=bool(gate.get("passes") and downstream_validation and downstream_audit); status="HISTORICAL_SHADOW_CANDIDATE" if historical_candidate else "REJECTED_HISTORICAL"
    distribution=build_distribution_validation(split,params)
    component_recommendations={
        "run_means":"SHADOW_ON_NATIVE_V14" if historical_candidate else "KEEP_CURRENT_RUN_MEANS",
        "score_distribution":"SHADOW_ON_NATIVE_V14" if distribution.get("passes") else "KEEP_CURRENT_DISTRIBUTION",
        "advanced_features":"COLLECT_STRICT_PIT_AND_VALIDATE_OOS",
    }
    return {**base,"status":status,"team_run_challenger":{"status":status,"tuning":tuning,"validation_2025":validation,"audit_2026":audit,"frozen_2026":audit,"frozen_2026_key_deprecated":True,"run_gate":gate,"probability_translation_2025":pval,"probability_translation_audit_2026":paudit,"probability_translation_frozen_2026":paudit,"downstream_probability_validation_pass":downstream_validation,"downstream_probability_audit_nonregression":downstream_audit,"downstream_probability_frozen_nonregression":downstream_audit,"promotion_policy":"historical evidence may nominate a shadow challenger only; growing 2026 is rolling audit, never blind promotion evidence; preregistered native V14 prospective confirmation is mandatory before changing MODEL_GENERATION"},"score_distribution_challenger":distribution,"component_recommendations":component_recommendations,"recommended_next_state":"SHADOW_ON_NATIVE_V14" if historical_candidate else "KEEP_CURRENT_CHAMPION"}


def write(output:Path|str=OUTPUT)->dict[str,Any]:
    artifact=build(); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(description="Run V14.5 strict historical PIT validation"); parser.add_argument("--output",default=str(OUTPUT)); args=parser.parse_args(); out=write(args.output)
    print(json.dumps({"schema":out.get("schema"),"status":out.get("status"),"split":out.get("split"),"recommended_next_state":out.get("recommended_next_state"),"component_recommendations":out.get("component_recommendations"),"parameters":(((out.get("team_run_challenger") or {}).get("tuning") or {}).get("parameters")),"distribution_status":((out.get("score_distribution_challenger") or {}).get("status"))},sort_keys=True))


if __name__=="__main__": main()
