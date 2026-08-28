# Pulsar V14 professionalization contract

This document describes the current V14 production/research boundary. Earlier V12/V13 implementation notes remain available in Git history and the pre-cleanup archive branch; they are no longer the operational contract for `main`.

## 1. Champion probability isolation

The production champion is `pulsar-v14-context-v3`. Governance, tracking, certification, market and data-pipeline hardening must not silently mutate champion probability code. `v14/champion_manifest.py` fingerprints the champion source set and the preflight fails on unauthorized mutation.

## 2. Exact evidence identity

Certification-facing evidence is accepted only when it matches both:

- `MODEL_GENERATION = pulsar-v14-context-v3`
- `PROBABILITY_POLICY_ID = pulsar-v14-probability-policy-v1`

Calibration, performance and paper-CLV evidence are all bound to this identity. Missing/old policy rows are excluded rather than relabeled.

## 3. Strict point-in-time discipline

Every prediction used for evaluation is strictly pregame. Historical reconstructed data declares its reconstruction mode and cannot masquerade as native-live evidence. Provider timestamps, cutoffs and dataset hashes are retained where applicable.

For market execution, a real `BET` requires a verifiable Odds event start time; unverified timestamp states remain research-only.

## 4. Probability quality before ROI

Model quality is judged with proper scoring rules first:

- Brier Score;
- Log Loss;
- calibration/ECE;
- paired model-vs-sharp score differences;
- run MAE diagnostics;
- rolling drift slices.

Short-term win/loss streaks are diagnostic context, not model-selection evidence.

## 5. Calibration and uncertainty

Calibration uses chronological train/holdout separation. A transform can activate only after paired OOS improvement; raw identity can be accepted when the untouched holdout is already calibrated.

Probability intervals are empirical decision-safety bands, not fabricated Bayesian credible intervals. Their provenance and any fallback penalty are explicit.

## 6. Market separation

Bookmaker/market probabilities never enter the baseball champion as predictive features. Market data is used after prediction for:

- canonical line selection;
- line shopping;
- no-vig sharp consensus;
- model/sharp divergence diagnostics;
- executable breakeven probability;
- CLV capture;
- decision thresholds.

Sharp consensus and execution prices are separate concepts.

## 7. Certification is market-specific

Software can be production-ready while betting remains `RESEARCH_ONLY`. Betting certification requires current-policy probability evidence, calibration acceptance, paired sharp evidence, drift control, fresh prospective paper CLV and same-book close evidence.

No historical artifact alone can authorize a real betting market.

## 8. Ledger boundaries

Three ledgers/roles are intentionally separate:

1. **Prediction tracking** — evaluates the probability engine.
2. **Paper/system-authorized evidence** — records prospective immutable research/authorization decisions and closes.
3. **Real execution** — requires explicit execution facts and is never inferred from a model recommendation.

This prevents theoretical system ROI from being reported as realized user ROI.

## 9. Data-enrichment policy

V14 aggressively collects candidate data while keeping it shadow-only until validated. Current research layers include:

- stable-ID Statcast priors;
- hitter pitch-type splits;
- hitter splits by opposing pitcher hand;
- pitcher splits by batter side;
- pitch mix and velocity;
- starter recent workload;
- bullpen availability/fatigue;
- defense/baserunning;
- venue/park physics;
- point-in-time weather;
- historical team-run and distribution challengers.

No batter-vs-pitcher head-to-head feature is promoted simply because it is available; noisy dimensions must demonstrate OOS value.

## 10. Statcast V14-native boundary

The current Statcast research path uses V14-native provider, deduplication and aggregation primitives. Raw pitch rows are stable-ID keyed, deduplicated and constrained to `game_date < cutoff`. Enriched artifacts remain `champion_impact = false` and `auto_activation = false`.

## 11. Repository governance

V14 has its own regression/PIT/provider CI. Frozen V11/V13 regression work is path-scoped and should run only when the legacy data foundation is touched. Obsolete workflows and docs should be removed from the active tree rather than kept as misleading operational guidance; Git history and the archive branch preserve reproducibility.

## 12. Promotion rule

A challenger may be considered for a future probability generation only after strict paired OOS evidence on identical games, with untouched chronological validation and no target leakage. A candidate must improve probability quality without unacceptable market-specific regression. Promotion is explicit and never automatic.
