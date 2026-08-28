# Pulsar V14 — MLB Probability & Decision Engine

Pulsar **V14.5.4** is the current production software line. The champion probability generation remains **`pulsar-v14-context-v3`** with probability policy **`pulsar-v14-probability-policy-v1`**. V14.5.4 hardens data provenance, evidence isolation and research enrichment; it does **not** change champion probability coefficients or promote a challenger.

## Production architecture

`MLB/Odds acquisition -> native structural run model -> bounded context overlay -> score distribution -> ML/RL/Total probabilities -> empirical calibration/uncertainty -> sharp/execution diagnostics -> certification gate -> Discord + immutable evidence ledgers`

The live workflow is `.github/workflows/mlb-bot.yml` (`Pulsar V14 Production`). Market prices are post-model data: they can choose executable lines, benchmark probabilities, calculate edge/CLV and drive decision thresholds, but they are never baseball predictive features.

## Probability contract

- Champion generation: `pulsar-v14-context-v3`.
- Probability policy: `pulsar-v14-probability-policy-v1`.
- Probability schema: `pulsar-v14-probability-v2`.
- Calibration is strictly chronological and can activate only after paired out-of-sample evidence; validated identity is allowed when raw probabilities are already calibrated.
- Certification evidence must match the exact model generation **and** probability policy.
- Integer-total pushes are excluded from binary Brier/LogLoss/calibration evidence.
- No recent winning streak is sufficient reason to retune the champion.

## Data and point-in-time rules

- MLB and Odds events are matched by canonical team identity and start time; doubleheaders must be unambiguous.
- A real `BET` path requires a verifiable Odds event timestamp. Unverified events may remain research-only.
- Every scored prediction satisfies `analyzed_at < game_date`.
- Historical reconstruction is explicitly separated from native-live evidence and cannot satisfy native-live promotion thresholds.
- V14 Statcast enrichment is stable-ID-only and strict `game_date < cutoff`.
- Statcast research stores xwOBA/contact/K-BB data, exact pitch mix, hitter performance by pitch type, hitter performance by opposing pitcher hand, and pitcher performance by batter side. These enrichments remain shadow/challenger-only.
- Weather reconstruction uses point-in-time forecast provenance; post-event observed weather is not substituted for a pregame forecast.

## Decision and market separation

`v14/decision.py` evaluates executable prices only after the baseball probability surface exists. A candidate must clear:

1. model edge versus executable breakeven;
2. lower-bound/robust edge versus executable breakeven;
3. positive model and lower-bound edge versus verified sharp fair probability;
4. market freshness and calibration gates;
5. at least one real sportsbook contributor for a real `BET`;
6. market-specific betting certification.

Until those certification requirements are earned, qualifying candidates remain `RESEARCH_ONLY`.

## Evidence ledgers

Pulsar intentionally separates three concepts:

- **Prediction performance** — Brier, LogLoss, calibration, sharp benchmark and run-error diagnostics in `data/v14_performance.json`.
- **System-authorized/paper evidence** — prospective immutable game×market entries, verified sharp closes and same-book closes.
- **Real execution** — explicit user/external execution facts in `v14/executed_bet_ledger.py`; production prediction code does not fabricate or auto-populate real wagers.

Primary betting-certification CLV is executable entry implied probability to a verified <=15-minute no-vig sharp close. Same-book executable close is retained as a secondary execution-quality measure.

## Betting certification

Software production readiness and betting certification are separate.

Current strict gates include, per the certification contract:

- at least 600 settled current-policy games globally;
- at least 400 observations per market;
- ECE <= 0.05;
- at least 400 paired sharp observations with positive paired Brier evidence;
- at least 100 paper certification-CLV observations;
- at least 50 same-book execution-CLV observations;
- positive CLV confidence bounds and freshness/drift checks.

Historical or stale evidence cannot silently certify the current policy.

## Main V14 modules

- `v14/acquisition.py` — MLB/Odds acquisition, aliases and time-aware event matching.
- `v14/mlb_inputs.py` — native team/starter/lineup/bullpen/environment inputs.
- `v14/structural.py`, `v14/run_stack.py`, `v14/context_overlay.py` — champion run construction.
- `v14/distribution.py` — regulation scoring plus explicit extra-inning settlement.
- `v14/probability_calibration.py` — strict chronological calibration.
- `v14/uncertainty.py`, `v14/uncertainty_fit.py` — empirical decision-safety bands.
- `v14/market_lines.py`, `v14/sharp_market.py`, `v14/execution_market.py` — post-model market state.
- `v14/decision.py` — fail-closed candidate decision diagnostics.
- `v14/tracking.py` — exact-policy prediction tracking, settlement and performance.
- `v14/paper_ledger.py`, `v14/bet_ledger.py`, `v14/executed_bet_ledger.py` — research, authorization and real-execution boundaries.
- `v14/certification.py` — market-specific statistical certification.
- `v14/statcast_base.py`, `v14/statcast_enrichment.py`, `v14/statcast_pit_backfill.py` — V14-native Statcast research pipeline.
- `v14/champion_manifest.py` — source fingerprint guard for champion probability files.
- `v14/preflight.py` — production-critical regression gate.

## Workflows

Active V14 workflows:

- `mlb-bot.yml` — production analysis/publication.
- `v14-performance.yml` — settlement, performance, calibration and evidence refresh.
- `v14-close-capture.yml` — prospective verified close capture.
- `v14-statcast-refresh.yml` — enriched PIT Statcast shadow data refresh.
- `v14-reference-data-smoke.yml` — reference-data provider checks.
- `v14-ci.yml` — complete V14 regression + historical/PIT/provider smoke suite.
- `v14-production-workflow-guard.yml` — guard for production workflow changes.

Legacy V11/V13 code remains only where it is still needed for frozen reference-data construction or rollback reproducibility. Its regression CI is path-scoped so ordinary V14 work does not rerun the entire historical stack.

## Common commands

```bash
python -m py_compile v14/*.py
python -m v14.preflight
python -m unittest discover -s tests -p 'test_v14_*.py' -v
python -m v14.production_runtime --target-date YYYY-MM-DD
python -m v14.tracking snapshot --payload runtime/v14/discord_payload.json
python -m v14.tracking settle
python -m v14.paper_ledger settle
```

## Change policy

A predictive change must be point-in-time safe, evaluated on untouched chronological evidence and compared on identical games. Shadow/challenger features can be collected aggressively, but champion probability changes require a new explicit generation/policy decision after out-of-sample evidence. Governance/data-hardening patches must not be presented as predictive improvements unless the scoring evidence actually demonstrates one.
