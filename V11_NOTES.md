# MLB Betting Bot V11.0.0 — Predictive Benchmark Upgrade

## Objective

Improve prediction quality without rewriting the validated V10.0.15 baseball engine before new features are proven.

## What changes

- `bot.py` remains frozen as the V10.0.15 reference engine.
- `bot_v11.py` imports the V10.0.15 engine and patches only the market benchmark / journal layer.
- The reference market is now based on a sharp-book set by default:
  - Pinnacle
  - Betfair Exchange EU
  - Matchbook
  - BetOnline.ag
- Winamax remains requested for display/execution information but is excluded from the predictive benchmark.
- Every bookmaker probability is de-vigged before aggregation.
- Market freshness is included in the weight.
- A robust disagreement penalty prevents a single outlier feed from dominating the consensus.
- All sharp books start with equal prior weight: V11 does not hard-code an unproven bookmaker hierarchy.
- Bookmaker skill is learned separately for ML, Run Line and Totals.
- Learning uses only one independent model-favoured observation per game/market: complementary sides and repeated manual runs cannot inflate the sample.
- FINAL observations replace LATE/EARLY observations for the same game/market when available.
- Bookmaker weights can change only after at least 80 settled independent V11 observations for that market.
- Learned weight adjustments are capped to ±15%.
- The journal records bookmaker-level benchmark components so the weights can be evaluated and learned from real outcomes.
- A model + sharp-market ensemble is recorded in shadow only. It does not affect official picks in V11.0.0.

## Point-in-time validation

The broad 2026 baseball replay did not contain historical bookmaker prices, so it could not validate a market blend. However, the production V10 history already contains real pregame market snapshots captured on live runs.

`v11_benchmark_report.py` uses only those persisted point-in-time snapshots. It makes no historical odds API calls and does not reconstruct missing prices. It compares:

- independent model Brier / LogLoss;
- legacy market benchmark Brier / LogLoss;
- V11 sharp benchmark Brier / LogLoss;
- individual sharp-book Brier / LogLoss;
- a model + sharp blend chosen on the chronological first 75% and evaluated on the latest 25% holdout.

The blend remains shadow-only even if it looks promising. Activation should require a stable holdout improvement and additional live V11 confirmation.

## What does not change

- Structural run model
- Residual run model
- Walk-forward / holdout guards
- Negative-binomial score distribution
- Existing phase logic
- Existing V10.0.15 calibration and selector lab
- Bankroll and exposure limits
- Discord structure
- Live journal settlement
- Historical V10 files and seed data

## GitHub Actions

The workflow remains manual (`workflow_dispatch`). It now runs:

1. `python -m py_compile bot.py bot_v11.py v11_benchmark_report.py`
2. the complete V10.0.15 regression self-test chain
3. V11 sharp-consensus self-tests
4. point-in-time V11 benchmark report
5. `python bot_v11.py`
6. JSON / JSONL validation
7. history, journal and benchmark-report persistence only after success

## Default V11 configuration

```text
V11_SHARP_BOOKS=pinnacle,betfair_ex_eu,matchbook,betonlineag
V11_EXECUTION_BOOKS=winamax_fr
V11_BOOK_WEIGHT_MIN_N=80
V11_MAX_MARKET_AGE_MIN=90
V11_CONSENSUS_ROBUST_SCALE=0.035
V11_SHADOW_MODEL_WEIGHT=0.55
```

## Next predictive work

The next baseball-feature changes should be tested in shadow/backtest before activation, especially:

- directional wind relative to ballpark orientation rather than treating all strong wind as run-positive;
- reliever-level bullpen availability / consecutive-day workload;
- starter recent-form features with shrinkage;
- stricter lineup-confirmation provenance;
- expansion of point-in-time market coverage as more V11 snapshots accumulate.

V11.0.0 intentionally avoids activating unvalidated baseball-feature changes until they demonstrate better out-of-sample prediction metrics.
