# V14 optimality contract

V14 is the clean successor to the last V13.10 production champion that works. It must preserve proven V13.10 predictive behavior first, remove legacy second, and improve third. Code reduction is never allowed to create a predictive regression.

## Immutable principles

1. **Champion parity first.** Every active V13.10 production component is ported to clean V14 code before its legacy implementation can be removed.
2. **Unproven legacy stays unproven.** V13 research/shadow/candidate layers do not become V14 baseline merely because they exist.
3. **Baseball probabilities are baseball-only.** Sportsbook/market probabilities are benchmark metadata, never run-model or calibration features.
4. **Point-in-time or reject.** Every target-game predictive input must be observed and durably attested before first pitch. Postgame labels live separately.
5. **One run model, one score distribution, one coherent surface.** ML, both standard ±1.5 runline pairs and the canonical half-run total come from one consistent scoring model.
6. **One MLB game is one statistical sample.** Complementary sides and paired runlines never inflate sample size.
7. **No forced activation.** Evidence thresholds are never lowered to make a candidate pass.
8. **Performance decides cleanup.** Simpler code wins only when predictive performance is statistically equivalent.

## Stage A — V13.10 behavioral parity

Port the frozen production champion behind V14-owned interfaces with no `v11` runtime import.

Required parity blocks:

1. V13.10 structural/run stack and operational adjustments.
2. Leakage-safe prior-season park factor behavior and fallback.
3. Champion run correction behavior that is actually active.
4. Champion score distribution: NB dispersion, common environment mixture and truncation policy.
5. Authenticated extra-innings home-win prior.
6. Standard ML / ±1.5 runline / canonical total probability math.
7. Baseball calibration behavior, including identity while evidence is immature.
8. Complement reconciliation and fail-closed probability surface.
9. PIT/provenance, generation identity, immutable tracking and validation contracts.

Parity is tested on synthetic edge cases and on persisted real champion snapshots. The migration is incomplete while the V14 run stack still consumes V13-produced run means.

## Stage B — Legacy removal

A V11/V12/V13 module may be deleted from the future V14 runtime only after a V14 implementation has passed behavioral parity for the function it replaces.

Old research scripts and compatibility wrappers are not copied unless they still provide unique evidence or validation value. Production, research, evidence and presentation remain separate packages.

## Stage C — Challenger improvements

After parity, every proposed improvement is an ablation challenge:

`current V14 champion` vs `current V14 champion + exactly one candidate change`.

Candidate examples:

- native compact run model,
- historical dispersion replacement,
- bullpen fatigue/availability,
- weather,
- Statcast quality of contact,
- platoon/handedness,
- starter expected IP,
- travel/rest,
- park refinement,
- richer lineup/player representation,
- calibration changes.

A candidate is kept only when chronological OOS evidence shows stable incremental value without material regression elsewhere. A gain confined to one small subgroup, one season or one metric is insufficient.

## Existing V13 candidates

The following remain challengers until their existing or new V14 gates pass:

- historical dispersion candidate around 3.5,
- historical run-mean correction,
- rich starter/platoon/Statcast/bullpen/player residuals,
- market posterior/blends,
- learned calibration before current-generation sample floors are satisfied.

The experimental `v14/run_model.py` is a challenger to the cleanly ported V13.10 run stack, not the default baseline. Beating a league-average baseline is only a shadow-entry condition; replacing the champion requires beating the ported champion directly.

## Final production promotion

V14 cannot replace V13.10 until the final candidate has demonstrated:

- complete end-to-end V13.10 parity for every retained champion behavior,
- no runtime dependency on V11/V12/V13,
- full PIT/provenance compliance,
- coherent eight-probability surface,
- no market leakage,
- run RMSE/NLL no worse than the frozen champion,
- ML/RUNLINE/TOTAL Brier and LogLoss no worse than the frozen champion,
- reliable calibration/reliability behavior,
- chronological and bootstrap stability,
- no material subgroup collapse,
- operational CI/persistence integrity.

Only then can V14 become production champion. After promotion, further simplification still follows the same no-regression rule.
