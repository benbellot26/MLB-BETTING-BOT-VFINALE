# V12.4 Historical Reconstruction Warm Start

## Purpose

Use the legacy 2026 1,801-game cohort as a **research-only warm start** for V12.4 module weights without pretending those rows are native V12.3.2/V12.4 evidence.

The native V12.4 counter remains separate (`0/75`, then `150`, then `250`). Historical games never increment that counter and can never promote production automatically.

## Point-in-time reconstruction

Games are processed chronologically. For each game, the reconstruction:

1. reads the legacy gamePk/date/final score and legacy V10 structural run means;
2. uses the historical starting-lineup identity from the final boxscore only as a FINAL-phase counterfactual identity;
3. builds hitter, starter, team-pitching and reliever state from **games already processed**;
4. computes the V12.4 module effects before updating state with the current game's statistics;
5. optionally queries Baseball Savant aggregate data with a cutoff before the game;
6. updates cumulative state only after the prediction row has been created.

This prevents the current game's batting/pitching result from entering its own prediction.

## Reconstructed modules

- Lineup player-level: chronological pregame OPS from prior boxscores.
- Starter expected IP: chronological pitcher workload/skill from prior games.
- Bullpen player-level: prior reliever performance plus prior three-day pitch usage.
- Platoon: chronological proxy that buckets a game's batting line by the opposing starter hand. Because it is not exact PA-by-PA handedness, its coverage is deliberately discounted by 35%.
- Statcast: Baseball Savant aggregate point-in-time cutoff when available.
- Weather x park: **coverage forced to zero** because the legacy cohort has no archived pregame weather forecast.

## Market boundary

Historical odds are not available. Therefore reconstruction uses only:

- ML probability scoring;
- the legacy standard Run Line proxy already stored in the historical dataset;
- team-run and total-run prediction error.

Historical Totals are not synthesized, historical closing lines are not invented, ROI is not trained, and no profitability claim is allowed.

## Baseline boundary

The historical rows use legacy V10 structural run means as an explicitly labeled `baseline_historical_proxy`. They are **not renamed into native V12.3.2 evidence**.

The proxy is used only to measure incremental module effects and initialize V12.4 shadow weights.

## Warm-start validation

The reconstruction is eligible only if:

- at least 600 reconstructed games are available;
- an expanding chronological walk-forward is active;
- a frozen final test (15%, minimum 100 games) was never used for fitting the weights;
- frozen-test Brier does not regress;
- frozen-test LogLoss does not regress;
- team-run MAE does not regress by more than 0.02 runs.

If the gate fails, the historical artifact stays diagnostic-only and V12.4 optimized remains governed by native data.

## Historical/native blending

If the historical artifact passes:

- native 0-74 games: historical weights may drive **V12.4 optimized shadow only**;
- native 75-149 games: historical and native weights are blended, with native influence increasing with sample size;
- native 150+ games: native weights fully replace the historical prior.

V12.3.2 production selection, Kelly, staking, Discord official picks and lifecycle are unchanged throughout.
