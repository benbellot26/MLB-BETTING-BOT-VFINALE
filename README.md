# Pulsar V14 — MLB Probability & Decision Engine

Pulsar **V14.5.4** is the current production software line. The champion probability generation remains **`pulsar-v14-context-v3`** with probability policy **`pulsar-v14-probability-policy-v1`**. The recent audit-hardening work changed evidence collection, certification, close capture, promotion governance and reporting; it did **not** retune champion probability coefficients or promote a challenger.

## Current production contract

The certifiable production chain is intentionally narrow:

`scheduled FINAL acquisition -> frozen champion probability policy -> executable market -> Pinnacle no-vig primary benchmark -> immutable paper entry -> independent PRIMARY and EXECUTION closes <=15 min -> certification -> authorization/staking`

The live workflow is `.github/workflows/mlb-bot.yml` (`Pulsar V14 Production`). It wakes frequently, but scheduled runs are locally gated before paid Odds acquisition. Manual runs remain available for analysis, but they do not substitute for the objective `SCHEDULED_FINAL` certification cohort.

Market prices are post-model data: they can select executable lines, benchmark probabilities, calculate edge/CLV and drive decision thresholds, but they are never baseball predictive features.

## Probability contract

- Champion generation: `pulsar-v14-context-v3`.
- Probability policy: `pulsar-v14-probability-policy-v1`.
- Probability schema: `pulsar-v14-probability-v2`.
- Production probability transformation is **frozen** under the current probability policy. Calibration artifacts may learn in shadow, but they cannot activate and change published probabilities without an explicit new probability policy.
- Certification evidence must match the exact model generation **and** probability policy.
- Integer-total pushes are excluded from binary Brier/LogLoss/calibration evidence.
- No recent winning streak, challenger result or historical holdout result is sufficient reason to retune the champion.

## Data and point-in-time rules

- MLB and Odds events are matched by canonical team identity and start time; doubleheaders must be unambiguous.
- A real `BET` path requires a verifiable Odds event timestamp.
- Every scored prediction satisfies `analyzed_at < game_date`.
- Betting authorization is FINAL-only under the current certification contract.
- The certifiable prospective cohort uses `SCHEDULED_FINAL`, not human-selected manual timing.
- Historical reconstruction is explicitly separated from native-live evidence and cannot satisfy native-live promotion thresholds.
- V14 Statcast enrichment is stable-ID-only and strict `game_date < cutoff`.
- Weather reconstruction uses point-in-time forecast provenance; post-event observed weather is not substituted for a pregame forecast.
- Research challengers remain shadow-only unless a preregistered prospective promotion guard accepts their exact generation/policy/timing evidence.

## Decision and market separation

`v14/decision.py` evaluates executable prices only after the baseball probability surface exists. A real `BET` must clear the production gates, including:

1. FINAL phase;
2. model edge versus executable breakeven;
3. lower-bound/robust edge versus executable breakeven;
4. positive primary edge versus **Pinnacle no-vig**;
5. verified market freshness;
6. at least one real sportsbook contributor;
7. market-specific betting certification.

The multi-book sharp consensus remains useful as a robustness/disagreement diagnostic, but it is not the primary certification benchmark.

Until the certification requirements are earned, qualifying candidates remain `RESEARCH_ONLY`.

## Prospective evidence and close contract

Pulsar intentionally separates entry, primary market evidence and execution-quality evidence.

### Paper entry

A certifiable paper entry must come from the current generation/policy and the objective `SCHEDULED_FINAL` cohort. Manual observations remain auditable, but cannot replace the scheduled certification entry.

### PRIMARY close

- First usable **Pinnacle sportsbook no-vig** close observed at `<=15 min` before first pitch.
- Captured prospectively.
- Immutable once acquired.
- Used for primary certification CLV.

### EXECUTION close

- First verified-fresh same-book executable close observed at `<=15 min`.
- Captured independently from PRIMARY.
- Immutable once acquired.
- Used as the secondary execution-quality CLV measure.

PRIMARY and EXECUTION can arrive in different snapshots. One must never overwrite or refresh the other. Certification freshness is checked independently for both evidence components.

## Evidence ledgers

Pulsar separates four concepts:

- **Prediction performance** — Brier, LogLoss, calibration, run-error diagnostics and research dashboard metrics in `data/v14_performance.json`.
- **Primary sharp benchmark** — Pinnacle no-vig paired evidence in `data/v14_sharp_benchmark_report.json`.
- **System-authorized/paper evidence** — prospective immutable game×market entries and independent PRIMARY/EXECUTION close components.
- **Real execution** — explicit user/external execution facts in `v14/executed_bet_ledger.py`; production prediction code does not fabricate or auto-populate real wagers.

`data/v14_betting_certification.json` generated through `v14.certification.load_status()` is the authoritative persisted betting-certification artifact. Any certification-like block embedded in a general performance/dashboard artifact is diagnostic only and must not be used to authorize a bet.

## Betting certification

Software production readiness and betting certification are separate.

Current strict gates include, per market where applicable:

- at least 600 settled current-policy games globally;
- at least 400 observations per market;
- ECE <= 0.05 on the certifiable cohort;
- at least 400 paired Pinnacle observations with positive paired Brier evidence;
- at least 100 paper PRIMARY certification-CLV observations;
- at least 50 same-book EXECUTION-CLV observations;
- positive CLV confidence bounds;
- market-specific freshness/drift checks;
- fresh PRIMARY and EXECUTION evidence independently.

Historical, manual, stale or wrong-policy evidence cannot silently certify the current policy.

## Coverage / selection-bias reporting

`v14/coverage_ledger.py` is audit-only. It cannot authorize a bet.

The coverage report distinguishes:

- raw snapshot observations versus first observation per unique game;
- `MANUAL`, `SCHEDULED_FINAL` and legacy/unknown provenance;
- current model generation versus excluded legacy generations;
- prediction availability;
- verified-fresh canonical market availability;
- verified-fresh sharp availability;
- verified-fresh execution availability;
- fully market-observable games;
- rejection reasons.

Later successful snapshots do not erase an earlier failure from the first-observation coverage view. Coverage must be inspected before assuming that performance on the analyzable universe generalizes to the full MLB slate.

## Experiment / challenger governance

Research challengers can be evaluated aggressively, but promotion claims are constrained.

- Experiments are preregistered in an append-only registry.
- Promotion evidence must be post-registration.
- Promotion evidence must match the current generation and probability policy.
- Certifiable prospective promotion evidence must identify `SCHEDULED_FINAL`, FINAL timing and first snapshot per game.
- Historical results can nominate a challenger but cannot automatically promote it.
- No challenger can silently overwrite the champion.
- A predictive promotion requires an explicit new generation/policy decision.

## API-cost controls

The frequent scheduled workflows are designed to wake cheaply.

- Paid Odds acquisition is gated locally before network calls whenever possible.
- Scheduled FINAL entry capture has a persistent daily budget and cooldown.
- Close capture has a separate persistent daily budget.
- Budget is reserved before the paid endpoint is called, so a crash cannot create uncounted paid retries.
- One due Odds snapshot is shared across close consumers.
- PRIMARY and EXECUTION missing components may be completed independently without rewriting already-acquired components.

The code tracks request-equivalent snapshots rather than guessing a vendor credit price that may change externally.

## Main V14 modules

- `v14/acquisition.py` — MLB/Odds acquisition, aliases and time-aware event matching.
- `v14/mlb_inputs.py` — native team/starter/lineup/bullpen/environment inputs.
- `v14/structural.py`, `v14/run_stack.py`, `v14/context_overlay.py` — champion run construction.
- `v14/distribution.py` — regulation scoring plus explicit extra-inning settlement.
- `v14/probability_calibration.py` — shadow calibration research; production activation requires a new policy.
- `v14/uncertainty.py`, `v14/uncertainty_fit.py` — empirical decision-safety bands.
- `v14/market_lines.py`, `v14/sharp_market.py`, `v14/execution_market.py` — post-model market state.
- `v14/decision.py` — fail-closed candidate decision diagnostics.
- `v14/tracking.py` — exact-policy prediction tracking, settlement and performance dashboards.
- `v14/paper_ledger.py`, `v14/bet_ledger.py`, `v14/executed_bet_ledger.py` — research, authorization and real-execution boundaries.
- `v14/close_components.py`, `v14/cost_aware_close_capture.py` — independent close evidence and paid-call orchestration.
- `v14/certification.py` — authoritative market-specific statistical certification.
- `v14/certification_timing.py` — shared FINAL/SCHEDULED_FINAL timing contract.
- `v14/coverage_ledger.py` — selection/coverage audit reporting.
- `v14/research_registry.py`, `v14/promotion_guard.py` — preregistration and fail-closed promotion governance.
- `v14/statcast_base.py`, `v14/statcast_enrichment.py`, `v14/statcast_pit_backfill.py` — V14-native Statcast research pipeline.
- `v14/champion_manifest.py` — source fingerprint guard for champion probability files.
- `v14/preflight.py` — production-critical regression gate.

## Workflows

Active V14 workflows:

- `mlb-bot.yml` — manual analysis plus gated scheduled FINAL acquisition.
- `v14-performance.yml` — settlement, performance, strict evidence refresh and challenger research.
- `v14-close-capture.yml` — prospective cost-aware PRIMARY/EXECUTION close capture.
- `v14-statcast-refresh.yml` — enriched PIT Statcast shadow data refresh.
- `v14-reference-data-smoke.yml` — reference-data provider checks.
- `v14-ci.yml` — complete V14 regression + historical/PIT/provider smoke suite.
- `v14-production-workflow-guard.yml` — guard for production workflow changes.

Legacy V11/V13 code remains only where still needed for frozen reference-data construction or rollback reproducibility. Its regression CI is path-scoped so ordinary V14 work does not rerun the entire historical stack.

## Common commands

```bash
python -m py_compile v14/*.py
python -m v14.preflight
python -m unittest discover -s tests -p 'test_v14_*.py' -v
python -m v14.production_runtime --target-date YYYY-MM-DD
python -m v14.tracking snapshot --payload runtime/v14/discord_payload.json
python -m v14.tracking settle
python -m v14.paper_ledger settle
python -m v14.coverage_ledger report
```

## Change policy

The current champion should remain frozen while prospective evidence accumulates.

A predictive change must be point-in-time safe, preregistered where appropriate, evaluated on untouched chronological/prospective evidence and compared on identical games. Shadow/challenger features can be collected aggressively, but champion probability changes require a new explicit generation/policy decision after out-of-sample evidence.

Governance/data-hardening patches must not be presented as predictive improvements unless scoring evidence actually demonstrates one.
