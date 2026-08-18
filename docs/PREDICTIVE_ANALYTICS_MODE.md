# Predictive Analytics Mode

## Objective

The production bot is an MLB probability engine first and a betting selector second.

The primary objective is to make announced probabilities as close as possible to the true long-run frequency of the modeled event. A single loss does not invalidate a 65% forecast; calibration is evaluated across many comparable forecasts.

Primary validation metrics are Brier score, LogLoss, calibration/ECE and strict point-in-time integrity. Economic metrics such as executable-price EV, CLV and realized P/L remain secondary diagnostics and must not contaminate the baseball probability.

## Probability products

Every analyzed market preserves separate probability products:

1. `p_baseball_raw`: baseball-only probability before empirical calibration.
2. `p_baseball_calibrated`: baseball-only probability after the current calibration layer.
3. `p_market`: de-vigged sharp-market benchmark.
4. `p_posterior`: market-aware ensemble shadow candidate.
5. `p_predictive_final`: probability shown as the primary predictive output.

For V13.5.2, `p_predictive_final` remains equal to `p_baseball_calibrated`. The posterior cannot enter selection/edge calculations and is not promoted automatically.

## Historical evidence hierarchy

### Tier A — native current-generation observations

A genuine V13.5.2 pregame observation produced live, carrying the exact predictive contract and later settled from the final result. This is the strongest evidence.

### Tier B — exact archived pregame replay

A durable source replay may count toward current baseball calibration when archived HTTP sources reconstruct the exact pregame information state and the row carries the current predictive contract. The probability used for calibration is the frozen pre-candidate baseline, never a candidate layer grading itself.

For RUNLINE/TOTAL markets that can PUSH, `p_replay_baseline_raw` is explicitly the binary probability `P(WIN | no PUSH)`. The PUSH mass is persisted separately. This matches the live engine and is required because Brier/LogLoss training removes PUSH outcomes.

If the replay contains a genuine historical sharp-market snapshot, it may contribute to posterior validation. Missing historical market probabilities are never fabricated.

### Tier C — broad 2026 walk-forward reconstruction

The 1,801-game 2026 reconstruction remains useful for structural research, ablations and diagnostics. It is not relabeled as exact current-generation calibration evidence when the exact current pregame feature/market snapshot was never archived.

### Tier D — older bot probabilities

Old V9/V10/V12/V13 probabilities are benchmarks only.

Native evidence overrides replay evidence when the same `game_pk + phase` exists in both sources.

## Posterior weight learning

The old heuristic/capped Sharp blend is no longer the V13 posterior policy. Candidate weights are learned chronologically from a 0%, 5%, ..., 100% Sharp grid.

Phase-specific evidence is preferred. Market-level evidence can be used as fallback. Weight selection uses prior observations only, and a retained shadow weight must improve both Brier and LogLoss on an untouched chronological holdout. If evidence is insufficient or unstable, the effective posterior weight is 0% Sharp.

This policy affects the shadow posterior only. It does not change `p_predictive_final`.

## Posterior promotion rule

A final game result is shared by its EARLY, LATE and FINAL forecasts, so those phases are correlated observations and must not inflate the promotion sample size.

For each market, pooled promotion evidence now uses **one latest pregame phase per unique game**. EARLY, LATE and FINAL are also reported separately. The all-phase observation count remains diagnostic only.

A posterior can become a review candidate only after:

- at least 300 unique paired games;
- Brier improvement versus calibrated baseball >= 0.001;
- LogLoss improvement versus calibrated baseball >= 0.002.

Historical exact replay and current-generation live evidence are merged, with live evidence overriding a same-game/same-phase replay collision. The broad 1,801-game reconstructed cohort does not count toward the posterior threshold unless exact pregame market evidence exists.

Passing the threshold creates a review candidate; it never silently changes the primary production probability.

## Calibration volume

Exact Tier-B replay baselines can contribute alongside Tier-A native observations. Strict activation floors remain:

- GLOBAL: 600;
- MARKET: 400;
- PHASE/MARKET: 300.

The fitter still requires expanding walk-forward method selection plus an untouched chronological final holdout.

## Structural champion and native challenger

The current structural run model is explicitly a heuristic champion. Its manual coefficients are not retuned from small-sample outcomes.

`v13_rich_native_train.py` is the evidence-driven replacement path for richer starter, platoon, Statcast, bullpen, lineup and weather/park information. Promotion requires at least 300 exact current-generation FINAL games, train-only walk-forward stability and an untouched >=100-game outer holdout. Market probabilities and historical reconstruction are forbidden from promotion evidence.

## Uncertainty output

The displayed range is a **model uncertainty band**, not a validated 90% frequentist confidence interval. The internal nominal 90% scaling is retained for compatibility, while the artifact explicitly records that coverage has not yet been validated.

## API efficiency

The automatic research collector first uses the free MLB schedule to determine whether a new game/phase is missing. The paid Odds API is called only when an uncaptured EARLY/LATE/FINAL phase actually needs analysis.

Closing-market tracking is checkpoint-based: T-60 and close only, with all currently due games batched into a single Odds API request. Repeated 15-minute workflow wake-ups do not imply repeated paid calls.

## Runtime integration safety

V13 currently composes over the mature V12.3 runtime. Every dynamic hook is explicitly marked and checked by `v13_runtime.assert_runtime_hooks()`. A shared critical preflight suite runs in CI, production, research and historical backfill, so architecture drift fails closed instead of silently bypassing V13 logic.

A larger explicit-engine refactor should be separated from predictive changes and performed only after the evidence pipeline is stable.

## Discord output

The main game message is analytics-first. It shows the primary probability, model uncertainty band, raw/calibrated baseball probability, sharp benchmark, learned-weight posterior shadow, calibration status, model-data quality and price context.

Ranking and betting-plan cards remain suppressed in predictive analytics mode.

## Profitability

Accurate probabilities are necessary but do not guarantee profitability. Long-run profitability also requires prices whose break-even probabilities are below the true event probabilities, while accounting for uncertainty, limits, execution quality and variance.
