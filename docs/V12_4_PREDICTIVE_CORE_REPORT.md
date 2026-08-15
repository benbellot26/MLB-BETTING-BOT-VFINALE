# V12.4 Predictive Core — implementation report

## Status

V12.4 is implemented as a **research-only shadow challenger** beside the official V12.3.2 Champion. It reads the same point-in-time game context and market snapshot, but it cannot select, stake, publish, block, or modify an official V12.3.2 recommendation.

| # | Improvement | Status | What is implemented | Remaining limitation |
|---|---|---|---|---|
| 1 | Platoon / handedness | **ADDED** | Player-level lineup splits versus the opposing starter hand, batting-order weighting, sample-size shrinkage, fail-neutral fallback. | MLB split coverage can be incomplete early in a season; missing samples are neutral rather than guessed. |
| 2 | Statcast expected metrics | **ADDED** | Point-in-time Baseball Savant aggregate provider; lineup and opposing-starter xwOBA signal; bounded run adjustment; replay-recordable; fail-neutral. | Provider availability/HTML schema can change; parser fails closed to a neutral adjustment if the expected table is absent. |
| 3 | Bullpen player-level | **ADDED** | Individual reliever season ERA/WHIP quality, three-day pitch load, consecutive use, probable availability and expected bullpen share. | Role labels such as closer/setup are not treated as ground truth because MLB Stats does not expose a stable live role field. |
| 4 | Lineup player-level | **ADDED** | All available starting hitters are valued individually with batting-order exposure and a bounded non-linear offensive adjustment. | Still uses OPS as the always-available player baseline when richer Statcast data are unavailable. |
| 5 | Starter expected innings | **ADDED** | Expected IP derived from season workload/starts, skill and sample shrinkage; starter/team-pitching contribution is rebalanced by projected innings. | No manager-specific hook model yet; prediction is bounded and empirical rather than a dedicated survival model. |
| 6 | Weather × park interaction | **PARTIAL** | Temperature, humidity and wind magnitude interact with park factor; retractable/covered parks fail neutral unless explicitly marked roof-open; wind direction is stored. | **Not added:** directional run adjustment from wind direction, because verified center-field bearings/roof state are not yet available for every park. No fabricated geometry is used. |
| 7 | Uncertainty decomposition | **ADDED** | Separate starter, lineup, bullpen, Statcast-coverage, sharp-dispersion and V11/V12-disagreement components; combined uncertainty shrinks probabilities toward 50%. | Component weights remain challenger assumptions until enough settled V12.4 evidence exists. |
| 8 | Model ensemble | **ADDED — RESEARCH ONLY** | V12.4 core + official V12 + V11.5 shadow + sharp probability, normalized over available sources and shrunk by uncertainty. | Fixed initial weights are not eligible for production promotion without out-of-sample evidence. |

## Ablation design

Each run stores independent comparison variants so the impact of every family can be measured rather than inferred from the combined model:

- `baseline_v1232`
- `only_platoon`
- `only_statcast`
- `only_bullpen_player`
- `only_lineup_player`
- `only_starter_ip`
- `only_weather_park`
- `all_core`
- `ensemble`

Settled variants are compared with accuracy, Brier score, LogLoss and hit rate above 55% confidence. The shadow report requires at least **75 settled games before any consideration of production influence**; this is a minimum evidence threshold, not an automatic promotion rule.

## Production isolation

V12.3.2 remains the official Champion. V12.4 has `affects_v12_selection = false`, is wrapped fail-open, and does not patch the selector, Kelly staking, bankroll controls, Discord recommendation selection, confidence floors, 1.40 reference-price floor, or sharp-value gate.

## Promotion policy

No V12.4 module should become official simply because its in-sample or single-night hit rate is better. Promotion requires point-in-time settled evidence and comparison against the V12.3.2 baseline. The intended decision order is:

1. validate each ablation individually;
2. reject modules that degrade Brier/LogLoss materially;
3. validate `all_core` and `ensemble` out of sample;
4. keep V12.3.2 official until the challenger demonstrates a durable improvement;
5. only then integrate proven components into a future production generation.
