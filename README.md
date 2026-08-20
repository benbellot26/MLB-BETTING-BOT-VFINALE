# MLB Betting Bot — V13.10 Champion

V13.10 is the single production champion of this repository.

The objective is not to create a new version number. The objective is to make V13.10 the most accurate, robust and reproducible MLB probability engine possible. A change belongs in the champion only when it fixes a real defect or is supported by point-in-time, out-of-sample evidence. V14 has been abandoned and removed.

## Production rule

The production probability is baseball-first and market-independent:

1. `p_baseball_raw` — baseball model probability before V13 calibration.
2. `p_baseball_calibrated` — baseball-only calibrated probability.
3. `p_market` — de-vig market consensus used as a benchmark only.
4. `p_posterior` — research-only market-aware comparison.
5. `p_predictive_final` — the production probability; it must remain equal to `p_baseball_calibrated` unless an explicit future promotion is supported by independent evidence.

Market probability is forbidden from entering baseball calibration or silently changing `p_predictive_final`.

## Champion runtime

The V13.10 runtime is explicit and intentionally reuses mature V12.3 primitives where they are still required:

`PregameSnapshot -> V12.3 structural primitives -> V13 park/run stack -> score distribution -> validated extra innings -> baseball calibration -> probability-surface reconciliation`

The `v11/` directory name is historical. It contains both legacy compatibility code and current V13.10 production modules. Files must therefore be judged by dependency and evidence, not by their directory/version prefix.

Core V13.10 responsibilities include:

- point-in-time input provenance;
- structural home/away run means;
- prior-season park factor handling;
- validated run-mean and distribution priors;
- extra-innings home-win probability;
- ML, standard ±1.5 runline and total probability generation;
- baseball-only calibration;
- uncertainty and probability-surface consistency;
- strict model-generation fingerprints;
- analytics-only output safety;
- feature/label leakage guards.

## Legacy and challenger policy

V11.5 and V12.4 predictive shadows are disabled by default when V13.10 starts. Dedicated research may opt into them explicitly, but they are not part of the champion production path.

Posterior, rich/native, run-mean and score-distribution candidates may exist only when they provide useful evidence for V13.10. A candidate must not affect the production probability merely because it exists in the repository.

No challenger is promoted automatically. A promotion requires chronological point-in-time evidence, an untouched holdout, proper-score improvement and an explicit decision to change the champion.

## Point-in-time evidence

Pregame evidence and final labels are separated. Historical replay must preserve the original `as_of`, model generation and pregame provenance. Final MLB scores are labels only and must never become features.

For RUNLINE/TOTAL markets with PUSH probability, binary scoring uses:

`P(WIN | no PUSH) = P(WIN) / (1 - P(PUSH))`

The push mass remains stored separately.

Reconstructed historical data may support research and transfer tests, but it must never masquerade as exact native current-generation evidence.

## Calibration

Baseball calibration is baseball-only. Sportsbook probabilities are not calibration features.

Activation remains evidence-gated. If the evidence is insufficient or unstable, the identity transform is preferred over an unproven correction.

The current strict evidence floors are:

- GLOBAL: 600 observations;
- per market: 400 unique game-market targets;
- per phase/market: 300 game-phase-market targets.

Method selection uses chronological validation and an untouched holdout.

## Historical transfer

Historical run-mean and score-distribution transfer remains useful because V13.10 can consume these artifacts when their safety and exact-transfer gates pass. The historical-transfer workflow is therefore retained even if some filenames contain older version labels.

Activation must remain FINAL-only, point-in-time safe, market-independent and protected by exact current-generation transfer evidence.

## Production workflow

`.github/workflows/mlb-bot.yml` is champion-only. It performs:

- a cheap schedule gate;
- V13.10 contract/invariant tests;
- validation of the historical reference required by the V13.10 base layer;
- baseball calibration;
- V13.10 analysis with legacy predictive shadows forced off;
- post-run probability/leakage/lifecycle checks;
- evidence persistence and Discord analytics publication;
- durable point-in-time source archiving.

It no longer trains V12.3 challengers, runs V12.3 backtests, retrains the rich/native challenger or rebuilds the posterior policy on every production analysis.

Research remains separated in dedicated workflows so evidence can improve V13.10 without contaminating its production path.

## Useful supporting workflows

- `.github/workflows/ci.yml` — broad regression and statistical invariants.
- `.github/workflows/v13-historical-backfill.yml` — historical replay/backfill and evidence rebuilding.
- `.github/workflows/v13-11-historical-transfer.yml` — strict run-mean/distribution transfer validation used by V13.10.
- `.github/workflows/v13-daily-postmortem.yml` — settled-game scoring and cumulative evidence.
- `.github/workflows/v13-market-tracking.yml` — market/settlement checkpoints.
- `.github/workflows/v13-7-free-data-collector.yml` — free Statcast/MLB/weather/park data foundation.
- `.github/workflows/v13-provider-hardening-ci.yml` — provider/fallback contract checks.
- `.github/workflows/v13-8-audit-closure.yml` — evidence/engineering guardrails.
- `.github/workflows/v12-3-research-collector.yml` — legacy-named evidence collector retained only while it contributes useful point-in-time research inputs.

## Critical validation

```bash
python -m py_compile v11/*.py tests/*.py
python -m v11.v13_preflight --verbose
python -m v11.v13_entry --self-test
```

The preflight includes a V13.10 champion-only guard that verifies V11.5/V12.4 shadows are off by default.

A green CI validates implementation invariants. It does not by itself prove predictive superiority or profitability.

## Change policy

Before changing the champion, answer three questions:

1. Does this directly improve V13.10 accuracy, robustness, data quality, reproducibility or evidence quality?
2. Is the change protected against point-in-time leakage and regression?
3. Is the gain measurable on independent data rather than inferred from a small recent sample?

If the answer is no, the change does not belong in the production champion.
