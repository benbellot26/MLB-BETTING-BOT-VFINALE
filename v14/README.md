# V14 — clean V13.10 champion successor

V14 is **not** a weaker minimal rewrite. Its baseline is the last V13.10 production champion that works, reimplemented behind clean boundaries with no V11/V12/V13 runtime dependency. Legacy code is removed only after V14 reproduces the champion behavior it replaces.

## Migration rule

`V13.10 behavior -> clean V14 parity -> remove legacy -> improve by OOS challenge`

Performance comes before code reduction. A V13.10 component that is active and proven is ported first. A historical/research/shadow candidate is not promoted merely because it already exists in the old stack.

## Target production contract

`pregame PIT data -> run model -> champion score distribution -> 8 probabilities -> validated calibration -> tracking/validation`

The eight probabilities are:

- Away ML / Home ML
- Away +1.5 / Home -1.5
- Away -1.5 / Home +1.5
- Over / Under at the canonical half-run total

All four pairs are complementary and are produced from one score distribution.

## Current parity migration

V14 currently ports the V13.10 champion score-distribution behavior natively:

- negative-binomial team scoring,
- common run-environment mixture (`environment_sigma`),
- dynamic tail truncation/renormalization,
- standard ±1.5 runline probabilities,
- canonical half-run totals,
- authenticated extra-innings home-win prior,
- fail-closed eight-probability surface.

During this migration phase, the persisted V13.10 `home_mu` / `away_mu` remain allowed as temporary parity inputs. V13 probabilities, market probabilities, calibration outputs, selectors and staking decisions are never V14 model inputs. `tests/test_v14_champion_parity.py` compares the clean V14 distribution directly with V13.10 math and with real persisted champion snapshots.

The next migration block is the native V14 port of the **V13.10 run stack**. Only when the run means and eight probabilities are parity-tested end-to-end can the legacy runtime be removed.

## What is not copied into the baseline

Unproven candidates stay challengers:

- historical dispersion candidate,
- historical run-mean candidate,
- rich starter/platoon/Statcast/bullpen/player residuals,
- learned calibration while evidence remains below its gate,
- market posterior/blends.

The experimental `run_model.py` is also a challenger. It may replace the ported champion run stack only if it beats that real baseline on untouched chronological data.

## Improvement rule after parity

Every change is tested as:

`current V14 champion` vs `current V14 champion + one candidate change`.

A candidate is retained only if it improves the metrics it is meant to improve without material regressions elsewhere. Simpler code wins only when predictive performance is statistically equivalent.

V13.10 remains production champion until V14 has complete behavioral parity, independent PIT operation, and then demonstrates no regression or a stable gain in run RMSE/NLL and ML/RUNLINE/TOTAL Brier + LogLoss.
