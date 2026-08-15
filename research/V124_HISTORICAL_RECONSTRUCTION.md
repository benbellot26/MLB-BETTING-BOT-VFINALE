# V12.4 Historical Reconstruction Warm Start

## Purpose

Use the legacy 2026 1,801-game cohort as a **research-only warm start** for V12.4 module weights without pretending those rows are native V12.3.2/V12.4 evidence.

The native V12.4 counter remains separate (`0/75`, then `150`, then `250`). Historical games never increment that counter and can never promote production automatically.

## Point-in-time reconstruction

The newly reconstructed V12.4 module state is processed chronologically with a **strict J-1 freeze**. All games sharing a calendar date are predicted from exactly the same cumulative player/team state, containing only earlier calendar dates. Only after every game for that date has been frozen are that date's boxscore statistics added to state.

For each game, the reconstruction:

1. reads the legacy gamePk/date/final score and legacy V10 structural run means;
2. uses the historical starting-lineup and starter identities from the final boxscore only as FINAL-phase counterfactual identities;
3. builds hitter, starter, team-pitching and reliever state from **prior calendar dates only**;
4. computes the V12.4 module effects while same-day results remain invisible;
5. optionally queries Baseball Savant aggregate data with a cutoff before the game;
6. updates cumulative boxscore state only after every prediction for the current date has been created.

This is deliberately more conservative than using an earlier completed game from the same day: it prevents any same-day result or overlapping-game timing ambiguity from leaking into another reconstructed V12.4 module.

## Reconstructed modules

- Lineup player-level: chronological pregame OPS from prior-date boxscores.
- Starter expected IP: chronological pitcher workload/skill from prior dates.
- Bullpen player-level: prior reliever performance plus prior-date three-day pitch usage.
- Platoon: chronological proxy that buckets a game's batting line by the opposing starter hand. Because it is not exact PA-by-PA handedness, its coverage is deliberately discounted by 35%.
- Statcast: Baseball Savant aggregate point-in-time cutoff when available; starter identity is resolved by ID/name from the historical boxscore, while performance remains point-in-time.
- Weather x park: **coverage forced to zero** because the legacy cohort has no archived pregame weather forecast.

## Market boundary

Historical odds are not available. Therefore reconstruction uses only:

- ML probability scoring;
- the legacy standard Run Line proxy already stored in the historical dataset;
- team-run and total-run prediction error.

Historical Totals are not synthesized, historical closing lines are not invented, ROI is not trained, and no profitability claim is allowed.

## Baseline boundary

The historical rows use legacy V10 structural run means as an explicitly labeled `baseline_historical_proxy`. They are **not renamed into native V12.3.2 evidence**.

The original 1,801-game V10 dataset is documented as leakage-safe walk-forward: each prediction was generated before the current game's boxscore entered state, with no future-game stats or fabricated historical odds. The new strict J-1 freeze applies specifically to the **reconstructed V12.4 module state**; it does not retroactively claim that the stored legacy V10 baseline itself used a prior-calendar-day freeze.

The proxy is used only to measure incremental module effects and initialize V12.4 shadow weights.

## Warm-start validation

The reconstruction is eligible only if:

- at least 600 reconstructed games are available;
- an expanding chronological walk-forward has at least three future windows;
- aggregate walk-forward Brier and LogLoss do not regress;
- a frozen final test (15%, minimum 100 games) was never used for fitting the weights;
- frozen-test Brier and LogLoss do not regress;
- team-run MAE stays within a 0.02-run non-regression tolerance in both OOS layers.

If the gate fails, the historical artifact stays diagnostic-only and V12.4 optimized remains governed by native data.

## 2026 reconstruction result — 2026-08-15

All **1,801 / 1,801** source games were reconstructed successfully with zero boxscore failures. Coverage was 100% for Starter Expected IP, 99.0% for bullpen player-level, 98.1% for lineup player-level, 85.2% for Statcast, 58.8% for the discounted platoon proxy, and 0% for weather as designed.

The in-development optimizer converged to these candidate weights:

- Starter Expected IP: **0.65**
- Platoon: **0.10**
- Statcast: **0.05**
- Bullpen player-level: **0.00**
- Lineup player-level: **0.00**
- Weather x park: **0.00**

However, the candidate **failed the out-of-sample activation gate** and is therefore `DIAGNOSTIC_ONLY`:

- aggregate chronological walk-forward (1,456 future games / 59 windows): Brier `-0.000199`, LogLoss `-0.000453` versus baseline; team-run MAE improved by `+0.00206` runs;
- untouched frozen test (270 games): Brier `-0.001406`, LogLoss `-0.002899` versus baseline; team-run MAE improved by `+0.00214` runs.

Here a negative probability-score improvement means the reconstructed candidate was worse than baseline. The result is therefore useful evidence **against activating** the historical weight vector, despite its tiny run-error improvement. No gate is relaxed to force a warm start.

Starter Expected IP remains the strongest historical research signal, but even a small Starter-IP-only candidate failed to improve the untouched frozen probability scores, so it is not activated separately.

## Historical/native blending

If a future historical reconstruction passes the same untouched OOS gate:

- native 0-74 games: historical weights may drive **V12.4 optimized shadow only**;
- native 75-149 games: historical and native weights are blended, with native influence increasing with sample size;
- native 150+ games: native weights fully replace the historical prior.

For the current 1,801-game artifact this branch is **not active**, because the historical gate failed. Native V12.4 evidence remains authoritative.

V12.3.2 production selection, Kelly, staking, Discord official picks and lifecycle are unchanged throughout.

## Storage boundary

The full reconstructed 1,801-row evidence file is retained as a GitHub Actions artifact for 90 days. Only the compact validated diagnostic/warm-start model is committed to the repository, avoiding unnecessary repository bloat while preserving reproducibility and auditability.
