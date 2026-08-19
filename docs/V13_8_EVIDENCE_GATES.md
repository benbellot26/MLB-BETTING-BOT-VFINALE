# V13.8 evidence-only gates

The 52 audit points are engineering-closed by V13.8, but the following claims remain evidence-gated and cannot be declared statistically closed until authenticated samples satisfy their thresholds.

- Rich native production promotion: native-live minimum and holdout/proper-score gates from `v13_rich_native_train`.
- Baseball calibration: strict native global/market/phase sample floors are retained.
- Posterior Sharp: remains shadow until live/PIT evidence and out-of-sample proper-score improvement are sufficient.
- Empirical uncertainty coverage: coverage validator exists; activation requires enough independent native observations.
- Learned bookmaker weights: requires at least 300 authenticated PIT book/outcome rows plus out-of-sample confirmation.
- Extra-innings prior: remains 0.50 until at least 200 authenticated extra-inning examples.
- Model-market gap/CLV proof: diagnostics exist, but no economic or predictive claim is made before adequate independent targets.
- Inning-level profile: learner exists but requires authenticated inning-by-inning labels.
- Dynamic calibration: research implementation exists, production activation remains out-of-sample gated.

No gate is weakened by reconstructed historical volume.
