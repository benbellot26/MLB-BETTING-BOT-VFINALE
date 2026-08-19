# MLB Betting Bot — V13 Predictive Analytics

V13 is probability-first. Its primary objective is to estimate MLB event probabilities as accurately as possible; betting/execution information is secondary and must never leak into the baseball probability.

The software version may advance for engineering work without silently changing the predictive evidence generation. Model-generation compatibility is governed separately by the frozen probability-contract fingerprint.

## Current production contract

The displayed probability products are deliberately separate:

1. `p_baseball_raw` — market-independent baseball probability before V13 calibration.
2. `p_baseball_calibrated` — baseball-only calibrated probability.
3. `p_market` — de-vig sharp-market consensus, used as a benchmark.
4. `p_posterior` — market-aware shadow challenger. Its Sharp weight is learned chronologically from prior evidence; insufficient evidence means 0% Sharp.
5. `p_predictive_final` — production primary probability. It remains `p_baseball_calibrated` until a posterior challenger passes the promotion protocol.

The posterior is not allowed to enter the edge/selection probability before promotion.

## Point-in-time evidence

Production and research runs can archive every HTTP response consumed by the model. Historical replay uses the recorded `as_of`; final MLB scores are fetched later and are labels only.

Exact archived replays are eligible for current-generation research only when they contain the frozen pre-candidate V13 validation baseline and the exact current model-generation fingerprint.

For RUNLINE/TOTAL markets with a possible PUSH, binary calibration and Brier/LogLoss use:

`P(WIN | no PUSH) = P(WIN) / (1 - P(PUSH))`

The push mass is stored separately. This is identical to the live probability semantics and prevents integer-total/runline backtests from being biased by dropping PUSH outcomes without conditioning the probability.

The broad reconstructed cohort remains a research/ablation benchmark. It is not mislabeled as native current-generation calibration evidence when exact pregame inputs were not archived.

## Calibration

Baseball calibration is baseball-only. Sportsbook probabilities are forbidden as calibration features.

Strict V13 activation floors are intentionally higher than the internal fitter thresholds:

- GLOBAL: 600 observations;
- per market: 400 unique game-market targets;
- per phase/market: 300 game-phase-market targets.

Method selection uses expanding chronological walk-forward validation plus an untouched final chronological holdout. If calibration evidence is insufficient or unstable, the identity transform remains active.

## Posterior market challenger

`v11/v13_posterior_policy.py` replaces the old fixed/heuristic market-blend cap with an evidence-driven shadow policy.

Candidate Sharp weights are searched from 0% to 100% in 5-point increments. Selection is chronological; phase-specific evidence is preferred and market-level evidence is only a fallback. A candidate weight is retained for shadow use only if its untouched holdout improves both Brier and LogLoss. Otherwise its effective Sharp weight is 0%.

Production promotion requires at least **300 unique games**, not 300 EARLY/LATE/FINAL observations. The pooled promotion comparison keeps one latest pregame phase per game. EARLY, LATE and FINAL are also scored separately so phase behavior cannot be hidden by an aggregate.

Promotion thresholds remain:

- at least 300 unique paired games;
- Brier improvement >= 0.001;
- LogLoss improvement >= 0.002;
- explicit review before changing `p_predictive_final`.

No automatic promotion is performed by the daily post-mortem.

## Baseball model champion/challenger

The current structural baseball model is explicitly treated as a **heuristic champion**, not as the theoretical ceiling. It contains interpretable manual weights for team offense, starters, opponent pitching, park, travel/fatigue and bullpen context.

Those coefficients must not be hand-retuned simply because a small recent sample looks favorable. The evidence-driven replacement path is `v11/v13_rich_native_train.py`, which evaluates native point-in-time modules such as starter IP, platoon, Statcast, bullpen player state, lineup player state and weather/park effects.

A rich/native challenger requires:

- at least 300 exact current-contract FINAL games;
- train-only chronological walk-forward with >=75% pass rate;
- at least 100 games in an untouched outer holdout;
- RMSE and Negative-Binomial NLL improvement, with MAE regression capped at 0.01;
- no market probability and no reconstructed historical features used for promotion.

Until those gates pass, the heuristic champion stays in production.

## FINAL distribution challengers

Historical run-mean and score-distribution candidates are FINAL-only and remain inactive until they transfer to at least 20 exact current-generation FINAL games from the independent pre-candidate baseline.

They cannot activate from the large reconstructed historical cohort alone.

## Uncertainty

Discord reports a **model uncertainty band**, not a validated frequentist “90% confidence interval”. Internally the current band retains a nominal 90% width convention for compatibility, but the artifact explicitly records `coverage_validated=false` until empirical coverage is demonstrated.

Market disagreement is reported separately and does not make the baseball-only uncertainty band narrower.

## Free provider foundation

Historical reconstructed enrichments remain free and promotion-ineligible.

Weather uses Open-Meteo Single Runs first. If the exact run archive is unavailable, the collector may use the documented Previous Runs fixed-lead fields; the lead is chosen conservatively relative to the pregame cutoff and the fallback provenance is stored explicitly.

Park factors use Baseball Savant first. If Savant's client-rendered leaderboard cannot be parsed, a clearly labeled MLB Stats fallback derives a venue run-environment index from the three completed seasons ending before the target season. The fallback never pretends to be handedness-specific and cannot become native promotion evidence.

Provider health distinguishes `HEALTHY`, `DEGRADED` and `FAIL`, so a valid fallback is visible without being confused with a hard provider outage.

## Data quality

Model-input DQ is based on usable baseball information: starter identity/statistics, lineup identities/statistics, team statistics, weather applicability and bullpen coverage. Sharp coverage, market freshness and execution price are kept out of model-input DQ so they cannot improve the baseball probability's epistemic confidence.

## Tracking and API usage

The production bot itself is manual-only through `.github/workflows/mlb-bot.yml` (`workflow_dispatch` only).

Research collection may wake automatically, but `v11/v13_research_gate.py` first checks the free MLB schedule and current journal. The paid Odds API is called only if at least one future game has entered an EARLY/LATE/FINAL phase not already captured under the current predictive contract.

Market tracking uses checkpoint polling rather than repeatedly buying the same market state: one T-60 window and one close window per tracked observation, with all games due at a checkpoint batched into one Odds API request.

## Runtime integration safety

V13 now uses an explicit `V13Engine` composition in `v11/v13_engine.py`. The mature V12.3 code remains a compatibility/base layer for structural projections, data acquisition, score-matrix primitives and legacy research shadows, but V13 no longer monkey-patches `engine_v12.analyze`, `_analysis_points`, `prob_home_win` or `methodology_v123.bootstrap_prior_v123`.

`v11/v13_runtime.py` installs one explicit engine object into `runner.engine` and keeps only a marked persistence adapter. `v13_runtime.assert_runtime_hooks()` retains its historical function name for compatibility, but now verifies the opposite architectural invariant: the explicit V13 engine is installed and no V13 global engine monkey-patches are present.

The explicit engine owns V13 run priors, distribution candidates, extra-innings probability, both standard runline pairs, calibration and the production probability contract. V12 regression behavior remains covered independently.

## Engineering closure registries

`data/v138_audit_closure.json` is the exact 52-point V13.8 registry and keeps engineering closure separate from statistical evidence closure.

The earlier broader “~90 remaining engineering points” was an estimate because the original 275-point audit was never committed as a numbered machine-readable checklist. V13.9 freezes that estimate into `v11/v139_engineering_closure.py`: exactly 90 concrete engineering controls with executable checks. It is explicitly labeled a **reconstructed engineering registry**, not a recovered copy of the missing historical audit.

CI requires the reconstructed registry to remain 90/90 engineering-closed. Statistical evidence gates remain independent and are never closed merely because an engineering control is green.

## Workflows

- `.github/workflows/mlb-bot.yml` — **manual production run** and Discord publication.
- `.github/workflows/v13-historical-backfill.yml` — **manual historical replay/backfill**.
- `.github/workflows/v12-3-research-collector.yml` — automatic cheap phase gate; paid analysis only for an uncaptured phase.
- `.github/workflows/v13-market-tracking.yml` — checkpoint market/settlement tracking.
- `.github/workflows/v13-daily-postmortem.yml` — daily scoring and cumulative evidence report.
- `.github/workflows/v13-7-free-data-collector.yml` — free Statcast/MLB/weather/park foundation.
- `.github/workflows/v13-provider-hardening-ci.yml` — live smoke tests for the free weather/park fallback contracts.
- `.github/workflows/v13-8-audit-closure.yml` — V13.8 evidence closure plus V13.9 reconstructed 90-point engineering closure.
- `.github/workflows/ci.yml` — software/statistical invariants.

A green CI proves implementation invariants; it is not evidence of predictive profitability.

## Shared validation

The critical V13 suite is centralized:

```bash
python -m py_compile v11/*.py tests/*.py
python -m v11.v13_preflight --verbose
python -m v11.v13_entry --self-test
python -m v11.v139_engineering_closure --assert-closed
```

Historical rebuild:

```bash
python -m v11.v13_historical_backfill --dir runtime/v13/replays
python -m v11.v13_run_mean_prior
python -m v11.v13_distribution_prior
python -m v11.v13_train
python -m v11.v13_historical_validation
python -m v11.v13_posterior_policy
```

The historical workflow remains the preferred way to execute this chain because it verifies provenance, PUSH conditioning, unique-game promotion semantics and model-generation compatibility before persisting evidence.
