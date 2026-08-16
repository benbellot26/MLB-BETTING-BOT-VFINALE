# V13.1 — Historical evidence from the 1,801-game cohort

## Source and provenance

The frozen 2026 walk-forward source contains 1,801 unique MLB games. Its original methodology states that each prediction was generated before adding the current game's statistics, using expanding prior team/player/starter/bullpen statistics only. Actual starter/lineup identity is treated as FINAL-phase information, while only prior statistics contribute. Historical bookmaker odds were not fabricated or used.

This creates a separate `FINAL_RECONSTRUCTED` evidence tier. It is weaker than an exact timestamped HTTP replay and must never be relabeled as EARLY/LATE or exact-replay evidence.

## Reconstructed cohort

- Source games: **1,801**
- Warm games (>=5 prior games for each team): **1,724**
- Cold games: **77**
- Calibration candidate markets from the frozen source: ML and Run Line only
- Totals are diagnostic-only because no historical bookmaker total line exists

### Raw probability diagnostics on the 1,724 warm games

Moneyline: Brier **0.249131**, LogLoss **0.691575**. Confidence bins confirm historical overconfidence: 55–60% model confidence hit 53.1%; 60–65% hit 56.7%; 65–70% hit 61.3%.

Run Line proxy: Brier **0.238923**, LogLoss **0.670753**.

Synthetic Total 8.5: Brier **0.251269**, LogLoss **0.696222**. This synthetic line is not eligible for live calibration.

## Chronological calibration test

Warm games were split by MLB day, not random rows:

- Train: **1,027** games through 2026-06-17
- Validation: **341** games through 2026-07-16
- Untouched test: **356** games through 2026-08-12

A Platt Moneyline challenger improved an internal train holdout but failed on the next chronological validation block: identity Brier **0.244690** vs Platt **0.245486**; identity LogLoss **0.682485** vs Platt **0.684056**. Run Line also preferred identity. Therefore no historical ML or Run Line calibrator is promoted to V13 live.

## Score-distribution ablation

The transferable result is the run-count dispersion. Four variants were evaluated on chronological validation, untouched future test, and the latest exact pregame HTTP replay for each of 29 games.

| Variant | Dispersion | Env sigma | Validation NLL gain | Test NLL gain | Exact replay NLL gain | Decision |
|---|---:|---:|---:|---:|---:|---|
| Default | 7.5 | 0.08 | 0 | 0 | 0 | Baseline |
| Dispersion only | **2.835691** | **0.08** | **+0.056771** | **+0.060600** | **+0.050007** | **Selected** |
| Environment only | 7.5 | 0.00 | -0.008212 | -0.006959 | -0.007609 | Reject |
| Full | 2.835691 | 0.00 | +0.057726 | +0.061632 | +0.050552 | Pass, but more complex |

The least-complexity passing variant is selected: change only the Negative Binomial dispersion to **2.835691107635618**, keep environment sigma at **0.08**.

## Production scope

V13.1 applies this validated dispersion prior **only in FINAL phase**. EARLY/LATE remain unchanged. It changes only the score distribution used to derive baseball-only market probabilities. It does not activate any historical probability calibrator, does not use market probability as a model feature, and does not claim historical ROI/CLV.

The 29 exact HTTP replay games remain the strongest current transfer cohort. Future exact V13 observations continue to be collected and will supersede reconstructed evidence as their sample grows.
