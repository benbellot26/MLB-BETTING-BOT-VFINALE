# Pulsar V14 — MLB Probability Engine

Pulsar V14 is the production MLB probability engine in this repository.

V13.10 is frozen as historical rollback/regression code only. It is not used by the live production workflow.

## Production path

`MLB/Odds acquisition -> native V14 structural inputs -> run model -> contextual overlay -> score distribution -> probability surface -> validation -> Discord analytics`

The live workflow is `.github/workflows/mlb-bot.yml` (`Pulsar V14 Production`).

V14 is baseball-first and market-independent: bookmaker prices may be used to choose the market line to price and to calculate post-model edge diagnostics, but bookmaker probability is never a predictive feature.

## Core V14 modules

- `v14/acquisition.py` — MLB schedule and Odds API acquisition.
- `v14/mlb_inputs.py` — native pregame baseball inputs.
- `v14/structural.py` — structural run projection.
- `v14/run_stack.py` / `v14/park.py` — run environment and park handling.
- `v14/context_overlay.py` — starter, confirmed lineup/matchup and bullpen context with bounded residual adjustments.
- `v14/distribution.py` — ML, ±1.5 run line and total probabilities from one coherent score distribution.
- `v14/pipeline.py` — single model orchestration entry point.
- `v14/production_runtime.py` — native production payload and Discord execution.
- `v14/market_edge.py` — fair odds, no-vig, edge and EV diagnostics after prediction.
- `v14/tracking.py` — immutable pregame prediction snapshots, settlement and live performance metrics.
- `v14/preflight.py` — production test gate.

## Safety rules

- Pregame information only in production.
- Missing data never becomes an invented advantage.
- Market probability is forbidden as a model feature.
- Contextual adjustments are bounded.
- Production payloads contain analytics, not automatic betting recommendations.
- Every production prediction is persisted before the game for later scoring.

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

`data/v14_predictions.jsonl` is the canonical V14 point-in-time prediction ledger. A production run adds predictions before publication; settlement later adds only final scores and settlement timestamps.

`data/v14_performance.json` reports:

- Brier score;
- Log Loss;
- accuracy at 50%;
- observed vs predicted rates;
- ML performance;
- home/away -1.5 run-line performance;
- totals performance;
- team-run and total-run MAE.

ROI is intentionally not reported until an official bet/stake ledger exists. CLV is intentionally not reported until canonical closing prices are persisted. The repository does not manufacture either metric.

## Workflows

- `Pulsar V14 Production` — live native V14 analysis and Discord publication.
- `Pulsar V14 Performance` — daily settlement and performance refresh.
- `Pulsar V14 CI` — focused V14 production tests.
- `Pulsar Regression CI` — broad historical regression/rollback guard.
- `Pulsar V14 Native Parity` — temporary rollback diagnostic comparing native V14 acquisition with the frozen legacy reference; it cannot publish.

Older V12/V13 historical, backfill and research workflows are retained only where they still provide rollback or historical evidence. They are not part of the production path.

## Legacy policy

The `v11/` directory is legacy. New production code must not import it. V14 has an import-boundary test that protects this rule.

Legacy code may remain only when it is needed for historical replay, regression evidence or rollback. Dead production/runtime compatibility code should be removed rather than carried forward.

## Change policy

A V14 model change should improve accuracy, robustness, data quality or reproducibility and remain point-in-time safe. Predictive changes should be judged on stored pregame evidence using proper scoring metrics, not on a few recent wins or losses.
