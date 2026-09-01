# Pulsar V14 professionalization contract

This document describes the active production/research boundary for **V14.6.0**.

Source-of-truth identity:

- `MODEL_GENERATION = pulsar-v14-context-v4-all-stats`
- `PROBABILITY_POLICY_ID = pulsar-v14-probability-policy-v1`
- `SCHEMA = pulsar-v14-probability-v2`

`v14/__init__.py` and the champion manifest are authoritative; documentation is not.

## 1. Champion isolation

Governance, tracking, certification, dashboards and research tooling must not silently
mutate champion probability behavior. Predictive changes require an explicit new
generation/policy decision and new validation.

## 2. Exact evidence identity

Certification-facing evidence must match the exact generation and probability policy.
Missing, historical or stale-policy observations are excluded rather than relabeled.

## 3. Strict point-in-time discipline

Every scored prediction is strictly pregame. Historical reconstruction declares its mode
and cannot masquerade as native-live evidence. Provider timestamps, cutoffs, stable
identity and provenance are retained where available.

## 4. Probability quality before ROI

Model quality is judged first with proper scoring and calibration:

- Brier;
- LogLoss;
- ECE/reliability;
- paired model-vs-sharp differences;
- confidence intervals;
- run-error diagnostics;
- temporal/regime stability.

Short-term W/L and ROI are never sufficient model-selection evidence.

## 5. Sample size is not certification

Minimum sample thresholds are necessary context, not a pass button. Betting/promotion
claims must combine sample size with calibration, proper scores, paired sharp comparison,
prospective CLV where relevant, drift/regime stability and execution quality.

## 6. Calibration and uncertainty

Calibration uses chronological/OOS separation and explicit policy identity. Uncertainty
bands are decision-safety intervals with explicit provenance, not invented certainty.

## 7. Market separation

Market probability never enters the baseball champion as a predictive feature. Market
data is post-model and may be used for line selection, line shopping, no-vig sharp
benchmarking, divergence, breakeven, CLV and decision thresholds.

## 8. Certification is market-specific

Software production readiness and betting certification are separate. The authoritative
betting state is `data/v14_betting_certification.json`; dashboards cannot override it.

## 9. Ledger boundaries

Prediction tracking, paper/system-authorized hypothetical execution and real external
execution remain separate. Hypothetical system ROI must never be reported as realized
user ROI.

## 10. Research preregistration

The registry is append-only. Existing registrations are preserved exactly. New
strict-governance experiments can additionally seal:

- minimum independent games;
- analysis plan;
- stopping rule;
- promotion scope;
- multiplicity/research-budget family;
- immutable spec fingerprint.

A change after looking at prospective outcomes requires a new experiment id.

## 11. Ablation and simplification

`V14-ABLATION-01` prospectively asks whether starter residuals, lineup residuals, bullpen
residuals, weather, advanced Statcast, defense, timezone and environment physics actually
add information. Counterfactuals use only persisted pregame PIT components and no market
probability.

Only post-registration predictions count toward promotion/simplification evidence.

## 12. Structural sensitivity

`v14/structural_sensitivity.py` reproduces the default structural champion in a shadow
parameterization and perturbs hand-authored weights ±10/20%. Its purpose is robustness
diagnosis, not automatic retuning.

## 13. Baselines and regimes

`v14/research_diagnostics.py` permanently reports simple 50/50 and available sharp
baselines on identical games, plus descriptive temporal/favorite/run-environment slices.
Regime slices generate hypotheses; they do not become post-hoc production rules.

## 14. Reproducibility

The V14 Python core is standard-library only under Python 3.12. `pyproject.toml` declares
the runtime contract and `v14.reproducibility_guard` fails on undeclared third-party
imports. If a third-party package is introduced, a deterministic lock/constraints policy
must be added in the same change.

## 15. Longitudinal dashboard

`v14/champion_dashboard.py` aggregates performance, certification, sharp, coverage,
data-quality, paper/authorization and research evidence, then stores one canonical daily
history snapshot. It is read-only and non-authoritative for betting.

## 16. Architecture boundary

V14 production, V14 research/shadow and historical compatibility are distinct logical
zones. Historical code remains only where needed for frozen reference/parity/rollback
work; destructive file moves are avoided when they would increase risk.

See `ARCHITECTURE.md`.

## 17. Promotion rule

A challenger can be nominated only after its declared OOS/prospective evidence is
satisfied on identical games. Promotion is explicit, generation-bound and never
automatic. Lowering thresholds merely to manufacture more bets is not a valid
professionalization step.
