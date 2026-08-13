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
- Bookmaker weights are allowed to learn only after at least 80 settled V11 observations for the bookmaker.
- Learned weight adjustments are capped to ±15% around conservative priors.
- The journal records bookmaker-level benchmark components so the weights can be evaluated and learned from real outcomes.
- A model + sharp-market ensemble is recorded in shadow only. It does not affect official picks in V11.0.0.

## Why the ensemble stays shadow-only

The existing 2026 baseball backtest does not contain point-in-time historical bookmaker prices. Activating a model/market blend without historical evidence could improve apparent agreement while silently degrading the independent model. V11 therefore records the blend and compares its Brier score to both the baseball model and the sharp benchmark after enough settled live observations.

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

1. `python -m py_compile bot.py bot_v11.py`
2. the complete V10.0.15 regression self-test chain
3. V11 sharp-consensus self-tests
4. `python bot_v11.py`
5. JSONL validation
6. history/journal persistence only after success

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
- point-in-time sharp-market historical backtest if a historical odds plan is available.

V11.0.0 intentionally avoids activating those changes until they demonstrate better out-of-sample prediction metrics.
