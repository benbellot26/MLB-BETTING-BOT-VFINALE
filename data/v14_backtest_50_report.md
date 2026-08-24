# Pulsar V14 — 50-game V13 reference backtest

- Reference games: **50** (validation block 0)
- Historical V13 generation: `v13.5.2-gen-structural-nb-independent-transfer-v2`
- Same as current V13.10 champion: **False**
- Exact current contextual snapshots available: **0/50**
- Games where V14 contextual overlay actually changed run means: **0**
- CI run: **success** (`Pulsar V14 50-Game Backtest`, run 32744331954)

## Overall market-observation comparison

| Metric | V13 historical | V14 shadow | Improvement (positive = V14 better) |
|---|---:|---:|---:|
| Brier | 0.2434145054 | 0.2434145073 | -0.0000000020 |
| Log Loss | 0.6807495594 | 0.6807495628 | -0.0000000034 |
| Accuracy @ 50% | 0.5461538462 | 0.5461538462 | 0 |

The maximum absolute probability difference across all evaluated observations was `0.000000491` probability, or about `0.0000491` percentage point. The two probability engines are therefore effectively identical on this historical block.

## By market

| Market | n | V13 Brier | V14 Brier | Δ Brier | V13 LogLoss | V14 LogLoss | Δ LogLoss | Accuracy V13/V14 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ML | 50 | 0.2580831350 | 0.2580831187 | +0.0000000163 | 0.7094941539 | 0.7094941209 | +0.0000000330 | 46% / 46% |
| RUNLINE | 50 | 0.2190997544 | 0.2190997671 | -0.0000000127 | 0.6329103336 | 0.6329103610 | -0.0000000275 | 72% / 72% |
| TOTAL | 30 | 0.2594913744 | 0.2594913888 | -0.0000000144 | 0.7125739449 | 0.7125739690 | -0.0000000241 | 40% / 40% |

Only 30 TOTAL observations are included because the strict V14 display/distribution contract accepts half-run totals; whole-run total observations were not forced into the comparison.

## Interpretation

This test validates the V14 distribution/parity layer on the exact 50-game reference block. It does **not** validate the new Quantum-inspired contextual additions because the committed V13 feature store contains no eligible starter/lineup/bullpen snapshot for any of those 50 historical games.

Accordingly, the contextual overlay was a strict no-op on all 50 games. No gain or loss in this report may be attributed to Starter Vulnerability, confirmed lineup/pitch-mix, bullpen stress, H2H or recent-form modules.

The historical reference itself was produced by `v13.5.2-gen-structural-nb-independent-transfer-v2`, not by the current V13.10 champion generation. A true current-V13.10-vs-contextual-V14 retrospective test would require preserved point-in-time player-level snapshots for those dates. Reconstructing missing identities or lineups from final-game data was deliberately rejected because it would introduce look-ahead leakage.
