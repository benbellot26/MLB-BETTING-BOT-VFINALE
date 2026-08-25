# V13.10 Champion Diagnostic Dashboard

Model generation: `v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3`
Latest settled date (any monitored current-generation evidence): `2026-08-24`
Run-projection sample settled through: `2026-08-23`
Market-tracking sample settled through: `2026-08-24`
100-game checkpoint: **75/100** (75.0%) — `COLLECTING`

## Core scorecard

| Metric | Latest day | Cumulative |
|---|---:|---:|
| Run-projection games | 0 | 65 |
| Tracked unique games | 10 | 75 |
| Home run MAE | — | 2.046 |
| Away run MAE | — | 2.452 |
| Total run MAE | — | 3.687 |
| Brier all markets | 0.261 | 0.255 |
| LogLoss all markets | 0.714 | 0.705 |

## Cumulative by market

| Market | N | Accuracy | Brier | LogLoss | ECE | Pushes |
|---|---:|---:|---:|---:|---:|---:|
| ML | 75 | 72.0% | 0.225 | 0.642 | 0.160 | 0 |
| RUNLINE | 75 | 49.3% | 0.260 | 0.713 | 0.135 | 0 |
| TOTAL | 83 | 38.6% | 0.279 | 0.753 | 0.208 | 3 |

## Market × data quality

| Market | DQ band | N | Accuracy | Brier | LogLoss |
|---|---|---:|---:|---:|---:|
| ML | 0.60-0.75 | 13 | 61.5% | 0.257 | 0.709 |
| ML | 0.75-0.90 | 16 | 56.2% | 0.242 | 0.677 |
| ML | >=0.90 | 46 | 80.4% | 0.210 | 0.611 |
| RUNLINE | 0.60-0.75 | 13 | 46.2% | 0.280 | 0.753 |
| RUNLINE | 0.75-0.90 | 16 | 68.8% | 0.231 | 0.655 |
| RUNLINE | >=0.90 | 46 | 43.5% | 0.264 | 0.722 |
| TOTAL | 0.60-0.75 | 22 | 22.7% | 0.299 | 0.792 |
| TOTAL | 0.75-0.90 | 16 | 18.8% | 0.279 | 0.751 |
| TOTAL | >=0.90 | 45 | 53.3% | 0.269 | 0.734 |

## Run Line diagnostic

Probability sample: **75** • accuracy 49.3% • projected-margin sample **65** • margin MAE 2.806 • bias -0.107

| |Projected margin| | N | Accuracy | Brier |
|---|---:|---:|---:|
| 1-2 | 16 | 56.2% | 0.245 |
| <1 | 49 | 49.0% | 0.262 |

## Total / Over-Under diagnostic

Probability sample: **83** • accuracy 38.6% • run-projection sample **75** • total MAE 3.700 • bias -0.623

| Total line | N | Accuracy | Brier |
|---|---:|---:|---:|
| 8.0-8.5 | 40 | 55.0% | 0.254 |
| 9.0-9.5 | 6 | 66.7% | 0.237 |
| <=7.5 | 31 | 16.1% | 0.313 |
| >=10.0 | 6 | 16.7% | 0.309 |

## Posterior shadow monitor

| Market | N | Δ Brier | Δ LogLoss | Status |
|---|---:|---:|---:|---|
| ML | 75 | 0.0024 | 0.0050 | COLLECTING |
| RUNLINE | 75 | 0.0002 | 0.0005 | COLLECTING |
| TOTAL | 83 | 0.0161 | 0.0339 | COLLECTING |

## Data-quality bands (run projection)

| DQ band | Games | Run MAE total | Brier | LogLoss |
|---|---:|---:|---:|---:|
| >=0.90 | 42 | 3.291 | 0.247 | 0.688 |
| 0.75-0.90 | 16 | 4.537 | 0.249 | 0.692 |
| 0.60-0.75 | 7 | 4.125 | 0.288 | 0.771 |

## Highest run-error teams — shrinkage protected

| Team | N | Run MAE | Raw bias | Shrunk bias | Reliability |
|---|---:|---:|---:|---:|---:|
| Chicago Cubs | 3 | 5.697 | 5.697 | 1.139 | 20.0% |
| Los Angeles Angels | 5 | 4.188 | 1.225 | 0.360 | 29.4% |
| Cincinnati Reds | 5 | 3.464 | 1.052 | 0.309 | 29.4% |
| Colorado Rockies | 4 | 3.043 | -3.043 | -0.761 | 25.0% |
| Detroit Tigers | 3 | 3.028 | -1.330 | -0.266 | 20.0% |
| Philadelphia Phillies | 4 | 2.914 | 2.649 | 0.662 | 25.0% |
| New York Mets | 3 | 2.900 | 0.986 | 0.197 | 20.0% |
| Texas Rangers | 5 | 2.883 | -2.696 | -0.793 | 29.4% |
| Washington Nationals | 5 | 2.605 | -2.056 | -0.605 | 29.4% |
| Kansas City Royals | 5 | 2.491 | 1.952 | 0.574 | 29.4% |

## Highest run-error venues — shrinkage protected

| Venue | Games | Total MAE | Raw total bias | Shrunk bias |
|---|---:|---:|---:|---:|
| T-Mobile Park | 3 | 6.377 | 6.377 | 1.276 |
| Daikin Park | 5 | 5.422 | 0.163 | 0.048 |
| Rate Field | 4 | 4.875 | -0.958 | -0.240 |
| Kauffman Stadium | 5 | 4.544 | 1.091 | 0.321 |
| Globe Life Field | 5 | 4.204 | -4.204 | -1.237 |
| Citizens Bank Park | 4 | 3.909 | 1.635 | 0.409 |
| loanDepot park | 3 | 3.544 | -3.544 | -0.709 |
| American Family Field | 4 | 3.369 | 0.292 | 0.073 |

## Data blockers

- `starter_stats_unusable`: 2

> Diagnostic only. Market tracking, posterior monitoring, shrinkage and the 100-game checkpoint do not modify V13.10 probabilities or selection behavior.
