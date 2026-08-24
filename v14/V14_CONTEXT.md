# Pulsar V14 — Contextual Shadow Layer

## Status

**Experimental / shadow only.**

V13.10 remains the production champion. This V14 line is deliberately isolated from the production execution and Discord publication paths. Nothing in this package is allowed to change V13.10 picks, stakes or delivery.

The contextual layer is a clean-room implementation of useful concepts found during the audit of an external MLB analytics project. No source code from that project is copied.

## Why this V14 exists

The first V14 objective is not to replace a working V13.10. It is to test whether a small number of intuitive baseball context signals add measurable, out-of-sample information after the existing V13.10 run stack has already done its work.

The experiment therefore starts from the exact V13.10 champion run means and applies only a tightly capped **residual** adjustment.

## Context modules

### 1. Starter Vulnerability

Continuous score from 0 (strong) to 100 (vulnerable), built from available PIT starter metrics such as ERA, WHIP, BB/9, HR/9, K/9 and innings/sample confidence. Missing starter identity or insufficient metrics is unavailable, not neutral/weak.

Maximum raw residual contribution: **±1.8%** to opponent run mean before double-counting guard.

### 2. Confirmed Lineup Strength

Only a real ordered/confirmed lineup is eligible. V14 never creates a fake starting nine by sorting the roster by batting average. The initial score uses covered hitter OPS and can accept already-PIT V13 rich lineup/Statcast/platoon context when present.

Maximum raw residual contribution: **±1.8%** before double-counting guard.

### 3. Bullpen Stress

Combines PIT bullpen availability/workload with covered reliever quality: taxed/unavailable relievers, repeat use, recent three-day pitch load and ERA/WHIP quality when available. Minimum coverage is required.

Maximum raw residual contribution: **±1.5%** before double-counting guard.

### 4. H2H micro-signal

Hitter-vs-pitcher H2H is **disabled unless a correct PIT producer explicitly supplies it** under `v14_supplemental`. When available it is Bayesian-shrunk with 40 virtual at-bats at a .250 prior. Maximum contribution: **±0.4%**.

### 5. Recent-form micro-signal

Recent hitting form is also dormant unless explicitly supplied with a PIT baseline and sample size. Maximum contribution: **±0.4%**.

## Global safety cap

After all components and double-counting guards, each team's contextual correction is hard-capped at **±2.5% of its V13.10 run mean**. The guard is stronger when V13 already has an active module representing the same baseball information.

## Point-in-time contract

`v14.feature_row` only selects feature-store rows that match the target game, are explicitly point-in-time, have no PIT validation reasons, are not explicitly ineligible, and have `as_of <= prediction_timestamp`.

V13's feature store itself already rejects predictively incompatible and invalid pregame rows and keeps final labels in a separate label store.

A future/mismatched/unsafe feature row makes the contextual layer an exact **no-op**.

## Market separation

`v14.market_edge` is diagnostic only. It can calculate implied probability, two-way no-vig probability, fair odds, edge, EV and closing-line diagnostics. Market probability is never accepted as a predictive input.

The audit record can retain model probability, market price, no-vig probability, edge, model version, timestamp, stake, result, P&L, closing odds and CLV.

## Running the contextual shadow

```bash
python -m v14.context_shadow
```

Optional:

```bash
python -m v14.context_shadow --payload runtime/v11/discord_payload.json --feature-store data/v13_feature_store.jsonl --output data/v14_context_shadow.jsonl --strict
```

Journal input is also supported:

```bash
python -m v14.context_shadow --journal data/v11_3_live.jsonl
```

Every output remains `SHADOW_ONLY`, `affects_production=false`, and `market_probability_used_as_feature=false`.

## Tests

```bash
python -m unittest tests.test_v14_context_overlay tests.test_v14_feature_row tests.test_v14_market_edge tests.test_v14_context_shadow
```

The historical V14 champion-parity/foundation tests remain in the branch as additional protection.

## Promotion gate

V14 must not replace V13.10 because it looks better on a few slates. Promotion requires a sufficiently large PIT shadow sample and out-of-sample evidence against V13.10, including Brier score, Log Loss, calibration, segmented ML/RL/totals performance, ROI, CLV and edge-bucket stability.

Any module that does not improve the evidence stays shadow-only or is removed.

## Deliberately rejected ideas

- hard-coded season values;
- fake top-nine lineups;
- raw AVG hitter tiers;
- binary weak-pitcher recommendations;
- one-game H2H presented as season H2H;
- treating missing data as `0-0`;
- market-free recommendations without probability/edge validation;
- manual confidence stars as model confidence.
