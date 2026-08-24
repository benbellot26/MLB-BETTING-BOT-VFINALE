# V13.10 Champion Diagnostic Dashboard

Model generation: `v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3`
Latest settled date: `2026-08-22`
100-game checkpoint: **65/100** (65.0%) — `COLLECTING`

## Core scorecard

| Metric | Latest day | Cumulative |
|---|---:|---:|
| Games | 15 | 50 |
| Home run MAE | 2.069 | 2.058 |
| Away run MAE | 2.293 | 2.424 |
| Total run MAE | 4.017 | 3.702 |
| Brier all markets | 0.264 | 0.255 |
| LogLoss all markets | 0.725 | 0.703 |

## Cumulative by market

| Market | N | Accuracy | Brier | LogLoss | ECE | Pushes |
|---|---:|---:|---:|---:|---:|---:|
| ML | 65 | 72.3% | 0.224 | 0.640 | 0.160 | 0 |
| RUNLINE | 65 | 50.8% | 0.258 | 0.709 | 0.112 | 0 |
| TOTAL | 72 | 40.3% | 0.279 | 0.754 | 0.192 | 3 |

## Market × data quality

| Market | DQ band | N | Accuracy | Brier | LogLoss |
|---|---|---:|---:|---:|---:|
| ML | 0.60-0.75 | 7 | 57.1% | 0.263 | 0.720 |
| ML | 0.75-0.90 | 16 | 56.2% | 0.242 | 0.677 |
| ML | >=0.90 | 42 | 81.0% | 0.210 | 0.613 |
| RUNLINE | 0.60-0.75 | 7 | 42.9% | 0.301 | 0.798 |
| RUNLINE | 0.75-0.90 | 16 | 68.8% | 0.231 | 0.655 |
| RUNLINE | >=0.90 | 42 | 45.2% | 0.261 | 0.715 |
| TOTAL | 0.60-0.75 | 15 | 26.7% | 0.294 | 0.783 |
| TOTAL | 0.75-0.90 | 16 | 18.8% | 0.279 | 0.751 |
| TOTAL | >=0.90 | 41 | 53.7% | 0.274 | 0.745 |

## Run Line diagnostic

Probability sample: **65** • accuracy 50.8% • projected-margin sample **50** • margin MAE 2.604 • bias -0.158

| |Projected margin| | N | Accuracy | Brier |
|---|---:|---:|---:|
| 1-2 | 14 | 57.1% | 0.246 |
| <1 | 36 | 55.6% | 0.248 |

## Total / Over-Under diagnostic

Probability sample: **72** • accuracy 40.3% • run-projection sample **59** • total MAE 3.735 • bias -0.854

| Total line | N | Accuracy | Brier |
|---|---:|---:|---:|
| 8.0-8.5 | 38 | 52.6% | 0.262 |
| 9.0-9.5 | 5 | 80.0% | 0.219 |
| <=7.5 | 24 | 20.8% | 0.310 |
| >=10.0 | 5 | 0.0% | 0.323 |

## Posterior shadow monitor

| Market | N | Δ Brier | Δ LogLoss | Status |
|---|---:|---:|---:|---|
| ML | 65 | 0.0014 | 0.0029 | COLLECTING |
| RUNLINE | 65 | -0.0002 | -0.0005 | COLLECTING |
| TOTAL | 72 | 0.0143 | 0.0307 | COLLECTING |

## Data-quality bands (run projection)

| DQ band | Games | Run MAE total | Brier | LogLoss |
|---|---:|---:|---:|---:|
| >=0.90 | 33 | 3.313 | 0.250 | 0.695 |
| 0.75-0.90 | 12 | 4.244 | 0.242 | 0.676 |
| 0.60-0.75 | 5 | 4.975 | 0.292 | 0.781 |

## Highest run-error teams — shrinkage protected

| Team | N | Run MAE | Raw bias | Shrunk bias | Reliability |
|---|---:|---:|---:|---:|---:|
| Los Angeles Angels | 4 | 4.987 | 1.778 | 0.445 | 25.0% |
| Cincinnati Reds | 4 | 3.891 | 1.754 | 0.439 | 25.0% |
| Texas Rangers | 4 | 3.487 | -3.487 | -0.872 | 25.0% |
| Philadelphia Phillies | 3 | 3.356 | 3.003 | 0.601 | 20.0% |
| Colorado Rockies | 3 | 3.002 | -3.002 | -0.601 | 20.0% |
| Washington Nationals | 4 | 2.621 | -1.934 | -0.484 | 25.0% |
| Miami Marlins | 3 | 2.570 | -2.570 | -0.514 | 20.0% |
| Cleveland Guardians | 4 | 2.487 | -1.098 | -0.275 | 25.0% |
| Athletics | 4 | 2.400 | -1.360 | -0.340 | 25.0% |
| Atlanta Braves | 3 | 2.355 | -2.355 | -0.471 | 20.0% |

## Highest run-error venues — shrinkage protected

| Venue | Games | Total MAE | Raw total bias | Shrunk bias |
|---|---:|---:|---:|---:|
| Daikin Park | 4 | 6.093 | -0.481 | -0.120 |
| Globe Life Field | 4 | 5.125 | -5.125 | -1.281 |
| Rate Field | 3 | 4.819 | 0.404 | 0.081 |
| Citizens Bank Park | 3 | 4.673 | 1.642 | 0.328 |
| Fenway Park | 3 | 3.588 | -0.452 | -0.090 |
| Coors Field | 3 | 3.499 | -3.499 | -0.700 |
| Kauffman Stadium | 4 | 3.435 | -0.881 | -0.220 |
| American Family Field | 4 | 3.369 | 0.292 | 0.073 |

## Data blockers

- `starter_stats_unusable`: 2

> Diagnostic only. Market tracking, posterior monitoring, shrinkage and the 100-game checkpoint do not modify V13.10 probabilities or selection behavior.
