# V11.1.5 — 2026 strict walk-forward backtest

This backtest is a **research/validation layer only**. It never changes official V10/V11 selections and it never writes to the live point-in-time journal.

## Baseline

The baseline is the existing `data/mlb_backtest_2026.jsonl` replay:

- V10 ML probability: `v10.p_home`
- V10 run means: `v10.home_mu` / `v10.away_mu`
- final result: `y`, `home_score`, `away_score`
- historical starter IDs/hands: `starters`

The original V10 replay remains useful as the common reference, but its own report documents frozen-input spot-check limitations. The V11.1 feature layer below is reconstructed independently and chronologically.

## No-lookahead contract

`v11_walkforward_backtest.py` processes the season by **Eastern calendar date**.

For every date:

1. state contains only games from previous Eastern dates;
2. every game on the current date is predicted;
3. only after every prediction is frozen are that date's boxscores ingested.

This intentionally refuses to use a same-day final even when a game started earlier. It is slightly conservative, but prevents doubleheader/same-day leakage.

## Reconstructed features

### Bullpen
- individual prior-game relief appearances;
- D-1 / D-2 / D-3 pitch counts;
- rolling season-to-date FIP-like quality;
- leverage weighting;
- position-player pitching noise and obvious rotation profiles filtered.

### Starting pitcher recent form
- last five prior starts only;
- FIP-like K/BB/HR signal;
- season-to-date baseline only;
- recent sample shrunk toward season skill;
- recent/season innings depth included.

### PROJECTED_HISTORY lineup
- prior seven batting orders only;
- rolling prior-game hitter production only;
- OPS reconstructed from OBP + SLG components and shrunk by PA;
- minimum 55% real-stat coverage;
- rejected lineups produce zero lineup and zero matchup correction.

### POSTED_RETRO lineup
Optional retrospective LATE scenario using the actual historical batting order from the current game, but **never current-game batting stats**.

It is never labelled EARLY because the exact historical lineup publication timestamp is not archived. It is reported separately from PROJECTED_HISTORY.

### Starter handedness interaction
The same V11.1.5 platoon logic is applied to a lineup only when that lineup passes its quality gate.

### Historical weather
Optional Open-Meteo archive weather is fetched in bulk by home park. Directional wind is only applied where the live V11.1 layer already has an audited home-plate-to-center-field azimuth. Unknown orientations stay neutral.

Weather changes run means only; it does not change the ML probability.

## Outputs

- `data/v11_walkforward_2026.jsonl`
- `data/v11_walkforward_2026_report.json`

The report contains V10 baseline, each individual ablation, full projected V11.1, optional POSTED_RETRO variants, Brier, LogLoss, accuracy, paired bootstrap Brier-gain probability, feature coverage, run MAE, chronological 75/25 split, and monthly breakdown.

Historical bookmaker ROI is intentionally absent because comprehensive archived point-in-time sharp/Winamax prices are not available.

## Promotion policy

Historical evidence can make V11.1 a stronger **candidate**, but cannot activate it by itself. Live point-in-time confirmation remains required before any production integration.

## Manual workflow

Use `Actions -> V11 2026 Walk-Forward Backtest -> Run workflow`.

Recommended smoke run first: `2026-03-25` to `2026-04-05`, `max_games=50`, `workers=6`, with POSTED_RETRO and archive weather enabled. Once clean, run the full range with `max_games=0`.
