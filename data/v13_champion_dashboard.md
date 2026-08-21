# V13.10 Champion Diagnostic Dashboard

Model generation: `v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3`
Latest settled date: `2026-08-20`

## Core scorecard

| Metric | Latest day | Cumulative |
|---|---:|---:|
| Games | 9 | 20 |
| Home run MAE | 2.575 | 2.227 |
| Away run MAE | 3.590 | 2.742 |
| Total run MAE | 4.778 | 4.179 |
| Brier | 0.225 | 0.232 |
| LogLoss | 0.642 | 0.657 |
| Calibration gap | 0.085 | 0.078 |

## Cumulative by market

| Market | N | Brier | LogLoss | Mean p | Outcome rate | Calibration gap |
|---|---:|---:|---:|---:|---:|---:|
| ML | 20 | 0.232 | 0.657 | 0.528 | 0.450 | 0.078 |
| RUNLINE | 0 | — | — | — | — | — |
| TOTAL | 0 | — | — | — | — | — |

## Data-quality bands

| DQ band | Games | Run MAE total | Brier | LogLoss |
|---|---:|---:|---:|---:|
| >=0.90 | 15 | 3.613 | 0.215 | 0.622 |
| 0.60-0.75 | 3 | 6.103 | 0.262 | 0.717 |
| 0.75-0.90 | 2 | 5.542 | 0.318 | 0.830 |

## Highest run-error teams (min 3 observations)

| Team | N | Run MAE | Bias |
|---|---:|---:|---:|

## Data blockers

- `starter_stats_unusable`: 2

> Diagnostic only. This report does not modify V13.10 probabilities or selection behavior.
