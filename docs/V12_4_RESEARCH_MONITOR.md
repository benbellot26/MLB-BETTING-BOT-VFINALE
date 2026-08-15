# V12.4 Research Monitor

## Purpose

The Research Monitor makes V12.4 shadow evidence visible on every normal bot run without changing any V12.3.2 production decision.

It reports:

- progress toward the 75 / 150 / 250 settled-game evidence stages;
- V12.3.2 baseline vs V12.4 `all_core`, `optimized`, and `ensemble` metrics;
- Brier, LogLoss, accuracy and >55% hit rate;
- ML / Run Line / Total metrics separately;
- each predictive ablation and its learned weight;
- optimizer `KEEP / WATCH / REJECT` diagnostics;
- changes versus the previous persisted report;
- the largest V12.3.2 ↔ V12.4 probability disagreements on the current run;
- V11.5 shadow context.

## Canonical research unit

A game can appear multiple times in the live journal because the bot may produce multiple point-in-time snapshots before first pitch. Research evidence must not count those rows as independent games.

The monitor installs a canonicalization layer used by the V12.4 metrics and weight optimizer:

- one `game_pk` = one settled observation;
- the latest settled pre-game snapshot is retained;
- duplicate earlier snapshots are excluded from the 75 / 150 / 250 counters and optimizer fitting.

This prevents repeated snapshots of one MLB game from artificially accelerating the evidence thresholds or overweighting one outcome.

## Per-market metrics

Each V12.4 variant now exposes separate `ML`, `RUNLINE`, and `TOTAL` research metrics in addition to the overall variant metrics. This allows a module to be judged differently across markets without fitting market-specific production weights prematurely.

## Discord behavior

A single `🧪 V12.4 RESEARCH MONITOR` embed is appended to the normal Discord publication flow. It is explicitly research-only and is not a betting recommendation.

The production workflow defers Discord publication. The enriched V12.4 report therefore replaces the preliminary report inside `runtime/v11/discord_payload.json` before the persisted payload is sent.

The monitor is deliberately non-blocking: a monitor formatting or Discord failure cannot keep official V12.3.2 recommendations in `PROPOSED` state and cannot block their publication lifecycle.

## Production isolation

The monitor and canonicalization layer do not modify:

- V12.3.2 probabilities;
- selector eligibility;
- reference-price floors;
- confidence thresholds;
- Kelly sizing;
- bankroll controls;
- official Discord pick selection;
- recommendation lifecycle;
- automatic promotion policy.

`research_only = true` and `affects_v12_selection = false` remain mandatory. There is no automatic promotion at 75, 150, or 250 games.
