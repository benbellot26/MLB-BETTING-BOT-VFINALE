# MLB Betting Bot V10 — release candidate

V10 changes are isolated on `v10-professional` until validation passes.

- Structural run projection: starter, bullpen, lineup, splits, Statcast, park, weather.
- Residual learning and calibration isolated by EARLY/LATE/FINAL phase.
- Run Line and Totals recommendations restricted to reference-market main lines.
- Confidence capped by reference-book depth and data quality; unsupported disagreement is penalized.
- Prediction ledger with ML/RL/TOTAL settlement and Brier/LogLoss reporting.
- Market- and phase-specific calibration with push preservation.
- Daily plan uses up to 3 qualified singles and never forces a parlay.
- Parlay metrics include all-win/no-loss probabilities, push-aware EV and bankroll exposure cap.
- Production workflow never rewrites Python source and only persists V10 data.

Promotion to `main` is permitted only after `python -m py_compile bot.py` and `python bot.py --self-test` pass in GitHub Actions.
