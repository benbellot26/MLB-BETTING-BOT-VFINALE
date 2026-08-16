# V13 Professional Probability Contract

V13 changes the primary product from pick selection to calibrated pregame probability estimation.

## Core contract

For every analyzed market V13 keeps four quantities separate:

- `p_baseball_raw`: probability produced from baseball-only information available before the game.
- `p_baseball_calibrated`: calibration of the baseball-only model, fitted only on historical baseball-only predictions.
- `p_market`: point-in-time de-vig sharp-market probability. It is a benchmark, never an input to `p_baseball_raw` or `p_baseball_calibrated`.
- `p_posterior`: optional forecasting blend of calibrated baseball and market probabilities. It is never used to claim model-vs-market edge.

Official edge/value diagnostics are computed from `p_baseball_calibrated` versus an independent fresh market quote. The selector must not use `p_posterior` for value discovery.

## Predictive contract versioning

Software releases no longer define training compatibility. Training rows are compatible when all predictive contracts match:

- feature contract
- target contract
- baseball probability contract
- calibration contract

Discord, CI, selector, delivery and other non-predictive changes may change software version without invalidating predictive history.

## Point-in-time invariant

Every feature builder receives an explicit `as_of`. A training row is rejected when:

- `analyzed_at >= game_date`;
- a source snapshot was recorded after `analyzed_at`;
- a feature declares no point-in-time provenance;
- reconstructed lineup identity came from a postgame boxscore;
- a season aggregate lacks a historical cutoff/snapshot.

Live runs can use current MLB season aggregates because current time is the requested `as_of`; historical reconstruction must use stored snapshots or explicitly cutoff-capable sources.

## Probability output

The primary report for each option is:

- calibrated baseball probability;
- empirical uncertainty interval;
- raw baseball probability;
- sharp de-vig probability;
- model-market gap in percentage points;
- push probability when applicable;
- provenance, phase and calibration sample size.

Recommendation/staking logic is downstream and optional. A probability report remains valid when no executable price exists.

## Validation policy

A predictive change may not be promoted from shadow to champion on a small single holdout. Promotion requires:

1. minimum 600 compatible games overall;
2. at least 200 untouched outer-holdout games;
3. at least 5 calendar-day-block walk-forward windows;
4. paired bootstrap confidence interval for Brier improvement with lower bound > 0;
5. non-negative LogLoss improvement;
6. no market with >=100 observations regressing by more than 0.002 Brier;
7. calibration slope/intercept and ECE within configured safety bounds;
8. frozen test set used for reporting only, never hyperparameter selection.

## Historical data policy

Legacy 1,801-game rows are valuable only when their feature values can be rebuilt point-in-time under the current predictive contract. They may be migrated into the new contract if the migration is deterministic, baseball-only, and does not use future/postgame information. Otherwise they remain diagnostic and never train production probabilities.

## V12.4 policy

V12.4 modules remain shadow-only. A module receives production weight only after positive paired out-of-sample evidence. A zero learned weight is an acceptable and preferred result when the feature family does not improve calibrated probability quality.

## Architecture direction

The runtime path is explicitly:

`PregameSnapshot -> BaseballFeatureBuilder -> BaseballProbabilityModel -> ScoreDistribution -> BaseballCalibrator -> MarketBenchmark -> ProbabilityReport`

Market blending and betting selection are separate downstream consumers. This removes the circularity where a sharp price influences the probability later compared against a sharp price.
