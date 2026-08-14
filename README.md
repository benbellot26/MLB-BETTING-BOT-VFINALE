# MLB Betting Bot — V11

## Production architecture
- `bot.py`: frozen V10.0.15 baseball baseline and legacy Discord renderer.
- `v11/`: explicit V11 orchestration, ML heads, features, value-gated selector,
  journal/settlement/ROI and Champion/Challenger gates.
- `v11_3_live.py`: compatibility entrypoint used by the current GitHub Action.

`sitecustomize.py` is no longer part of the architecture.

## Current production status
- Moneyline direction: V11.3.
- Moneyline probability: V11.2.
- Run Line / Total: V10.0.15 **until** their V11 challengers pass the
  predeclared chronological and live evidence gates.
- Official selection: V11 value gate. A strong prediction is not an official
  bet unless the recorded Winamax price is high enough for the configured EV
  and edge floors.
- Discord: the existing V10 presentation is reused.

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
including phase, lineups, starters and available market snapshot. This is the
basis for future EARLY/LATE/FINAL backtests without leaking final information.

## Local validation
```bash
python -m py_compile bot.py v11_3_live.py v11/*.py tests/test_v11.py
python bot.py --self-test
python v11_3_live.py --self-test
python -m unittest tests.test_v11
```

## Remaining evidence work
The code framework can be made complete immediately; statistical superiority
cannot be manufactured. RL, Total, selector and combo promotion remain gated
until enough point-in-time and live data exist to demonstrate improvement.
