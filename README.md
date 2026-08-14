# MLB Betting Bot — V11 Standalone

## Production architecture
- `v11/core.py`: MLB Stats API, The Odds API, Winamax execution prices, sharp de-vig, Discord transport.
- `v11/engine.py`: V11 run projection + independent Poisson score distribution + ML / Run Line / Total probabilities.
- `v11/market.py`: correct de-vig for ML, spreads ± and totals.
- `v11/selector.py`: V11 value gate, portfolio limits and 2-leg combo.
- `v11/journal.py`: point-in-time journal, settlement, Brier/LogLoss, ROI, drawdown and losing streak.
- `v11/discord.py`: game cards, Top 3 ML/RL/Total and Plan Officiel V11.
- `v11/runner.py`: sole production orchestration.
- `v11_3_live.py`: compatibility entrypoint used by the current GitHub Action.
- `bot.py`: compatibility shim only; the former V10 engine code has been removed.

## Production status
**V11 is the only production engine.**

- Moneyline: V11.
- Run Line: V11.
- Totals Over/Under: V11.
- Top 3: V11.
- Official selector: V11.
- 2-leg combo: V11.
- Winamax price/value gate: V11.
- V10 code dependency: **none**.

Historical V10 data files may remain in `data/` strictly as frozen benchmarks. They are never imported to generate a pick.

## V11 probability model
The standalone engine estimates expected home/away runs from current-season offense, opponent pitching, probable starter, available lineup OPS, park factor and home advantage. It converts those expected runs into a full score distribution and derives ML, spread and total probabilities from that same distribution.

When sharp reference books are available, their de-vig consensus is used as a **bounded 15–30% ensemble component**, never as 100% predictive truth. Winamax is execution only and is not part of the predictive consensus.

## Official bet rule
A prediction and a bet are separate decisions. A V11 option is official only if:
- model probability/confidence/quality are sufficient;
- at least one reference market is available;
- the exact Winamax market exists;
- the Winamax price clears fair price + EV floor + edge floor + safety margin;
- portfolio exposure and correlation limits are respected.

## Point-in-time evidence
Every run stores the V11 options, phase, lineup/starter context, sharp probability, Winamax price and official decision in `data/v11_3_live.jsonl`. Settled games are graded automatically for ML, Run Line and Total.

`v11_backtest.py` evaluates the captured point-in-time evidence separately for EARLY / LATE / FINAL so FINAL information is not injected into earlier phases.

## Financial evidence
The journal settles official singles and official combos and reports P/L, ROI, maximum drawdown and longest losing streak from the recorded Winamax prices. Historical ROI or CLV is never fabricated where point-in-time prices do not exist.

## Calibration improvement loop
`v11_train.py` evaluates candidate calibration offsets on chronological train/holdout splits for ML, Run Line and Total. Candidates are never auto-promoted; improvements must be demonstrated on unseen/live evidence before changing production coefficients.

## Local validation
```bash
python -m py_compile bot.py v11_3_live.py v11/*.py tests/test_v11.py
python bot.py --self-test
python v11_3_live.py --self-test
python -m unittest tests.test_v11
python v11_backtest.py
python v11_train.py
```

## Superiority policy
V11 is now the sole production code path, but statistical superiority is an evidence claim, not a version-name claim. The report therefore keeps the old V10 2026 results only as a frozen reference and measures V11 live/backtest performance market by market. V11 should be called superior only where the accumulated out-of-sample evidence supports it.
