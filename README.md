# MLB Betting Bot — V11

## Production architecture
- `bot.py`: frozen V10.0.15 baseball baseline. V11 no longer extends this monolith.
- `v11/`: explicit V11 orchestration, ML heads, enhanced shadow features,
  value-gated selector, journal/settlement/ROI, Discord delivery and
  Champion/Challenger gates.
- `v11_3_live.py`: compatibility entrypoint used by the current GitHub Action.
- `v11_backtest.py`: point-in-time EARLY/LATE/FINAL evaluation.
- `v11_train.py`: creates an **inactive** RL/Total challenger candidate.

`sitecustomize.py` is no longer part of the architecture.

## Current production status
- Moneyline direction: V11.3.
- Moneyline probability: V11.2.
- Run Line / Total: V10.0.15 **until** their V11 challengers pass the
  predeclared chronological and live evidence gates.
- Enhanced lineup, starter, bullpen, rest and travel features are collected in
  shadow only; they cannot silently alter the validated ML head.
- Official selection: V11 value gate. A strong prediction is not an official
  bet unless the recorded Winamax price reaches the configured fair/EV/edge
  floor plus safety margin.
- Combo: 2-leg value-gated construct inside the same daily exposure cap.
- Discord: V10 layout preserved, with wording aligned to V11 economics.

## Promotion policy
No challenger is promoted just because it exists. Promotion requires:
1. chronological no-lookahead evaluation;
2. enough holdout observations;
3. Brier improvement >= configured gate;
4. paired bootstrap gain probability >= configured gate;
5. LogLoss no worse than the configured tolerance;
6. live confirmation;
7. no manual lowering of gates after seeing results.

## Point-in-time evidence
Every V11 run stores a `point_in_time` snapshot in `data/v11_3_live.jsonl`,
including phase, lineups, starters, operational context and available market
snapshot. This is the basis for future EARLY/LATE/FINAL backtests without
injecting FINAL information into EARLY/LATE.

## Financial evidence
The live journal settles singles and official combos, and reports simulated
P/L, ROI, market split, maximum drawdown and longest losing streak using the
recorded Winamax prices. CLV is not claimed until a real closing-price archive
exists.

## Sharp market policy
The sharp consensus is measured as a benchmark against V10/V11.2. It is not
used as predictive truth and is never auto-blended into the model.

## Local validation
```bash
python -m py_compile bot.py v11_3_live.py v11/*.py tests/test_v11.py
python bot.py --self-test
python v11_3_live.py --self-test
python -m unittest tests.test_v11
python v11_backtest.py
python v11_train.py
```

`v11_train.py` writes `data/v11_candidate_model.json` with
`official_effect=false` and `active=false`. Promotion remains a separate,
explicit decision after evidence gates.

## Evidence still required
Statistical superiority cannot be manufactured. RL, Total and enhanced feature
promotion remain gated until enough historical point-in-time and live data
exist. Historical ROI/CLV is intentionally not fabricated where historical
prices are absent.
