# MLB Betting Bot — V11 Standalone

## Production architecture
- `v11/core.py`: MLB Stats API, The Odds API, Winamax execution prices and Discord transport.
- `v11/engine.py`: V11 run projection + overdispersed Negative Binomial score distribution + ML / Run Line / Total probabilities.
- `v11/market.py`: stale-aware, freshness-weighted sharp de-vig for ML, spreads ± and totals.
- `v11/selector.py`: V11 value gate, portfolio limits and 2-leg combo.
- `v11/journal.py`: point-in-time journal, settlement, Brier/LogLoss, ROI, drawdown and losing streak.
- `v11/discord.py`: game cards, Top 3 ML/RL/Total and Plan Officiel V11.
- `v11/runner.py`: sole production orchestration.
- `v11_3_live.py`: compatibility entrypoint used by the current GitHub Action.
- `bot.py`: compatibility shim only; the former engine implementation has been removed.

## Production status
**V11 is the only production engine.**

- Moneyline: V11.
- Run Line: V11.
- Totals Over/Under: V11.
- Top 3: V11.
- Official selector: V11.
- 2-leg combo: V11.
- Winamax price/value gate: V11.
- Legacy code dependency: **none**.

Historical pre-V11 data files may remain in `data/` strictly as frozen benchmarks. They are never imported to generate a pick.

## V11 probability model
The standalone engine estimates expected home/away runs from current-season offense, batting-order-weighted lineup OPS, opponent pitching, sample-shrunk probable starter ERA/WHIP, park factor, home advantage and bounded operational context (rest, travel, recent extra innings/doubleheader and previous-game bullpen workload).

Expected runs are converted into a full **Negative Binomial** score matrix, which allows more MLB run dispersion than an independent Poisson model. The same score distribution produces Moneyline, Run Line and Total probabilities.

For integer Run Line / Total markets, V11 models `p_win` and `p_push` separately. The value gate therefore prices refunded outcomes correctly rather than treating a push as half a loss.

## Sharp market ensemble
Reference books are de-vigged one book at a time. Books older than **90 minutes** are excluded. Remaining references are freshness-weighted, and disagreement between sharp books automatically reduces their blend weight.

The base blend weight is bounded at approximately **12–25%** depending on the number of fresh references. Winamax remains execution-only and is never used as predictive truth.

## Official bet rule
A prediction and a bet are separate decisions. A V11 option is official only if:
- model probability/confidence/quality are sufficient;
- at least one fresh reference market is available;
- the exact Winamax market/line exists;
- the Winamax price clears fair price + EV floor + edge floor + safety margin;
- portfolio exposure and correlation limits are respected.

The portfolio remains limited to 3 official singles, one single per match, no more than two selections from the same market profile, and 4 units total including the optional 2-leg combo.

## Point-in-time evidence
Every run stores V11 probabilities for **ML / Run Line / Total**, `p_win`, `p_push`, sharp references, lineup/starter context, operational adjustments, Winamax price and official decision in `data/v11_3_live.jsonl` (legacy filename retained only because the current workflow already persists it).

Settled games are graded automatically. `v11_backtest.py` evaluates captured point-in-time evidence separately for EARLY / LATE / FINAL so later information is not injected into earlier phases.

## Financial evidence
The journal settles official singles and official combos and reports P/L, ROI, market split, maximum drawdown and longest losing streak from recorded Winamax prices. A PUSH leg in a combo is removed from the effective combo price rather than incorrectly grading the entire combo as a push.

Historical ROI or CLV is never fabricated where point-in-time prices do not exist.

## Calibration improvement loop
`v11_train.py` evaluates chronological train/holdout calibration candidates separately for ML, Run Line and Total. Candidates are never auto-promoted; improvements must be demonstrated on unseen/live evidence before changing production coefficients.

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
V11 is the sole production code path, but statistical superiority is an evidence claim, not a version-name claim. Frozen historical results remain only as a comparison baseline. V11 is considered superior market by market only after its out-of-sample/live Accuracy, Brier, LogLoss and betting results support that conclusion.
