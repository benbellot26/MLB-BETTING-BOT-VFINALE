# MLB Betting Bot — V12 Professional Foundation

V12 keeps the interpretable V11 score-distribution primitives while replacing the most fragile production heuristics with auditable point-in-time data, model uncertainty, Champion/Challenger validation, bankroll-aware portfolio construction, an immutable bet ledger and CLV tracking.

## Production architecture

- `v11/core.py` — MLB/The Odds API transport, Winamax execution prices and Discord transport.
- `v11/engine.py` — retained compatibility/math layer for the established V11 score primitives.
- `v11/engine_v12.py` — production V12 engine: multi-season starter priors, three-day bullpen context, learned residual hook, calibrated probabilities and all executable Winamax lines.
- `v11/context.py` — weather and three-day bullpen availability context.
- `v11/market.py` — book-by-book de-vig, strict timestamp freshness, exchange commission adjustment, configurable book quality and disagreement-aware blending.
- `v11/pro_model.py` — pure-Python residual run model, trainable run dispersion and market-specific probability calibration with chronological holdout gates.
- `v11/data_quality.py` — independent data-completeness score and hard NO-BET blockers.
- `v11/selector.py` — uncertainty-adjusted price gate, fractional Kelly, bankroll/day/bet/correlation caps and duplicate-position prevention.
- `v11/storage.py` — point-in-time raw snapshots, market snapshots, event-sourced bet ledger and CLV observations.
- `v11/journal.py` — prediction journal and settlement compatibility layer.
- `v11/backtest.py` — strictly pregame point-in-time evaluation, structural/model/sharp comparison and walk-forward challenger checks.
- `v11/train.py` — Champion/Challenger candidate generation; promotion is explicit and holdout-gated.
- `v11/discord_v12.py` — V12 game cards, official plan and data-health reporting.
- `tests/test_v11.py` — V12 regression and production-safety tests.

## Model policy

The live probability stack is:

1. interpretable baseball structural baseline;
2. multi-season starter-prior and richer bullpen/context correction;
3. optional learned run-residual correction only after chronological holdout improvement;
4. Negative Binomial score matrix, with dispersion learned when enough settled point-in-time data exist;
5. fresh sharp-market de-vig blend;
6. market-specific probability calibration only when a candidate beats the uncalibrated model on holdout;
7. explicit model uncertainty passed to the execution gate.

A missing Champion artifact does **not** silently activate an unvalidated model. The system runs structural-first and exposes the fallback uncertainty.

## Betting policy

A bet is official only when:

- required data quality is present;
- a fresh sharp reference exists;
- the exact Winamax market/line is executable;
- the Winamax price clears fair value, minimum EV and edge after an uncertainty haircut;
- the same game is not already an open position;
- bankroll-aware fractional Kelly and portfolio exposure limits permit the stake.

The optional two-leg combo cannot reuse a game already selected as a single.

## Point-in-time evidence and CLV

Every production run captures raw MLB/Odds payloads under `runtime/v11/snapshots/` and flattened market snapshots. GitHub Actions uploads these as artifacts instead of committing large raw snapshots into Git history. Compact prediction evidence, model candidates and the event-sourced bet ledger remain in `data/`.

The ledger records the official plan price, later price observations, FINAL-phase closing price when observed, CLV, settlement, ROI and chronologically ordered drawdown. It is an internal recommendation ledger; it does not place a wager at the bookmaker.

Historical information that was never archived is never fabricated. Full historical engine replay becomes stronger as the point-in-time archive grows.

## Champion / Challenger

```bash
python -m v11.train --dry-run
python -m v11.train
python -m v11.train --promote
```

`--promote` refuses promotion unless the candidate passes the configured chronological holdout gates.

## Validation

```bash
python -m py_compile v11/*.py tests/test_v11.py
python -m unittest tests.test_v11
python -m v11.runner --self-test
python -m v11.train --dry-run
python -m v11.backtest
```

`.github/workflows/ci.yml` runs automatically on pushes and pull requests. `.github/workflows/mlb-bot.yml` remains the explicit production workflow and archives raw snapshots as workflow artifacts.
