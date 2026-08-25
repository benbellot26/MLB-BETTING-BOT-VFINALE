# Pulsar V14 — MLB Probability Engine

Pulsar V14 is the production MLB probability engine in this repository.

V13.10 is frozen as historical rollback/regression code only. It is not used by the live production workflow.

## Production path

`MLB/Odds acquisition -> native V14 structural inputs -> residual context -> score distribution -> probability surface -> post-model market diagnostics -> validation -> Discord analytics`

The live workflow is `.github/workflows/mlb-bot.yml` (`Pulsar V14 Production`).

V14 is baseball-first and market-independent: bookmaker prices may be used to choose the market line to price and to calculate post-model no-vig edge/EV diagnostics, but bookmaker probability is never a predictive feature.

## Core V14 modules

- `v14/acquisition.py` — MLB schedule and Odds API acquisition with retry and process-local request caching.
- `v14/mlb_inputs.py` — native pregame baseball inputs, 9/9 lineup state, three-day bullpen workload and MLB weather/roof context.
- `v14/structural.py` — structural run projection.
- `v14/run_stack.py` / `v14/park.py` — run environment and park handling.
- `v14/context_overlay.py` — strictly residual starter K/BB/HR, advanced lineup, three-day bullpen and bounded weather adjustments. Structural ERA/WHIP and lineup OPS are not counted a second time.
- `v14/distribution.py` — ML, ±1.5 run line and total probabilities from one coherent score distribution.
- `v14/pipeline.py` — single model orchestration entry point.
- `v14/production_runtime.py` — native production payload and Discord execution.
- `v14/market_lines.py` — fresh canonical line selection and immutable bookmaker price snapshots.
- `v14/market_edge.py` — fair odds, no-vig, edge and EV diagnostics after prediction.
- `v14/tracking.py` — immutable pregame prediction/market snapshots, settlement and live performance metrics.
- `v14/preflight.py` — production test gate.

## Current signal policy

The structural model owns the fundamental baseball inputs already validated under the V13.10 parity contract: team offense, lineup OPS, team pitching, starter ERA/WHIP with historical shrinkage, prior-game bullpen usage, travel/rest and park.

The V14 contextual layer may only add information not already consumed structurally. Current production residuals are:

- starter K/9, BB/9 and HR/9 profile;
- advanced lineup/Statcast/platoon information when explicitly available;
- three-day reliever workload and likely availability;
- bounded outdoor temperature/wind/precipitation context, neutralized for closed/indoor roofs.

H2H and recent-form signals are explicitly disabled pending sufficient live out-of-sample evidence. Missing advanced inputs fail closed to zero adjustment.

## Safety rules

- Pregame information only in production.
- Missing data never becomes an invented advantage.
- Market probability is forbidden as a model feature.
- Contextual adjustments are bounded to a maximum team move.
- A lineup is `CONFIRMED` only at 9/9; partial batting orders remain `PARTIAL`.
- Production payloads contain analytics, not automatic betting recommendations.
- Every production prediction and available market snapshot is persisted before publication for later scoring.
- Retrieval timestamps are distinguished from source-provided timestamps; provenance never claims a source timestamp that MLB did not expose.

## Commands

Production validation:

```bash
python -m py_compile v14/*.py
python -m v14.preflight
```

Build the native production payload locally when the required API key is available:

```bash
python -m v14.production_runtime --target-date YYYY-MM-DD
```

Persist a pregame prediction snapshot:

```bash
python -m v14.tracking snapshot --payload runtime/v14/discord_payload.json
```

Settle completed games and rebuild performance:

```bash
python -m v14.tracking settle
```

## Live evidence

`data/v14_predictions.jsonl` is the canonical V14 point-in-time prediction ledger. A production run adds model probabilities, run means, phase, canonical bookmaker price snapshots and post-model edge/EV diagnostics before publication; settlement later adds only final scores and settlement timestamps.

`data/v14_performance.json` reports:

- Brier score and Log Loss per market;
- accuracy at 50%;
- observed vs predicted rates;
- ML performance;
- home/away -1.5 run-line performance;
- totals performance;
- team-run and total-run MAE;
- a latest-persisted-pregame-price CLV proxy when at least two market snapshots exist for a game.

The aggregate cross-market Brier is dashboard-only because markets from the same game are correlated; it must not be used as the primary promotion criterion.

ROI is intentionally not reported until an official bet/stake ledger exists. CLV is labelled as a proxy until a dedicated canonical closing-price feed is persisted; the repository does not manufacture a true close.

## Workflows

- `Pulsar V14 Production` — live native V14 analysis and Discord publication.
- `Pulsar V14 Performance` — daily settlement and performance refresh.
- `Pulsar V14 CI` — focused V14 production tests.
- `Pulsar Regression CI` — broad historical regression/rollback guard.
- `Pulsar V14 Native Parity` — rollback diagnostic comparing native V14 acquisition with the frozen legacy reference; it cannot publish.

Older V12/V13 historical, backfill and research workflows are retained only where they still provide rollback or historical evidence. They are not part of the production path.

## Legacy policy

The `v11/` directory is legacy. New production code must not import it. V14 has an import-boundary test that protects this rule.

Legacy code may remain only when it is needed for historical replay, regression evidence or rollback. Dead production/runtime compatibility code should be removed rather than carried forward.

## Change policy

A V14 model change should improve accuracy, robustness, data quality or reproducibility and remain point-in-time safe. Predictive changes should be judged on stored pregame evidence using proper scoring metrics, not on a few recent wins or losses. Coefficient changes should wait for a meaningful live sample rather than being tuned to individual slates.
