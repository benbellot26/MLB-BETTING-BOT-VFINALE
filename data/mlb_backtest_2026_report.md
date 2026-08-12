# MLB 2026 walk-forward backtest — V9 vs V10.0.5

Range: **2026-03-01 → 2026-08-11**  
Games replayed: **1801** (warm sample ≥5 prior games/team: **1724**)  

## Leakage control

- Prediction generated before adding the current game's stats.
- Expanding team/player/starter/bullpen statistics only.
- Actual starter/lineup identity used as FINAL-phase information, but only prior stats contribute.
- No historical bookmaker odds invented: **no ROI/EV/CLV claims**.
- Historical Statcast/weather/market confidence neutralized in this replay.

## Moneyline — all games

- V9 accuracy: **51.92%** | Brier 0.2529 | LogLoss 0.6996
- V10.0.5 accuracy: **53.08%** | Brier 0.2511 | LogLoss 0.6956

## Moneyline — warm sample

- V9 accuracy: **52.15%** | Brier 0.2513 | LogLoss 0.6961
- V10.0.5 accuracy: **53.19%** | Brier 0.2502 | LogLoss 0.6939

## Run projection — warm sample

- V9 team-run MAE **2.547** | RMSE **3.233** | total MAE **3.612**
- V10.0.5 team-run MAE **2.532** | RMSE **3.228** | total MAE **3.612**

## Run Line proxy ±1.5

- N **1801** | hit rate **60.58%**
- This is predictive only; no historical price/value filter.

## Walk-forward activation

- Residual run model active at end: **True**
- ML calibration active at end: **False**

## V10 probability bins (warm sample)

- 50-55%: n=758 | avg model 52.4% | hit 50.7%
- 55-60%: n=529 | avg model 57.4% | hit 52.4%
- 60-65%: n=258 | avg model 62.3% | hit 55.8%
- 65-70%: n=117 | avg model 66.9% | hit 60.7%
- 70-75%: n=51 | avg model 71.8% | hit 70.6%
- 75-80%: n=10 | avg model 76.5% | hit 40.0%
- 80-100%: n=1 | avg model 80.9% | hit 100.0%

## Important limitation

This backtest tests the **baseball prediction engine**, not historical profitability. A true betting ROI backtest needs point-in-time bookmaker lines/prices from a licensed historical odds archive. Those prices are deliberately not reconstructed from future/current data.
