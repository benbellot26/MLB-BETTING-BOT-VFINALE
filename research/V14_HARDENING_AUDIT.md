# Pulsar V14 hardening audit

This branch hardens the V14.6 production/research boundary without changing the current champion probability generation.

## Production safeguards

- Dedicated `runtime-data` branch for mutable ledgers, reports and refreshed data artifacts.
- Shared Odds API accounting for scheduled FINAL, close and manual snapshots.
- MLB slate-date limits plus a 450-credit local hard monthly ceiling on a 500-credit plan, leaving a 50-credit reserve.
- The Odds API response headers (`x-requests-remaining`, `x-requests-used`, `x-requests-last`) are captured after paid responses without persisting credentials.
- Once provider quota telemetry exists, the next paid request is blocked if its conservative cost would reduce the provider-reported balance below the same 50-credit reserve; this guard is independent of Pulsar's UTC-month rollover.
- Paid-call reservations are durably persisted before network execution. Close capture uses a pre-network persistence hook; if that state push fails, the paid Odds loader is never called.
- Current-generation performance/calibration/certification summaries are rebuilt by a zero-Odds identity workflow when stale.
- Feature-family ownership contract prevents hidden double counting across STRUCTURAL, CONTEXT and ALL_STATS layers.
- Data-quality dashboard separates operational health from betting authorization.

## Shadow challengers only

The following additions cannot auto-activate and do not alter V14.6 probabilities:

- adaptive 14/30/45/60-day Statcast windows;
- learned residual-layer weights with regularized chronological holdout;
- opener/bulk role handling that refuses to invent an unidentified bulk pitcher;
- integer-total push probability;
- existing individual bullpen Statcast-quality × availability behavior is explicitly regression-tested.

All new model experiments are preregistered in `research/v14_experiments.json` and remain nomination-only until their prospective validation gates pass.

## Non-goals

- no V15;
- no staking increase;
- no certification-threshold reduction;
- no hidden market probability as a baseball feature;
- no reuse of old-generation certification as current-generation evidence.
