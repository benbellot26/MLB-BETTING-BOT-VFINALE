# Professionalization audit implementation map

This branch implements the audit as a system redesign rather than 35 isolated constants.

1. **Learnable model layer** — `pro_model.py` fits residual run corrections and calibration instead of pretending `train.py` trains the structural engine.
2. **Point-in-time methodology** — backtest accepts only stored pregame rows and raw run snapshots are now archived for future true replay.
3. **Proper scoring rules** — Brier/LogLoss remain first-class; model, structural and sharp are compared separately.
4. **Reduced structural double counting** — structural formula is kept interpretable while learned residuals must prove holdout value.
5. **Richer context** — starter history, K/BB/HR profile, three-day bullpen availability and weather are captured.
6. **Starter priors** — year-by-year prior replaces immediate league-average collapse for small current-season samples.
7. **Trainable dispersion** — Negative Binomial dispersion is estimated into the candidate artifact once enough data exist.
8. **Extra-innings heuristic containment** — the previous run-share pseudo-model is removed from the V12 production probability and a neutral documented prior is used until inning-level point-in-time evidence exists.
9. **Calibration** — arbitrary phase shrinkage is removed from V12 execution probability; validated market-specific calibration is supported.
10. **Uncertainty** — confidence is no longer reused as an execution input; explicit model uncertainty drives a conservative haircut.
11. **Data quality** — independent completeness score and hard FINAL/starters/sharp/execution blockers.
12. **Sharp foundation retained** — book-level de-vig and disagreement robustness remain.
13. **Unknown timestamps fixed** — missing timestamps are excluded, not treated as age zero.
14. **Book weights** — configurable source reliability and effective sample size.
15. **Exchange commission** — Betfair/Matchbook decimal prices are commission-adjusted before de-vig.
16. **All Winamax lines** — V12 prices all available execution lines, not only a modal line.
17. **Push-aware EV retained** — p_win/p_push remain explicit.
18. **Safety margin fixed** — flat +0.01 odds padding replaced by probability uncertainty haircut.
19. **Bankroll staking** — fractional Kelly now uses bankroll with bet/day caps.
20. **Combo exposure** — combo cannot reuse a single-selected game and retains push-aware expectation math.
21. **Idempotency** — event-sourced ledger blocks repeat positions across runs.
22. **Drawdown order** — production ledger computes drawdown/losing streak in settlement-time order.
23. **CLV** — official-plan/latest/closing price observations and CLV metrics are recorded.
24. **Schema isolation** — new rows carry `v12-professional-v1`; legacy data remains readable but is not relabeled.
25. **Git bloat control** — raw/market snapshots are ignored from Git and uploaded as Actions artifacts; compact evidence remains versioned.
26. **RAW archive** — exact MLB/Odds payloads consumed by each run are persisted to a run snapshot.
27. **As-of discipline** — backtest rejects post-start analysis rows and the new archive is timestamped per run.
28. **Structural vs market separation** — p_structural, p_market, p_model and calibrated p_effective stay distinct.
29. **Hybrid architecture** — structural baseline + learned residual + calibration + market + value + portfolio.
30. **Variance learning** — candidate estimates run dispersion rather than requiring a forever-fixed constant.
31. **Tests expanded** — stale/missing timestamps, DQ, uncertainty, Kelly, idempotency and push/correlation constraints are covered.
32. **CI split** — automatic push/PR CI is separate from manual production execution.
33. **HEAD validation** — the new CI validates every branch push/PR instead of relying on an older manually dispatched run.
34. **API/data failures visible** — DQ and health reporting expose missing coverage; fallbacks no longer masquerade as complete data for betting eligibility.
35. **Health check** — Discord/report coverage shows scheduled, matched, analyzed, lineup/starter, sharp and Winamax coverage.

## Important evidence boundary

Several improvements require data that did not exist historically: raw closing prices, exact historical API payloads, inning-level extra-inning state, Statcast point-in-time features and long-lived raw snapshots. This branch implements the collection, storage contracts, validation gates and model hooks now. It does **not** fabricate those missing historical observations to claim an artificial backtest advantage.

The event ledger records the bot's official recommendations and observed prices; it is not an automated wager-execution interface to Winamax.
