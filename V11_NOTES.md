# MLB Betting Bot V11.0.0 — Predictive Benchmark Upgrade

## Objective

Improve prediction quality without rewriting the validated V10.0.15 baseball engine before new features are proven.

## What changes

- `bot.py` remains frozen as the V10.0.15 reference engine.
- `bot_v11.py` imports the V10.0.15 engine and patches only the market benchmark / journal layer.
- The predictive reference market is based on a sharp-book set by default:
  - Pinnacle
  - Betfair Exchange EU
  - Matchbook
  - BetOnline.ag
- Winamax remains requested for display/execution information but is excluded from the predictive benchmark.
- Betclic, Unibet, PMU and NetBet remain collected as auxiliary sources for market/line coverage but are also excluded from the sharp benchmark.
- Every sharp-book probability is de-vigged before aggregation.
- Market freshness is included in the weight.
- A robust disagreement penalty prevents a single outlier feed from dominating the consensus.
- All sharp books start with equal prior weight: V11 does not hard-code an unproven bookmaker hierarchy.
- Bookmaker skill is learned separately for ML, Run Line and Totals.
- Learning uses only one independent model-favoured observation per game/market: complementary sides and repeated manual runs cannot inflate the sample.
- FINAL observations replace LATE/EARLY observations for the same game/market when available.
- Each book is evaluated against the other sharp books on the same observations, avoiding sample-difficulty bias.
- Bookmaker weights can change only after at least 80 settled independent V11 observations for that market.
- Learned weight adjustments are capped to ±15%.
- The journal records bookmaker-level benchmark components so the weights can be evaluated and learned from real outcomes.

## Point-in-time validation

The broad 2026 baseball replay did not contain historical bookmaker prices, so it could not validate a market blend. However, the production V10 history already contains real pregame market snapshots captured on live runs.

`v11_benchmark_report.py` uses only those persisted point-in-time snapshots. It makes no historical odds API calls and does not reconstruct missing prices. Comparisons are performed on the same matched sample where both the independent effective model and V11 sharp probability exist. It compares:

- independent effective model Brier / LogLoss;
- legacy market benchmark Brier / LogLoss where available;
- V11 sharp benchmark Brier / LogLoss;
- individual sharp-book Brier / LogLoss;
- a model + sharp ML blend whose model weight is chosen on the chronological first 75% and evaluated on the latest 25% holdout.

## Evidence-gated predictive blend

`v11_predictive_gate.py` is the production V11 entrypoint. The ML blend stays OFF unless all gates pass:

- at least 40 chronological holdout games;
- the blend improves Brier by at least 0.0015 versus the independent effective model;
- blend LogLoss is no worse than the independent model;
- at least 60% of holdout observations have 2+ sharp references;
- the blend weight was selected only on the earlier training sample and remains between 25% and 80% model weight.

If any gate fails, ML uses the independent V10 effective probability unchanged. Run Line and Totals remain independent-model only in V11.0.0 regardless of the report. When active, the pre-blend probability is still journaled as `p_effective_independent`, so future validation cannot accidentally grade the blend against itself.

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

1. `python -m py_compile bot.py bot_v11.py v11_benchmark_report.py v11_predictive_gate.py`
2. the complete V10.0.15 regression self-test chain
3. V11 sharp-consensus and predictive-gate self-tests
4. point-in-time V11 benchmark report
5. `python v11_predictive_gate.py`
6. JSON / JSONL validation
7. history, journal and benchmark-report persistence only after success

## Default V11 configuration

```text
V11_SHARP_BOOKS=pinnacle,betfair_ex_eu,matchbook,betonlineag
V11_EXECUTION_BOOKS=winamax_fr
V11_AUX_BOOKS=betclic_fr,unibet_fr,pmu_fr,netbet_fr
V11_BOOK_WEIGHT_MIN_N=80
V11_MAX_MARKET_AGE_MIN=90
V11_CONSENSUS_ROBUST_SCALE=0.035
V11_SHADOW_MODEL_WEIGHT=0.55
V11_AUTO_BLEND_ENABLED=1
V11_AUTO_BLEND_MIN_HOLDOUT=40
V11_AUTO_BLEND_MIN_BRIER_GAIN=0.0015
V11_AUTO_BLEND_MIN_MULTIREF_PCT=0.60
```

## Next predictive work

The next baseball-feature changes should be tested in shadow/backtest before activation, especially:

- directional wind relative to ballpark orientation rather than treating all strong wind as run-positive;
- reliever-level bullpen availability / consecutive-day workload;
- starter recent-form features with shrinkage;
- stricter lineup-confirmation provenance;
- expansion of point-in-time market coverage as more V11 snapshots accumulate.

V11.0.0 intentionally avoids activating unvalidated baseball-feature changes until they demonstrate better out-of-sample prediction metrics.
