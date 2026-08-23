# V13.10 Champion Diagnostic Dashboard

Model generation: `v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3`
Latest settled date: `2026-08-22`

## Core scorecard

| Metric | Latest day | Cumulative |
|---|---:|---:|
| Games | 15 | 50 |
| Home run MAE | 2.069 | 2.058 |
| Away run MAE | 2.293 | 2.424 |
| Total run MAE | 4.017 | 3.702 |
| Brier | 0.248 | 0.229 |
| LogLoss | 0.688 | 0.650 |
| Calibration gap | -0.049 | -0.103 |

## Cumulative by market

| Market | N | Brier | LogLoss | Mean p | Outcome rate | Calibration gap |
|---|---:|---:|---:|---:|---:|---:|
| ML | 50 | 0.229 | 0.650 | 0.537 | 0.640 | -0.103 |
| RUNLINE | 0 | — | — | — | — | — |
| TOTAL | 0 | — | — | — | — | — |

## Data-quality bands

| DQ band | Games | Run MAE total | Brier | LogLoss |
|---|---:|---:|---:|---:|
| >=0.90 | 33 | 3.313 | 0.211 | 0.614 |
| 0.75-0.90 | 12 | 4.244 | 0.261 | 0.716 |
| 0.60-0.75 | 5 | 4.975 | 0.267 | 0.729 |

## Highest run-error teams (min 3 observations)

| Team | N | Run MAE | Bias |
|---|---:|---:|---:|
| Los Angeles Angels | 4 | 4.987 | 1.778 |
| Cincinnati Reds | 4 | 3.891 | 1.754 |
| Texas Rangers | 4 | 3.487 | -3.487 |
| Philadelphia Phillies | 3 | 3.356 | 3.003 |
| Colorado Rockies | 3 | 3.002 | -3.002 |
| Washington Nationals | 4 | 2.621 | -1.934 |
| Miami Marlins | 3 | 2.570 | -2.570 |
| Cleveland Guardians | 4 | 2.487 | -1.098 |
| Athletics | 4 | 2.400 | -1.360 |
| Atlanta Braves | 3 | 2.355 | -2.355 |

## Data blockers

- `starter_stats_unusable`: 2

> Diagnostic only. This report does not modify V13.10 probabilities or selection behavior.
