# V13.10 Champion Diagnostic Dashboard

Model generation: `v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3`
Latest settled date: `2026-08-19`

## Core scorecard

| Metric | Latest day | Cumulative |
|---|---:|---:|
| Games | 11 | 11 |
| Home run MAE | 1.942 | 1.942 |
| Away run MAE | 2.048 | 2.048 |
| Total run MAE | 3.689 | 3.689 |
| Brier | 0.238 | 0.238 |
| LogLoss | 0.669 | 0.669 |
| Calibration gap | 0.072 | 0.072 |

## Cumulative by market

| Market | N | Brier | LogLoss | Mean p | Outcome rate | Calibration gap |
|---|---:|---:|---:|---:|---:|---:|
| ML | 11 | 0.238 | 0.669 | 0.527 | 0.455 | 0.072 |
| RUNLINE | 0 | — | — | — | — | — |
| TOTAL | 0 | — | — | — | — | — |

## Data-quality bands

| DQ band | Games | Run MAE total | Brier | LogLoss |
|---|---:|---:|---:|---:|
| >=0.90 | 9 | 3.277 | 0.220 | 0.633 |
| 0.75-0.90 | 2 | 5.542 | 0.318 | 0.830 |

## Highest run-error teams (min 3 observations)

| Team | N | Run MAE | Bias |
|---|---:|---:|---:|

## Data blockers

- `starter_stats_unusable`: 2

> Diagnostic only. This report does not modify V13.10 probabilities or selection behavior.
