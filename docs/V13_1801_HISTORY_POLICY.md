# V13 — Safe use of the 1,801-game 2026 historical set

The 1,801-game dataset is documented as leakage-safe for the baseball engine: predictions were generated before current-game boxscore stats entered state, expanding prior stats were used, no historical odds were fabricated, and historical Statcast/weather were neutralized.

It is **not** a native V13 replay dataset. Therefore:

- V10 probabilities are not used to calibrate V13.
- V10 probabilities are not used for edge/value training.
- Historical bookmaker ROI/CLV is not claimed.
- The dataset may be used for transferable score-distribution parameters only.
- Only the warm cohort with at least 5 prior games for both teams is used: 1,724 games.

## Validated transferable result

Chronological split of the warm cohort:

- train: 1,034 games
- validation: 345 games
- frozen test: 345 games

Baseline score distribution:

- Negative Binomial dispersion: 7.5
- shared environment sigma: 0.08

Candidate learned on train:

- dispersion: 3.5
- environment sigma: 0.0

Out-of-sample joint-score NLL gain:

- validation: +0.071712
- frozen test: +0.058360
- walk-forward: 3/3 future windows improved, pass rate 100%

This candidate is eligible only as a **FINAL-phase distribution fallback prior**. A native validated V13 champion or native V13 point-in-time distribution model has priority and supersedes it automatically.

## Bridge limitation

The old dataset ends on 2026-08-12 while archived true V13 source replays begin on 2026-08-14. There are currently zero overlapping games, so direct V10↔V13 probability equivalence cannot be established. This is why the 1,801-game set is not admitted to V13 probability calibration.
