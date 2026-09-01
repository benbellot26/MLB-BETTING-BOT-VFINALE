# Pulsar V14 — MLB Probability & Decision Engine

Pulsar **V14.6.0** is the active software line.

- Champion generation: **`pulsar-v14-context-v4-all-stats`**
- Probability policy: **`pulsar-v14-probability-policy-v1`**
- Probability schema: **`pulsar-v14-probability-v2`**
- Python contract: **3.12**, standard-library-only V14 core

The source of truth for software/model identity is `v14/__init__.py` plus the champion
manifest. Documentation is not an identity authority.

The betting state is deliberately **not hard-coded in this README**. The authoritative
runtime gate is `data/v14_betting_certification.json`; if certification has not been
earned, candidates remain research-only.

## Production contract

The certifiable chain is intentionally narrow:

`scheduled FINAL acquisition -> frozen baseball probability policy -> executable market -> Pinnacle no-vig benchmark -> immutable paper entry -> PRIMARY/EXECUTION close -> certification -> authorization/staking`

Market prices are post-model data. They may select an executable line, benchmark the
model, calculate edge/CLV and affect decision thresholds, but they are never baseball
predictive features.

## What is frozen

The active champion probability generation is frozen while prospective evidence
accumulates. Research, governance, provenance, dashboards and shadow challengers can
improve without silently retuning production coefficients.

A predictive production change requires:

1. a new explicit generation/policy decision;
2. point-in-time-safe implementation;
3. preregistered evaluation where appropriate;
4. untouched chronological/prospective evidence;
5. comparison on identical games;
6. successful regression, calibration, sharp-benchmark and execution-quality review.

A larger sample is not a magic pass button.

## Evidence model

Pulsar keeps separate concepts separate:

- **prediction quality** — Brier, LogLoss, calibration and run-error diagnostics;
- **sharp benchmark quality** — paired Pinnacle/no-vig evidence;
- **paper/system-authorized evidence** — hypothetical execution under the system contract;
- **real execution** — explicitly recorded external/user execution facts;
- **coverage** — what portion of the actual MLB slate was observable/eligible;
- **research evidence** — challengers, ablations, sensitivity and regime diagnostics.

System-authorized hypothetical ROI must never be presented as realized user ROI.

## Research governance

Experiments are append-only preregistrations. New strict-governance experiments can seal:

- hypothesis and exact feature/model definition;
- train/validation period;
- primary/secondary metrics;
- success rule;
- minimum independent sample;
- analysis plan;
- stopping rule;
- promotion scope;
- code commit;
- multiplicity/research-budget family.

Changing the question after seeing outcomes requires a new experiment id.

See `research/V14_EXPERIMENT_PROTOCOL.md`.

## Sensitivity, baselines, ablations and regimes

The professionalization layer adds read-only research tooling:

- `v14/structural_sensitivity.py` — ±10/20% one-at-a-time coefficient perturbations with
  default parity to the frozen structural champion;
- `v14/research_diagnostics.py` — champion vs 50/50 and sharp baselines, paired bootstrap
  inference, and descriptive regime slices;
- `v14/ablation_shadow.py` — probability counterfactuals with selected information layers
  removed, using only persisted PIT pregame components;
- `v14/ablation_report.py` — only post-registration predictions count toward the sealed
  ablation experiment;
- `v14/champion_dashboard.py` — one read-only dashboard plus daily longitudinal history.

These modules cannot authorize a wager.

## Reproducibility

The V14 Python core currently has **zero third-party runtime dependencies**. A meaningless
empty lockfile is therefore avoided. Instead:

```bash
python -m v14.reproducibility_guard --fail-on-external
```

fails if a third-party import appears. If an external dependency is ever introduced, it
must be declared and deterministically pinned in the same change.

See `REPRODUCIBILITY.md`.

## Architecture boundaries

Production, research/shadow and historical compatibility are separate contracts.
Historical `v11/` code remains where needed for frozen reference construction and rollback
reproducibility; it is not part of the native V14 production prediction path.

See `ARCHITECTURE.md`.

## Point-in-time rules

- predictions must be strictly pregame;
- certifiable betting authorization is FINAL-only under the current timing contract;
- the certifiable entry cohort uses objective `SCHEDULED_FINAL` acquisition;
- historical reconstruction cannot silently become native-live evidence;
- Statcast uses stable identity and strict pre-target cutoff;
- weather uses forecast provenance, never observed post-event conditions;
- missing context fails closed or becomes a documented no-op;
- manual timing cannot replace the scheduled certification cohort.

## Betting / execution rules

A real `BET` path must clear the production gates, including market-specific
certification, executable price, verified freshness, robust lower-bound edge and positive
primary edge against Pinnacle no-vig.

Staking remains independent from prediction research and uses conservative portfolio
caps. Research dashboards do not alter staking.

## Main V14 modules

- `v14/acquisition.py` — MLB/Odds acquisition and event matching.
- `v14/mlb_inputs.py` — native team/starter/lineup/bullpen/environment inputs.
- `v14/structural.py`, `v14/run_stack.py` — structural run construction.
- `v14/context_overlay.py`, `v14/all_stats_context.py` — bounded residual context.
- `v14/distribution.py` — coherent ML/RL/total score distribution.
- `v14/probability_calibration.py` — calibration research under explicit policy control.
- `v14/uncertainty.py` — decision-safety intervals.
- `v14/sharp_market.py`, `v14/execution_market.py` — post-model market state.
- `v14/decision.py` — fail-closed candidate decision diagnostics.
- `v14/staking.py` — bankroll/exposure controls.
- `v14/tracking.py` — prediction ledger, settlement and performance.
- `v14/certification.py` — authoritative betting certification.
- `v14/research_registry.py`, `v14/promotion_guard.py` — research governance.
- `v14/data_quality_dashboard.py` — source/coverage health.
- `v14/champion_dashboard.py` — longitudinal read-only champion dashboard.
- `v14/preflight.py` — production/governance regression gate.

## Active workflows

- `mlb-bot.yml` — native V14 production/scheduled acquisition.
- `v14-performance.yml` — settlement, evidence refresh and shadow research.
- `v14-close-capture.yml` — PRIMARY/EXECUTION close capture.
- `v14-statcast-refresh.yml` — PIT Statcast refresh.
- `v14-reference-data-smoke.yml` — provider/reference checks.
- `v14-ci.yml` — V14 regression and PIT/provider smoke suite.
- `v14-production-workflow-guard.yml` — production workflow change guard.

Mutable runtime evidence is isolated through the runtime-data state branch rather than
being treated as normal source code.

## Common commands

```bash
python -m py_compile v14/*.py
python -m v14.reproducibility_guard --fail-on-external
python -m v14.preflight
python -m unittest discover -s tests -p 'test_v14_*.py' -v

python -m v14.production_runtime --target-date YYYY-MM-DD
python -m v14.tracking settle
python -m v14.research_diagnostics
python -m v14.ablation_report
python -m v14.champion_dashboard
```

## Change policy

Do not modify the champion merely to create more bets or to chase a recent result.
Collect prospective evidence under the frozen policy, improve measurement and research
in shadow, and promote only changes that earn it on untouched data.
