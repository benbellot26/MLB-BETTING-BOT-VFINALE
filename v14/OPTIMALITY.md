# V14 optimality contract

V14 is not defined as "more features than V13". It is the smallest MLB probability engine that can repeatedly beat the frozen V13.10 champion on genuine chronological out-of-sample evidence.

## Immutable principles

1. **Baseball probabilities are baseball-only.** Sportsbook/market probabilities are benchmark metadata, never run-model or calibration features.
2. **Point-in-time or reject.** Every predictive input must be observed and durably attested before first pitch. Postgame labels live in a separate store.
3. **One run model, one score distribution, one coherent surface.** ML, both standard ±1.5 runline pairs, and the canonical half-run total all come from the same score distribution.
4. **One MLB game is one statistical sample.** Complementary sides and paired runlines never inflate sample size.
5. **Shadow before champion.** A candidate may enter shadow only after beating a deliberately simple baseline on untouched data. Production promotion additionally requires beating V13.10 directly on the same games.
6. **No feature by prestige.** Weather, bullpen detail, Statcast, platoon, travel, umpire, park refinements, extra-innings refinements, calibration and distribution changes are added one at a time only when their incremental OOS value is positive and stable.
7. **No forced activation.** Thresholds are never lowered to make a candidate pass.
8. **Simpler wins ties.** If two models are statistically indistinguishable, keep the smaller and more auditable one.

## Stage 1 — Native run-model eligibility for shadow

The minimal native V14 run model uses only:

- home indicator,
- team OPS,
- confirmed/pregame lineup OPS,
- opponent team ERA,
- opponent starter ERA,
- opponent starter WHIP,
- leakage-safe park factor.

It needs at least **300 genuine FINAL PIT games**, including an untouched chronological holdout of at least **60 games**. Ridge strength is selected on validation only. The final holdout is scored once.

It may become `active_for_shadow` only if, versus a train-only home/away league-run baseline:

- RMSE improves,
- Poisson NLL improves,
- paired bootstrap probability of positive MSE gain is at least 90%,
- paired bootstrap probability of positive Poisson-NLL gain is at least 90%.

Passing this stage does **not** make the model production-ready. It only earns the right to challenge V13.10.

## Stage 2 — Direct paired V14 vs V13.10 probability gate

V14 and the frozen V13.10 champion must be evaluated on the exact same latest valid FINAL pregame snapshot and the same separately settled MLB result.

Minimum: **300 paired games**.

For **ML, RUNLINE and TOTAL separately**:

- V14 Brier must be no worse than V13.10,
- V14 LogLoss must be no worse than V13.10,
- paired bootstrap probability of positive Brier gain must be at least 90%,
- paired bootstrap probability of positive LogLoss gain must be at least 90%.

RUNLINE losses are averaged inside each game; they do not count as two observations.

## Stage 3 — Calibration

Identity calibration is the default. A learned calibration layer is allowed only after sufficient independent current-generation evidence exists and only if it improves untouched proper scores without damaging reliability.

A calibration candidate must be fitted outside the final evaluation window and compared against identity on chronological holdout data. If evidence is insufficient or unstable, V14 stays uncalibrated rather than fitting noise.

## Stage 4 — Incremental feature/layer challenges

Every proposed addition is an ablation challenge against the current V14 champion:

`current V14` vs `current V14 + exactly one candidate change`.

Examples:

- bullpen fatigue/availability,
- weather,
- Statcast quality of contact,
- platoon/handedness,
- park-factor refinement,
- travel/rest,
- extra-innings home-win prior,
- score-dispersion parameter,
- richer lineup/player representation.

A candidate is retained only if chronological validation shows a stable incremental gain in the metrics it is expected to improve. A gain confined to one tiny subgroup, one season slice, or one metric with regressions elsewhere is not sufficient.

## Final production promotion

V14 cannot replace V13.10 until all hard blockers are removed and the final frozen V14 candidate has demonstrated:

- full PIT/provenance compliance,
- independent native run model,
- coherent eight-probability surface,
- no market leakage,
- stable run RMSE/NLL,
- ML/RUNLINE/TOTAL Brier and LogLoss no worse than V13.10,
- reliable calibration/reliability behavior,
- chronological and bootstrap stability,
- no material subgroup collapse,
- operational CI and persistence integrity.

Only then is V14 eligible to become the production champion. Until that point V13.10 remains untouched.
