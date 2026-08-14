# MLB Betting Bot — V12.2 Professional Validation Foundation

V12.2 keeps the interpretable structural baseball baseline while hardening the full decision chain around reproducible point-in-time data, phase-specific learning, end-to-end Champion/Challenger validation, empirical uncertainty, bankroll-aware selection, explicit recommendation lifecycle and CLV evidence.

## Production architecture

- `v11/core.py` — MLB/The Odds API transport, explicit `as_of`, complete HTTP source recording/replay, Winamax prices and Discord transport.
- `v11/engine.py` — retained structural compatibility layer.
- `v11/engine_v12.py` — production engine with raw/current + multi-season starter priors, three-day bullpen context, phase-specific residual model, correlated run-environment score matrix, dynamic tail truncation and fixed canonical evaluation lines.
- `v11/context.py` — weather and three-day bullpen availability context.
- `v11/market.py` — point-in-time de-vig consensus, strict timestamp freshness, exchange commission adjustment, book weighting and disagreement-aware blending.
- `v11/pro_model.py` — coherent missing-value handling, phase-specific residual/calibration models, push calibration, empirical uncertainty, end-to-end holdout validation, walk-forward promotion gate and model provenance metadata.
- `v11/data_quality.py` — independent data quality based on actually usable lineup/starter/team data, not merely identities/counts.
- `v11/selector.py` — uncertainty-adjusted price gate, fractional Kelly, persistent recommendation exposure and duplicate prevention. Official combos are disabled until a dependence model is validated.
- `v11/storage.py` — run snapshots, source replays, market snapshots, recommendation/wager lifecycle ledger and CLV observations.
- `v11/journal.py` — prediction journal and settlement compatibility layer.
- `v11/backtest.py` — strict V12.2 cohort evaluation with WIN/PUSH/LOSS multiclass scoring.
- `v11/train.py` — explicit Champion/Challenger generation and promotion.
- `v11/discord_v12.py` — recommendation cards and data-health reporting.
- `tests/test_v11.py` — regression, statistical and production-safety invariants.

## Probability stack

1. immutable structural run baseline;
2. phase-specific learned residual only after chronological improvement;
3. Negative Binomial scoring with a shared run-environment factor, so home and away scores are not conditionally independent;
4. dynamic score-tail truncation rather than a fixed hard matrix cut;
5. fresh sharp-market de-vig blend at an explicit historical `as_of`;
6. phase/market side calibration plus push calibration;
7. empirical uncertainty from reliability bins, sharp disagreement and data quality;
8. conservative execution probability used for EV, minimum price and Kelly sizing.

EARLY, LATE and FINAL snapshots are trained separately while train/holdout splits remain grouped by `game_pk`, preventing the same game from leaking across validation boundaries.

## Champion / Challenger policy

A Challenger is **not** promotable merely because one component improves. Promotion requires:

- V12.2-compatible rows only (`engine_version`, schema and feature schema must match);
- an external end-to-end holdout where the deployed stack improves Brier and LogLoss;
- multiple positive future walk-forward windows;
- compatible model provenance metadata and feature-schema hash;
- sufficient live evidence at promotion time.

The model artifact stores dataset fingerprint, training cutoff, engine/schema versions, feature-schema hash and producing Git commit when available.

If a Champion file exists but is corrupt or schema-incompatible, the betting data-quality gate fails closed. Absence of a Champion is different: structural-only operation is allowed while evidence is collected.

## Recommendation and wager lifecycle

The bot does not claim that publishing a Discord recommendation means a bookmaker wager was placed.

Lifecycle:

`PROPOSED → PUBLISHED → CONFIRMED_PLACED → WIN / LOSS / PUSH`

- `PROPOSED`: selected and durably persisted before Discord.
- `PUBLISHED`: Discord publication succeeded.
- `CONFIRMED_PLACED`: explicit external/user confirmation that the wager was actually placed.
- settlement and ROI use only confirmed wagers.

Manual confirmation is available with:

```bash
python -m v11.runner --confirm-placed '<bet_key>' --price 1.91
```

## Betting policy

A single recommendation requires:

- usable team/starter/lineup data above the DQ threshold;
- fresh sharp references;
- an exact executable Winamax line;
- uncertainty-adjusted positive value and minimum edge;
- no already-published recommendation on the same game;
- fractional Kelly above the minimum unit size;
- room under persistent daily exposure limits.

Official combinés are disabled in V12.2 because multiplying leg probabilities assumes independence that has not yet been validated. Research combo calculations can exist, but they cannot enter the official portfolio.

## Point-in-time source replay and CLV

Every production/snapshot run can record **all HTTP responses actually consumed**: schedule, Odds API, team/player stats, boxscores, starter priors, bullpen lookups and weather. API secrets are scrubbed from archived request URLs.

Source bundles under `runtime/v11/source_replays/` can be replayed without using the current clock:

```bash
python -m v11.runner --replay-dry-run runtime/v11/source_replays/<file>.json.gz
```

Market freshness and game phase use the recorded historical `as_of`, not `datetime.now()`.

`.github/workflows/market-snapshot.yml` checks for published recommendations every 15 minutes. It only calls the APIs when something is open, then captures T-60, T-15 and close-candidate trajectories without generating or republishing picks.

## Evidence boundary

The system reports `COLLECTING` until it has at least the configured number of confirmed settled wagers and close-candidate CLV observations. A green CI validates software invariants; it is **not** treated as evidence of predictive profitability.

Historical information that was never captured is never reconstructed from future data.

## Validation

```bash
python -m py_compile v11/*.py tests/test_v11.py
python -m unittest tests.test_v11
python -m v11.runner --self-test
python -m v11.train --dry-run
python -m v11.backtest
```

`.github/workflows/ci.yml` runs on pushes and pull requests. `.github/workflows/mlb-bot.yml` is the explicit production workflow; `.github/workflows/market-snapshot.yml` is the CLV/source snapshotter.
