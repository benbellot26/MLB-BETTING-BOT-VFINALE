# V13 audit implementation map

This document maps the 15 audit findings to concrete V13 changes.

1. **No compatible learned evidence** — V13 calibration compatibility is based on a predictive contract and saved baseball-only pregame probability, not software version. `v13_train.py` can reuse safe V12.3 `p_learned` rows.
2. **1,801 historical games not directly usable** — `historical_migration_v13.py` classifies rows as feature-trainable, calibration-migratable, diagnostic-only or rejected. No relabeling of incompatible V10 evidence is allowed.
3. **Heuristic baseball weights** — `feature_learning_v13.py` provides a regularized learned residual layer. It is candidate-only until strict V13 validation proves improvement; the structural formula remains fallback, not claimed truth.
4. **Model/market circularity** — `p_baseball_raw`, `p_baseball_calibrated`, `p_market` and `p_posterior` are separate. Edge/value uses only calibrated baseball probability against an independent market quote.
5. **Historical overconfidence** — `calibration_baseball_v13.py` trains baseball-only Platt/beta challengers chronologically and keeps identity when calibration does not improve Brier/LogLoss without unacceptable ECE regression.
6. **Calibration architecture without evidence** — phase/market/global fallback is retained, but activation needs canonical independent targets and larger samples. Current software may operate identity-calibrated while evidence accumulates.
7. **V12.4 unproven modules** — V12.4 remains shadow-only. Existing production isolation stays active and V13 does not consume V12.4 ensemble probability for edge discovery.
8. **Fixed run distribution parameters** — `distribution_learning_v13.py` estimates NB dispersion and shared environment sigma as candidates; they are not promotable without the strict outer validation gate.
9. **Sharp market handling** — existing fresh timestamped de-vig sharp consensus is retained as independent benchmark. It may enter `p_posterior` for pure forecasting, never `p_baseball_calibrated`.
10. **Point-in-time leakage risk** — `point_in_time_v13.py` and `asof_stats_v13.py` require explicit `as_of`, provenance and snapshot/cutoff capability; historical current-season lookups fail closed without replay/snapshot.
11. **Weak promotion thresholds** — `validation_v13.py` requires >=600 compatible games, >=200 outer-holdout games, >=5 day-block walk-forward windows, >=80% positive windows, positive paired-bootstrap Brier lower bound, non-negative LogLoss gain and per-market/calibration safety.
12. **Versioning invalidates useful history** — `probability_contract_v13.py` separates predictive compatibility from software version. Discord/selector/CI changes no longer invalidate pregame probability evidence.
13. **Monkey-patch complexity** — `pipeline_v13.py` introduces an explicit `PregameSnapshot -> BaseballModel -> ScoreDistribution -> BaseballCalibration -> MarketBenchmark` probability pipeline. The runtime wrapper is transitional compatibility glue around the existing production transport.
14. **Pick-first product** — `probability_report_v13.py` and `discord_v13.py` put baseball calibrated/raw probability, 90% interval, sharp probability and model-market gap before price/EV.
15. **Professional target architecture** — `v13_entry.py` is the new production entrypoint; `.github/workflows/mlb-bot.yml` runs/trains/persists V13 while keeping existing V11.5/V12.4 research shadows isolated.

## Additional corrections

- **Extra innings**: `extra_innings_v13.py` defaults ties to a neutral 50/50 extra-inning prior instead of a fixed 52% home split until a dedicated prior is validated.
- **Calibration independence**: at most one canonical side per market/game/phase is used for calibration so complementary outcomes and alternate lines do not inflate sample size.
- **Probability persistence**: V13 fields are copied into the historical journal so future calibration is based on the exact probability shown at prediction time.
- **Uncertainty**: `uncertainty_v13.py` combines calibration sample size, reliability error, sharp disagreement and DQ with a non-zero uncertainty floor.
- **Production invariant**: CI rejects a result when legacy `p_effective` diverges from `p_baseball_calibrated` or when a market-derived source is labeled as baseball probability.

## Evidence boundary

V13 is a methodological correction, not a retroactive claim of profitability. Until enough V13-compatible observations exist, calibration may remain identity and learned feature/distribution candidates remain inactive. That conservative state is expected and preferable to promoting unproven complexity.
