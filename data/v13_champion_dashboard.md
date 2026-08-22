# V13.10 Champion Diagnostic Dashboard

Model generation: `v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3`
Latest settled date: `2026-08-21`

## Core scorecard

| Metric | Latest day | Cumulative |
|---|---:|---:|
| Games | 15 | 35 |
| Home run MAE | 1.823 | 2.054 |
| Away run MAE | 2.132 | 2.480 |
| Total run MAE | 2.752 | 3.568 |
| Brier | 0.205 | 0.220 |
| LogLoss | 0.602 | 0.633 |
| Calibration gap | -0.397 | -0.126 |

## Cumulative by market

| Market | N | Brier | LogLoss | Mean p | Outcome rate | Calibration gap |
|---|---:|---:|---:|---:|---:|---:|
| ML | 35 | 0.220 | 0.633 | 0.532 | 0.657 | -0.126 |
| RUNLINE | 0 | — | — | — | — | — |
| TOTAL | 0 | — | — | — | — | — |

## Data-quality bands

| DQ band | Games | Run MAE total | Brier | LogLoss |
|---|---:|---:|---:|---:|
| >=0.90 | 28 | 3.258 | 0.211 | 0.615 |
| 0.75-0.90 | 4 | 3.830 | 0.255 | 0.703 |
| 0.60-0.75 | 3 | 6.103 | 0.262 | 0.717 |

## Highest run-error teams (min 3 observations)

| Team | N | Run MAE | Bias |
|---|---:|---:|---:|
| Los Angeles Angels | 3 | 6.407 | 2.614 |
| Athletics | 3 | 3.083 | -1.696 |
| Texas Rangers | 3 | 2.999 | -2.999 |
| Cincinnati Reds | 3 | 2.958 | 0.109 |
| Washington Nationals | 3 | 2.759 | -1.843 |
| Cleveland Guardians | 3 | 2.432 | -0.579 |
| St. Louis Cardinals | 3 | 2.390 | 2.167 |
| Tampa Bay Rays | 3 | 2.253 | -0.900 |
| Seattle Mariners | 3 | 1.985 | 1.985 |
| Toronto Blue Jays | 3 | 1.921 | 0.406 |

## Data blockers

- `starter_stats_unusable`: 2

> Diagnostic only. This report does not modify V13.10 probabilities or selection behavior.
