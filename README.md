# Pulsar V14 — MLB Probability Engine

Pulsar **V14.2.0** (`pulsar-v14-context-v3`) is the production MLB probability engine in this repository. V13.10 is frozen historical rollback/regression code only and is not used by the live production workflow.

## Production path

`MLB/Odds acquisition -> native structural inputs -> residual context -> regulation score model + extra-inning settlement -> ML/RL/Total surface -> post-model market diagnostics -> strict PIT tracking -> Discord analytics`

The live workflow is `.github/workflows/mlb-bot.yml` (`Pulsar V14 Production`). Bookmaker prices may select the line to price and may be used after prediction for no-vig/edge/EV diagnostics, but bookmaker probability is never a predictive feature.

## Core rules

- Native V14 acquisition matches games by team identity and start time; doubleheader Odds events are unique and cannot be reused.
- Team offense, team pitching, starter ERA/WHIP shrinkage, lineup OPS, previous-game bullpen, travel/rest and park belong to the structural layer.
- Partial lineups are shrunk toward team OPS; only 9/9 is `CONFIRMED`.
- Starter K/BB/HR, advanced lineup/Statcast/platoon, three-day bullpen availability and bounded weather are residual context only.
- H2H and recent form remain disabled until live out-of-sample evidence proves value.
- LATE/FINAL production requires both announced starting pitchers; FINAL also requires both 9/9 lineups.
- Regulation ties are explicitly resolved through an extra-innings scoring kernel for ML, ±1.5 run lines and totals. Final-score probabilities never leave impossible ties unresolved.
- Market freshness is timestamp-verified when possible. Missing bookmaker timestamps are fallback-only; stale or materially future timestamps are rejected.
- Production fails if fewer than 80% of matched Odds games can be priced.
- Every tracking record must satisfy `analyzed_at < game_date`; the canonical scored record is the latest strictly-pregame snapshot per game.

## Market audit and tracking

`market_snapshot` and `market_diagnostics` are preserved end-to-end from the native candidate through the production payload into `data/v14_predictions.jsonl`. They contain bookmaker/line/price/time state and no-vig/edge/EV diagnostics, but never feed the baseball probability model.

`data/v14_performance.json` reports Brier Score, Log Loss, calibration, ML/RL/Total performance and run MAE. The cross-market aggregate is dashboard-only because markets within a game are correlated.

**ROI remains unavailable** until an official bet/stake ledger exists. **True CLV remains unavailable** until there is an official selection ledger plus canonical closing-price feed. A separate `market_movement_proxy` may compare persisted market snapshots; it must not be called bet CLV.

## Native evidence

- `data/v14_extra_innings_prior.json` — V14-native authenticated historical extra-inning home-win prior.
- `data/v14_park_factors_manifest.json` — V14-native manifest over the frozen leakage-safe historical park dataset.

The old raw historical files may remain in the repository for reproducibility, but production code reaches them through V14 contracts rather than treating legacy schema names as the production API.

## Main modules

- `v14/acquisition.py` — MLB/Odds acquisition, retry/cache, aliases and time-aware matching.
- `v14/mlb_inputs.py` — native team/starter/lineup/bullpen/weather inputs.
- `v14/structural.py` — structural run means.
- `v14/run_stack.py` / `v14/park.py` — prior-season park correction.
- `v14/context_overlay.py` — bounded residual context.
- `v14/distribution.py` — correlated NB regulation scoring plus explicit extra-inning resolution.
- `v14/market_lines.py` / `v14/market_edge.py` — line/price snapshots and post-model diagnostics.
- `v14/pipeline.py` — model orchestration.
- `v14/production_runtime.py` — coverage gate, payload validation and publication.
- `v14/tracking.py` — immutable strictly-pregame snapshots, settlement and performance.
- `v14/preflight.py` — critical production test gate.

## Commands

```bash
python -m py_compile v14/*.py
python -m v14.preflight
python -m v14.production_runtime --target-date YYYY-MM-DD
python -m v14.tracking snapshot --payload runtime/v14/discord_payload.json
python -m v14.tracking settle
```

## Workflows

- `Pulsar V14 Production` — live native analysis and Discord publication.
- `Pulsar V14 Performance` — daily settlement/performance refresh.
- `Pulsar V14 CI` — critical V14 production tests, including phase, market end-to-end persistence and extra-inning settlement.
- `Pulsar Regression CI` — historical rollback/regression guard.
- `Pulsar V14 Native Parity` — historical diagnostic only; it cannot authorize or publish production.

## Change policy

Predictive changes must be point-in-time safe and judged on stored pregame evidence using proper scoring metrics. No coefficient should be tuned to a handful of recent wins/losses. V14.2 starts a distinct generation so its live performance is not mixed with V14.1.
