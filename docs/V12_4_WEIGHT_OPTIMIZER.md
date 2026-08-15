# V12.4 Weight Optimizer — shadow research

## Purpose

The optimizer learns how much influence each V12.4 predictive module has earned from settled, point-in-time V12.4 evidence. It is research-only and cannot change V12.3.2 production selection, staking, bankroll controls or Discord recommendations.

## Modules optimized

- platoon / handedness
- Statcast expected metrics
- bullpen player-level
- lineup player-level
- starter expected innings
- weather × park

Uncertainty remains a shrinkage layer rather than a fitted run-factor weight. Ensemble-source weights remain fixed for now; source-weight optimization is deliberately deferred until the V12.4 core is stable.

## Training objective

Weights are bounded to `0.00 .. 1.25` and cannot become negative. The objective is dominated by proper probability scoring:

- 50% LogLoss
- 35% Brier score
- 15% scaled team-run MAE
- L2 regularization toward zero

ROI, profit and realized betting return are never training targets. They remain downstream reporting metrics only.

Historical option probabilities are learned from the already-recorded V12.4 baseline and one-module ablations. This preserves the point-in-time probability/calibration/sharp context that actually existed when the prediction was made. The learned live variant then applies the weights to module run factors and reprices all ML, Run Line and Total options from one common score projection.

## Coverage

A learned weight is multiplied by the module coverage for the current game. Missing or unavailable data therefore reduce that module toward neutral automatically. Modules marked unavailable, disabled or roof-neutral receive zero effective influence.

## Evidence stages

- 0–74 settled games: `COLLECTING`; no optimized live shadow variant.
- 75–149: `EXPERIMENTAL_SHADOW`; learned weights may create an additional V12.4 shadow variant only.
- 150–249: `WALK_FORWARD_READY`; enough observations for a more meaningful expanding-window evaluation.
- 250+: `MATURE_RESEARCH`; still no automatic production promotion.

These are evidence stages, not promotion thresholds.

## Walk-forward validation

The optimizer uses expanding chronological training sets and future 25-game test blocks. For example, the first window trains on the first 75 eligible settled games and evaluates on the next 25. Later windows expand the training history but never fit on their own future test block.

The report compares frozen-window optimized predictions against the V12.3.2 baseline on Brier, LogLoss, team-run MAE and total-run MAE.

## Module verdicts

Each module receives a paired diagnostic versus the baseline and a deterministic bootstrap 95% interval for the combined proper-score/run objective:

- `KEEP`: positive interval and meaningful learned weight.
- `REJECT`: negative interval and near-zero learned weight.
- `WATCH`: evidence is still mixed or insufficient.

A single bad or good slate cannot promote or remove a module.

## Production isolation

`research_only = true` and `affects_v12_selection = false` are hard-coded in the optimizer model and optimized variant. No optimizer path patches the production selector, Kelly staking, price floors, confidence thresholds or publishing lifecycle.
