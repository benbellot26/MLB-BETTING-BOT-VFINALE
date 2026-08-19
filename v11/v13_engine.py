from __future__ import annotations

import math
from typing import Any, Callable

from . import config, core, data_quality, engine_v12 as base_engine, market, methodology_v123, pro_model
from . import extra_innings_v13, v13_distribution_prior, v13_park_runtime, v13_probability_surface
from . import v13_rich_run_shadow, v13_run_mean_runtime
from .pipeline_v13 import ProbabilityPipelineV13
from .probability_contract_v13 import (
    MODEL_GENERATION_FINGERPRINT,
    PREDICTIVE_CONTRACT_VERSION,
    assert_no_market_leakage,
)

VERSION = "13.10-deep-audit-hardening-v1"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _norm(value: Any) -> str:
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _option_key(option: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(option.get("market") or "").upper(),
        _norm(option.get("name")),
        str(option.get("point")),
    )


class V13Engine:
    """Explicit V13 orchestration over the mature V12.3 baseball primitives.

    V12.3 still supplies structural/data primitives and research shadows. V13
    owns the current-generation prior, park, distribution, extra-innings,
    calibration and probability-surface contracts without monkey-patching the
    underlying engine globals.
    """

    version = VERSION
    architecture = "explicit-composition"

    def __init__(
        self,
        base_analyze: Callable[..., dict[str, Any]] | None = None,
        pipeline: ProbabilityPipelineV13 | None = None,
    ) -> None:
        self._base_analyze = base_analyze or base_engine.analyze
        self._pipeline = pipeline

    @staticmethod
    def joint_score_matrix(*args, **kwargs):
        return base_engine.joint_score_matrix(*args, **kwargs)

    @staticmethod
    def prob_cover_parts(*args, **kwargs):
        return base_engine.prob_cover_parts(*args, **kwargs)

    @staticmethod
    def prob_total_parts(*args, **kwargs):
        return base_engine.prob_total_parts(*args, **kwargs)

    @staticmethod
    def prob_home_win(home_mu, away_mu, dispersion=None, env_sigma=None):
        joint = base_engine.joint_score_matrix(
            home_mu,
            away_mu,
            dispersion=dispersion,
            env_sigma=env_sigma,
        )
        prior, _meta = extra_innings_v13.validated_home_prior()
        return extra_innings_v13.home_win_probability(joint, extra_innings_home_prior=prior)

    @staticmethod
    def _validated_historical_priors(
        structural_hmu: float,
        structural_amu: float,
        champion: dict[str, Any],
        phase: str,
    ) -> tuple[Any, ...]:
        """Compose V13 candidate priors without replacing V12.3 functions."""
        values = list(methodology_v123.bootstrap_prior_v123(structural_hmu, structural_amu, champion, phase))
        phase_name = str(phase or "EARLY").upper()
        phase_model = ((champion.get("phase_models") or {}).get(phase_name) or {})
        native_residual_active = bool(
            champion.get("active") and (phase_model.get("residual") or {}).get("active")
        )

        validation_meta = dict(values[2] or {})
        validation_meta.update(
            {
                "v13_validation_baseline_home_mu": values[0],
                "v13_validation_baseline_away_mu": values[1],
                "v13_validation_baseline_dispersion": values[4],
                "v13_validation_baseline_environment_sigma": values[6],
                "v13_validation_model_generation": MODEL_GENERATION_FINGERPRINT,
                "v13_validation_baseline_source": "v123-compose-runtime-pre-v13-candidate",
            }
        )
        values[2] = validation_meta
        legacy_run_prior_active = bool(validation_meta.get("active"))

        if phase_name == "FINAL" and not native_residual_active and not legacy_run_prior_active:
            hmu, amu, mean_meta = v13_run_mean_runtime.apply_pair(values[0], values[1], phase_name)
            if mean_meta.get("active"):
                values[0], values[1] = hmu, amu
                bootstrap = dict(values[3] or {})
                bootstrap["v13_run_mean_prior"] = mean_meta
                values[3] = bootstrap

        dispersion, env_sigma, dist_meta = v13_distribution_prior.apply(values[4], values[6], phase_name)
        if dist_meta.get("active"):
            values[4] = dispersion
            values[5] = dist_meta.get("source")
            values[6] = env_sigma
            bootstrap = dict(values[3] or {})
            bootstrap["v13_distribution_prior"] = dist_meta
            values[3] = bootstrap
        return tuple(values)

    def _apply_v13_run_stack(self, result: dict[str, Any]) -> dict[str, Any]:
        phase = str(result.get("phase") or "EARLY").upper()
        shmu = result.get("structural_hmu")
        samu = result.get("structural_amu")
        if shmu is None or samu is None:
            raise ValueError("V13Engine requires structural_hmu/structural_amu from V12.3")

        # Replace the legacy static park multiplier only when a leakage-safe
        # prior-season venue factor exists. Missing/invalid priors retain the
        # established static baseline exactly.
        shmu, samu, park_meta = v13_park_runtime.apply(result, float(shmu), float(samu))
        result["structural_hmu"] = shmu
        result["structural_amu"] = samu

        champion = pro_model.load_model()
        values = self._validated_historical_priors(float(shmu), float(samu), champion, phase)
        prior_hmu, prior_amu = float(values[0]), float(values[1])
        validation_meta = dict(values[2] or {})
        bootstrap = dict(values[3] or {})
        dispersion = float(values[4])
        dispersion_source = values[5]
        env_sigma = float(values[6])
        env_source = values[7]

        result_like = {
            "features": result.get("features") or {},
            "ctx": result.get("ctx") or {},
            "phase": phase,
        }
        home_mu, away_mu, learned = pro_model.apply_run_correction(
            prior_hmu,
            prior_amu,
            result_like,
            champion,
            phase,
        )

        features = dict(result.get("features") or {})
        previous_bootstrap = dict(features.get("historical_bootstrap") or {})
        previous_bootstrap.update(
            {
                "active": bool(bootstrap.get("active")),
                "status": bootstrap.get("status"),
                "version": bootstrap.get("version"),
                "run_prior": validation_meta,
                "prior_home_mu": prior_hmu,
                "prior_away_mu": prior_amu,
            }
        )
        if bootstrap.get("v13_run_mean_prior") is not None:
            previous_bootstrap["v13_run_mean_prior"] = bootstrap.get("v13_run_mean_prior")
        if bootstrap.get("v13_distribution_prior") is not None:
            previous_bootstrap["v13_distribution_prior"] = bootstrap.get("v13_distribution_prior")
        extra_prior, extra_meta = extra_innings_v13.validated_home_prior()
        features.update(
            {
                "historical_bootstrap": previous_bootstrap,
                "home_mu": home_mu,
                "away_mu": away_mu,
                "learned_run_adjustment": learned,
                "run_dispersion": dispersion,
                "dispersion_source": dispersion_source,
                "run_environment_sigma": env_sigma,
                "run_environment_source": env_source,
                "distribution": "correlated-negative-binomial-mixture",
                "v13_engine_architecture": self.architecture,
                "park_factor_runtime": park_meta,
                "park_factor": park_meta.get("factor"),
                "extra_innings_prior": extra_meta,
                "extra_innings_home_probability": extra_prior,
            }
        )

        result["features"] = features
        result["hmu"] = home_mu
        result["amu"] = away_mu
        result["model"] = dict(result.get("model") or {})
        result["model"].update(
            {
                "version": champion.get("version", result["model"].get("version")),
                "active": bool(champion.get("active")),
                "dispersion": dispersion,
                "environment_sigma": env_sigma,
            }
        )
        result["v13_validation_baseline"] = {
            "home_mu": validation_meta.get("v13_validation_baseline_home_mu"),
            "away_mu": validation_meta.get("v13_validation_baseline_away_mu"),
            "dispersion": validation_meta.get("v13_validation_baseline_dispersion"),
            "environment_sigma": validation_meta.get("v13_validation_baseline_environment_sigma"),
            "model_generation": validation_meta.get("v13_validation_model_generation"),
            "source": validation_meta.get("v13_validation_baseline_source"),
        }
        result["v13_validation_baseline_ready"] = (
            all(
                result["v13_validation_baseline"].get(key) is not None
                for key in ("home_mu", "away_mu", "dispersion", "environment_sigma")
            )
            and result["v13_validation_baseline"].get("model_generation") == MODEL_GENERATION_FINGERPRINT
        )
        return result

    def _recompute_existing_baseball_options(self, result: dict[str, Any]) -> None:
        home = str((result.get("ctx") or {}).get("home") or "")
        hmu, amu = float(result["hmu"]), float(result["amu"])
        shmu, samu = float(result["structural_hmu"]), float(result["structural_amu"])
        dispersion = _num((result.get("features") or {}).get("run_dispersion"), config.RUN_DISPERSION)
        env_sigma = _num((result.get("features") or {}).get("run_environment_sigma"), config.RUN_ENV_SIGMA)
        home_ml = self.prob_home_win(hmu, amu, dispersion, env_sigma)
        structural_home_ml = self.prob_home_win(shmu, samu, config.RUN_DISPERSION, config.RUN_ENV_SIGMA)

        for option in result.get("options") or []:
            market_name = str(option.get("market") or "").upper()
            name = str(option.get("name") or "")
            push = structural_push = 0.0
            probability = structural_probability = None
            if market_name == "ML":
                is_home = _norm(name) == _norm(home)
                probability = home_ml if is_home else 1.0 - home_ml
                structural_probability = structural_home_ml if is_home else 1.0 - structural_home_ml
            elif market_name == "RUNLINE" and option.get("point") is not None:
                side = "home" if _norm(name) == _norm(home) else "away"
                structural_win, structural_push = base_engine.prob_cover_parts(
                    shmu, samu, side, _num(option.get("point")), config.RUN_DISPERSION, config.RUN_ENV_SIGMA
                )
                win, push = base_engine.prob_cover_parts(
                    hmu, amu, side, _num(option.get("point")), dispersion, env_sigma
                )
                structural_probability = structural_win / max(1e-9, 1.0 - structural_push)
                probability = win / max(1e-9, 1.0 - push)
            elif market_name == "TOTAL" and option.get("point") is not None:
                side = str(name).lower()
                if side in {"over", "under"}:
                    structural_win, structural_push = base_engine.prob_total_parts(
                        shmu, samu, side, _num(option.get("point")), config.RUN_DISPERSION, config.RUN_ENV_SIGMA
                    )
                    win, push = base_engine.prob_total_parts(
                        hmu, amu, side, _num(option.get("point")), dispersion, env_sigma
                    )
                    structural_probability = structural_win / max(1e-9, 1.0 - structural_push)
                    probability = win / max(1e-9, 1.0 - push)
            if probability is None:
                continue
            if structural_probability is not None:
                option["p_structural"] = round(core.clamp(structural_probability), 6)
            option["p_learned"] = round(core.clamp(probability), 6)
            option["p_push_model"] = round(max(0.0, min(1.0, push)), 6)

    def _ensure_standard_runlines(self, result: dict[str, Any]) -> None:
        """Guarantee both standard +/-1.5 pairs without mutating V12 globals."""
        ctx = result.get("ctx") or {}
        home = str(ctx.get("home") or "")
        away = str(ctx.get("away") or "")
        if not home or not away:
            return
        existing = {_option_key(option) for option in result.get("options") or []}
        event = result.get("event") or {}
        as_of = result.get("as_of")
        quality = _num(result.get("quality"), 0.5)
        phase = str(result.get("phase") or "EARLY").upper()
        hmu, amu = float(result["hmu"]), float(result["amu"])
        shmu, samu = float(result["structural_hmu"]), float(result["structural_amu"])
        dispersion = _num((result.get("features") or {}).get("run_dispersion"), config.RUN_DISPERSION)
        env_sigma = _num((result.get("features") or {}).get("run_environment_sigma"), config.RUN_ENV_SIGMA)
        canonical = (result.get("canonical_lines") or {}).get("RUNLINE")
        champion = pro_model.load_model()

        for home_point in (-1.5, 1.5):
            for name, side, point in (
                (home, "home", home_point),
                (away, "away", -home_point),
            ):
                key = ("RUNLINE", _norm(name), str(point))
                if key in existing:
                    continue
                structural_win, structural_push = base_engine.prob_cover_parts(
                    shmu,
                    samu,
                    side,
                    point,
                    config.RUN_DISPERSION,
                    config.RUN_ENV_SIGMA,
                )
                learned_win, learned_push = base_engine.prob_cover_parts(
                    hmu,
                    amu,
                    side,
                    point,
                    dispersion,
                    env_sigma,
                )
                p_structural = structural_win / max(1e-9, 1.0 - structural_push)
                p_learned = learned_win / max(1e-9, 1.0 - learned_push)
                sharp = market.sharp_consensus(event, "RUNLINE", name, point, as_of=as_of)
                price = core.winamax_price(event, "RUNLINE", name, point)
                uncertainty = pro_model.model_uncertainty(
                    "RUNLINE",
                    p_learned,
                    phase,
                    sharp.get("dispersion"),
                    1.0,
                    champion,
                )
                result.setdefault("options", []).append(
                    {
                        "market": "RUNLINE",
                        "name": name,
                        "point": point,
                        "is_canonical_line": canonical is not None and abs(_num(canonical) - point) <= 1e-6,
                        "line_source": "v13-standard-1.5",
                        "execution_available": bool(price and price > 1),
                        "p_structural": round(core.clamp(p_structural), 6),
                        "p_learned": round(core.clamp(p_learned), 6),
                        "p_model": round(core.clamp(p_learned), 6),
                        "p_effective": round(core.clamp(p_learned), 6),
                        "p_win": round(learned_win, 6),
                        "p_push": round(learned_push, 6),
                        "p_push_model": round(learned_push, 6),
                        "p_market": round(float(sharp["p"]), 6) if sharp.get("p") is not None else None,
                        "refs": int(sharp.get("n") or 0),
                        "sharp_books": sharp.get("books", []),
                        "sharp_weight": 0.0,
                        "sharp_dispersion": sharp.get("dispersion"),
                        "sharp_robustness": sharp.get("robustness"),
                        "sharp_max_age_min": sharp.get("max_age_min"),
                        "sharp_effective_n": sharp.get("effective_n"),
                        "quality": quality,
                        "model_uncertainty": round(_num(uncertainty), 6),
                        "calibration_source": "v13-baseball-only",
                        "phase_model": phase,
                        "winamax_eval": {
                            "price": price,
                            "official_selected": False,
                            "official_units": 0,
                        },
                    }
                )
                existing.add(key)

    def _apply_probability_contract(self, result: dict[str, Any]) -> dict[str, Any]:
        pipeline = self._pipeline or ProbabilityPipelineV13.from_artifact()
        phase = str(result.get("phase") or "EARLY").upper()
        dq = result.get("data_quality") if isinstance(result.get("data_quality"), dict) else data_quality.assess(result)
        result["data_quality"] = dq
        dq_score = max(0.0, min(1.0, _num(dq.get("model_input_score", dq.get("score")), 1.0)))
        for option in result.get("options") or []:
            try:
                legacy_effective = option.get("p_effective")
                pipeline.transform_option(option, phase, data_quality=dq_score)
                option["p_legacy_market_blended"] = legacy_effective
                calibrated = float(option["p_baseball_calibrated"])
                raw = float(option["p_baseball_raw"])
                push = max(0.0, min(0.35, _num(option.get("p_push_model", option.get("p_push")), 0.0)))
                option["p_effective"] = round(calibrated, 6)
                option["p_model"] = round(raw, 6)
                option["p_win"] = round(calibrated * (1.0 - push), 6)
                option["p_push"] = round(push, 6)
                option["p_predictive_final"] = round(calibrated, 6)
                option["predictive_final_source"] = "baseball_calibrated"
                option["predictive_final_status"] = "BASEBALL_PRIMARY_POSTERIOR_SHADOW"
                option["probability_product"] = "calibrated-baseball-only"
                option["edge_probability_field"] = "p_baseball_calibrated"
                option["posterior_allowed_for_edge"] = False
                assert_no_market_leakage(option)
            except Exception as exc:
                option["v13_probability_error"] = f"{type(exc).__name__}:{exc}"
                option["v13_probability_eligible"] = False

        surface = v13_probability_surface.reconcile(result)
        result["probability_surface_valid"] = bool(surface.get("valid"))
        result["probability_surface_display_complete"] = bool(surface.get("display_complete"))
        if not surface.get("valid"):
            error = "surface:" + ",".join(surface.get("errors") or [])
            for option in result.get("options") or []:
                option["v13_probability_error"] = option.get("v13_probability_error") or error
                option["v13_probability_eligible"] = False

        hm = next(
            (
                option
                for option in result.get("options") or []
                if str(option.get("market") or "").upper() == "ML"
                and _norm(option.get("name")) == _norm((result.get("ctx") or {}).get("home"))
            ),
            None,
        )
        if hm and hm.get("p_baseball_calibrated") is not None:
            result["p_home"] = hm["p_baseball_calibrated"]
        result["software_version"] = VERSION
        result["engine_version"] = VERSION
        result["v13_engine"] = {
            "architecture": self.architecture,
            "base_engine": "V12.3 compatibility primitives",
            "global_engine_monkeypatches_required": False,
        }
        result["probability_contract_version"] = PREDICTIVE_CONTRACT_VERSION
        result["model_generation"] = MODEL_GENERATION_FINGERPRINT
        result["probability_product"] = "baseball-only-calibrated"
        result["predictive_analytics_mode"] = True
        result["primary_probability_field"] = "p_predictive_final"
        result["posterior_role"] = "shadow_candidate_until_unique_game_out_of_sample_validation"
        result["market_blend_allowed_for_edge"] = False
        result["market_blend_allowed_for_forecast_only"] = True
        result["probability_pipeline"] = (
            "PregameSnapshot->V12.3StructuralBase->PriorParkFactor->V13RunStack->"
            "ScoreDistribution->ValidatedExtraInnings->BaseballCalibration->"
            "ComplementReconciliation->ValidatedPosteriorShadow"
        )
        return result

    def analyze(self, game: dict[str, Any], event: dict[str, Any], as_of=None) -> dict[str, Any]:
        result = self._base_analyze(game, event, as_of=as_of)
        self._apply_v13_run_stack(result)
        self._recompute_existing_baseball_options(result)
        self._ensure_standard_runlines(result)

        before = bool((result.get("shadow_v124") or {}).get("modules"))
        v13_rich_run_shadow.attach(result)
        result["v13_shadow_chain"] = {
            "v124_modules_before_rich": before,
            "rich_status": (result.get("shadow_v13_rich_runs") or {}).get("status"),
            "affects_probability": False,
        }
        return self._apply_probability_contract(result)
