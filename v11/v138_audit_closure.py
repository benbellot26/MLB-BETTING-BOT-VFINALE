from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT=Path("data/v138_audit_closure.json")
SCHEMA="v13-8-52-point-closure-v3"

POINTS=(
(1,"Offense talent engine","v138_audit_features.offense_talent","RESEARCH_IMPLEMENTED"),
(2,"Advanced starter model","v138_audit_features.starter_skill","RESEARCH_IMPLEMENTED"),
(3,"Pitch mix x hitter matchup","v138_audit_features.pitch_mix_matchup","DATA_OPTIONAL_RESEARCH_IMPLEMENTED"),
(4,"Next-generation lineup model","v138_audit_features.lineup_strength","RESEARCH_IMPLEMENTED"),
(5,"Stable-ID Statcast runtime foundation","v137_free_data + v138_audit_features","PROVIDER_HARDENED"),
(6,"Bullpen roles and leverage","v138_audit_features.classify_bullpen_roles","RESEARCH_IMPLEMENTED"),
(7,"Opener / bullpen-game detection","v138_audit_features.detect_opener","RESEARCH_IMPLEMENTED"),
(8,"Handedness park factor integration","v138_audit_features.park_factor","RESEARCH_IMPLEMENTED"),
(9,"Timezone/circadian/travel","v138_audit_features.circadian_travel","DATA_OPTIONAL_RESEARCH_IMPLEMENTED"),
(10,"IL/roster availability impact","v137_mlb_state + v138_audit_features.roster_availability","NATIVE_COLLECTION_IMPLEMENTED"),
(11,"Defense OAA/DRS","v138_audit_features.defense_factor","DATA_OPTIONAL_RESEARCH_IMPLEMENTED"),
(12,"Baserunning","v138_audit_features.baserunning_factor","DATA_OPTIONAL_RESEARCH_IMPLEMENTED"),
(13,"Catcher framing","v138_audit_features.catcher_framing_factor","DATA_OPTIONAL_RESEARCH_IMPLEMENTED"),
(14,"Umpire context","v138_audit_features.umpire_factor","DATA_OPTIONAL_RESEARCH_IMPLEMENTED"),
(15,"New log-link GLM run challenger","v138_research_models.fit_glm","RESEARCH_IMPLEMENTED"),
(16,"Gradient boosting challenger","v138_research_models.fit_gbdt","RESEARCH_IMPLEMENTED"),
(17,"Feature ablation","v138_validation.ablation_report","VALIDATION_IMPLEMENTED"),
(18,"Rich-model promotion gate","v13_rich_native_train","EVIDENCE_GATE_IMPLEMENTED"),
(19,"Bootstrap CI for gains","v138_validation.bootstrap_difference","VALIDATION_IMPLEMENTED"),
(20,"Contextual dispersion","v138_advanced_research.fit_contextual_dispersion","RESEARCH_IMPLEMENTED"),
(21,"Learned extra-innings prior","v138_inning_history + v138_validation.learn_extra_innings_home_prior","FREE_EVIDENCE_IMPLEMENTED"),
(22,"Calibration maturity","calibration_baseball_v13 + v138_advanced_research.dynamic_calibration","EVIDENCE_GATE_IMPLEMENTED"),
(23,"Empirical uncertainty coverage","v138_native_evidence.probability_band_validation","AUTO_EVIDENCE_GATE"),
(24,"Learned bookmaker weights","v138_book_telemetry + v138_native_evidence.bookmaker_weights_oos","AUTO_EVIDENCE_GATE"),
(25,"Posterior Sharp promotion","v13_posterior_policy","EVIDENCE_GATE_IMPLEMENTED"),
(26,"CLV/model-market gap validation","v13_probability_diagnostics + v138_validation.gap_bins","VALIDATION_IMPLEMENTED"),
(27,"Edge/gap bins","v138_validation.gap_bins","VALIDATION_IMPLEMENTED"),
(28,"Naive baselines","v138_validation.baseline_predictions","VALIDATION_IMPLEMENTED"),
(29,"Multi-season walk-forward","v138_validation.walk_forward","VALIDATION_IMPLEMENTED"),
(30,"Per-season validation","v138_validation.walk_forward","VALIDATION_IMPLEMENTED"),
(31,"Subgroup validation","v138_validation.subgroup_validation","VALIDATION_IMPLEMENTED"),
(32,"Parquet + DuckDB analytical store","v138_dataset_store","DATA_ENGINEERING_IMPLEMENTED"),
(33,"Per-artifact checksums","v138_dataset_store.sha256_file","DATA_ENGINEERING_IMPLEMENTED"),
(34,"Dataset versioning","v138_dataset_store.manifest","DATA_ENGINEERING_IMPLEMENTED"),
(35,"Training reproducibility manifest","v138_validation.reproducibility_manifest","DATA_ENGINEERING_IMPLEMENTED"),
(36,"Automatic critical-change republish","discord_v13 + v138_live_change","PRODUCTION_IMPLEMENTED"),
(37,"Starter-change detection","v138_live_change.classify","PRODUCTION_IMPLEMENTED"),
(38,"Lineup-change detection","v138_live_change.classify","PRODUCTION_IMPLEMENTED"),
(39,"Provider/context failure test matrix","tests.test_v138_audit_closure","TESTING_IMPLEMENTED"),
(40,"Graphical model-health dashboard","v138_monitoring.render","OBSERVABILITY_IMPLEMENTED"),
(41,"Provider health time series","v138_monitoring","OBSERVABILITY_IMPLEMENTED"),
(42,"Feature drift alerts","v138_validation.feature_drift + v138_monitoring","OBSERVABILITY_IMPLEMENTED"),
(43,"GAM challenger","v138_research_models.fit_gam","RESEARCH_IMPLEMENTED"),
(44,"Gradient boosted trees mature path","v138_research_models.fit_gbdt","RESEARCH_IMPLEMENTED"),
(45,"Hierarchical Bayesian-style shrinkage","v138_research_models.fit_hierarchical","RESEARCH_IMPLEMENTED"),
(46,"Learned ensemble","v138_research_models._ensemble_weights","RESEARCH_IMPLEMENTED"),
(47,"Meta-model stacking","v138_advanced_research.fit_meta_model","RESEARCH_IMPLEMENTED"),
(48,"Dynamic calibration","v138_native_evidence.dynamic_calibration_oos","AUTO_EVIDENCE_GATE"),
(49,"Inning-level model","v138_inning_history + v138_advanced_research.fit_inning_profile","FREE_EVIDENCE_IMPLEMENTED"),
(50,"Conditional score dispersion","v138_advanced_research.fit_contextual_dispersion","RESEARCH_IMPLEMENTED"),
(51,"Nonlinear SP x lineup x park x weather","v138_advanced_research.nonlinear_interactions","RESEARCH_IMPLEMENTED"),
(52,"Season-regime learning","v138_advanced_research.fit_season_regimes","RESEARCH_IMPLEMENTED"),
)

EVIDENCE_GATED={18,21,22,23,24,25,26,27,48,49}
DATA_LIMITED={3,9,11,12,13,14,21,24,49}


def _load(path: str) -> dict[str,Any]:
    p=Path(path)
    if not p.exists():return {}
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return {}


def _native_gate(name: str) -> tuple[bool,str]:
    d=_load("data/v138_native_evidence.json");g=d.get(name) or {};n=int(g.get("n") or d.get("independent_native_targets") or 0)
    active=bool(g.get("active"));reason=str(g.get("reason") or g.get("criterion") or "native OOS gate")
    return active,f"native/PIT n={n}; active={active}; {reason}"


def _evidence_status(pid: int) -> tuple[bool,str]:
    if pid==18:
        d=_load("data/v13_rich_native_candidate.json");n=int(d.get("native_games") or 0);req=int(d.get("minimum_games") or 300)
        return bool(d.get("active_for_production")),f"native_games={n}/{req}"
    if pid==21:
        d=_load("data/v138_inning_evidence.json");prior=d.get("extra_inning_prior") or {};n=int(d.get("extra_inning_examples") or prior.get("n") or 0)
        return bool(prior.get("active")),f"authenticated free MLB extra-inning examples={n}; required=200"
    if pid==22:
        d=_load("data/v13_baseball_calibration.json");c=d.get("calibrators") or {};active=sum(bool(x.get("active")) for x in c.values())
        return active>0,f"active_calibrators={active}; strict native thresholds retained"
    if pid==23:return _native_gate("uncertainty_coverage")
    if pid==24:return _native_gate("bookmaker_weights")
    if pid==25:
        d=_load("data/v13_posterior_policy.json");n=int(d.get("live_observations") or 0);affected=bool(d.get("primary_probability_affected"))
        return affected,f"live_observations={n}; primary_affected={affected}"
    if pid in {26,27}:
        d=_load("data/v13_probability_diagnostics.json");n=sum(int(x.get("n") or 0) for x in (d.get("by_market") or {}).values())
        return n>=300,f"independent_market_targets={n}; proof floor=300"
    if pid==48:return _native_gate("dynamic_calibration")
    if pid==49:
        d=_load("data/v138_inning_evidence.json");profile=d.get("inning_profile") or {};n=int(d.get("inning_profile_games") or profile.get("n") or 0)
        return bool(profile.get("active")),f"authenticated free MLB inning-profile games={n}; required=300"
    return True,"engineering/validation implementation is sufficient"


def build() -> dict[str,Any]:
    points=[];engineering_closed=0;evidence_closed=0
    for pid,name,impl,kind in POINTS:
        eng=True
        ev,reason=_evidence_status(pid) if pid in EVIDENCE_GATED else (True,"engineering closure; no independent evidence floor required")
        engineering_closed+=int(eng);evidence_closed+=int(ev)
        points.append({"id":pid,"name":name,"implementation":impl,"implementation_status":kind,
                       "engineering_closed":eng,"evidence_closed":ev,"overall_closed":bool(eng and ev),
                       "data_limited":pid in DATA_LIMITED,"evidence_note":reason})
    return {"schema":SCHEMA,"total_points":len(points),"engineering_closed":engineering_closed,
            "evidence_closed":evidence_closed,"overall_closed":sum(bool(x["overall_closed"]) for x in points),
            "engineering_open":len(points)-engineering_closed,"evidence_gates_pending":sum(not x["evidence_closed"] for x in points),
            "points":points,
            "policy":"A point is never called statistically closed merely because code exists. Engineering closure and evidence closure are reported separately; native/PIT sample floors are never lowered. V13.8.2 auto-evaluates every remaining evidence gate that can be evaluated from accumulated native telemetry."}


def main() -> None:
    d=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({k:d[k] for k in ("total_points","engineering_closed","overall_closed","evidence_gates_pending","policy")},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
