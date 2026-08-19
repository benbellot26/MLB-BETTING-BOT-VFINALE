# V13.9 engineering closure

V13.9 converts the earlier conservative **~90 engineering-point estimate** into an explicit, executable acceptance registry: `v11/v139_engineering_closure.py`.

This is intentionally **not** a claim that the original 275-point audit contained a machine-readable sub-list numbered 1 through 90. The older total was approximate. V13.9 makes the engineering scope exact from this point forward so future work can be measured rather than reconstructed from arithmetic.

## Acceptance registry

The V13.9 registry contains exactly 90 engineering checks grouped as follows:

- provider integrity / observability: 16;
- PIT and data contracts: 14;
- architecture / production boundary: 14;
- advanced/native feature paths: 16;
- probability/model safety: 14;
- validation/evidence discipline: 10;
- CI/operations: 6.

`python -m v11.v139_engineering_closure` writes `data/v139_engineering_closure.json` and exits non-zero if any acceptance point is open. CI runs the registry in addition to the normal V12 regression suite, V13 preflight, probability self-test, calibration dry-run and research gates.

## Provider corrections

### Baseball Savant park factors

The prior collector now requests Savant's actual three-season view with `rolling=3`. The former `rolling=1` request was a single-season view and did not match the intended prior contract.

Returned rows are authenticated against the expected completed-season window (for example, a 2026 target must use 2023-2025). Wrong-window rows are rejected, empty parses are visible, and zero validated venue rows fail closed.

### Archived weather

Historical Open-Meteo/ECMWF weather now uses a hardened provider boundary. The forecast run is selected once from the original pregame `as_of` timestamp and is never advanced by a retry. Fallbacks may use another documented ECMWF resolution or a reduced documented variable set, but they use the exact same forecast run.

If all attempts fail, weather remains unavailable and neutral downstream. Reconstructed weather remains `promotion_eligible=false`.

## Explicit V13 engine boundary

`v11/v13_engine.py` adds a runner-facing `V13Engine`. It wraps the already-tested numerical core rather than duplicating it, while giving V13 one explicit architecture boundary for new native/research integrations.

Before research context is attached, all Champion probability fields are snapshotted. If the research attachment changes any of them, analysis fails closed. This makes the current V13.9 research/native work probability-neutral by construction.

The old V12.3/V13 runtime hooks still exist internally as transitional compatibility glue. V13.9 contains and verifies them; it does **not** pretend they have disappeared. Removing those internals entirely is a suitable V14 consolidation task after V13 evidence collection is complete.

## Native research context

`v11/v139_native_context.py` joins advanced V13.8 feature paths to live/PIT-safe sources without feeding them into the Champion probability:

- stable-ID Statcast priors are rejected when generated after `as_of`, when their cutoff is after the game, or when their lookback includes game-day/future pitches;
- MLB roster/transaction snapshots are rejected when observed after `as_of` or dated after the game;
- Savant park factors use only completed seasons before the target season;
- lineup player IDs are preserved as stable IDs;
- roster/IL availability is neutral if no authenticated PIT state is available;
- no market payload or target label is embedded in the native research bundle.

The resulting context is explicitly marked `research_only=true`, `affects_champion=false`.

## Evidence boundary

Engineering closure is separate from statistical closure. V13.9 does not lower any V13/V13.8 evidence threshold, does not activate a challenger because code exists, and does not fabricate historical PIT observations.

The previously pending V13.8 evidence gates remain governed by their own real-data floors, including rich-model promotion, calibration maturity, uncertainty coverage, bookmaker weighting, posterior-Sharp validation, model-market/gap validation and dynamic calibration.

The intended sequence remains:

1. engineering and provider contracts must be green;
2. native evidence accumulates naturally;
3. challengers may promote only when their existing out-of-sample gates pass;
4. V14 can then remove legacy compatibility layers and retain only components that proved useful.
