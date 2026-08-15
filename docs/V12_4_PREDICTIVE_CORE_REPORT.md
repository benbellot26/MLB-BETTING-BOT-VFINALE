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
| 6 | Weather × park interaction | **ADDED** | Moist-air density from temperature/humidity/surface pressure; gust-aware wind split into outfield and crosswind components; MLB field-relative wind preferred, with MLB venue azimuth + Open-Meteo vector fallback; park-sensitivity scaling and explicit roof-state safety. | If a retractable-roof game has no verifiable current roof state, outside weather remains neutral rather than guessed. This is a runtime data-availability safeguard, not a missing model component. |
| 7 | Uncertainty decomposition | **ADDED** | Separate starter, lineup, bullpen, Statcast-coverage, sharp-dispersion and V11/V12-disagreement components; combined uncertainty shrinks probabilities toward 50%. | Component weights remain challenger assumptions until enough settled V12.4 evidence exists. |
| 8 | Model ensemble | **ADDED — RESEARCH ONLY** | V12.4 core + official V12 + V11.5 shadow + sharp probability, normalized over available sources and shrunk by uncertainty. | Fixed initial weights are not eligible for production promotion without out-of-sample evidence. |

## Weather implementation v2

The weather module no longer applies independent temperature, humidity and wind bonuses. It first estimates moist-air density using temperature, relative humidity and surface pressure. Lower-density air increases the carry component; higher-density air reduces it.

Wind direction uses the following hierarchy:

1. MLB hydrated game weather when it supplies a field-relative label such as `Out To CF`, `In From CF`, `L To R` or `R To L`;
2. otherwise MLB venue `azimuthAngle` combined with Open-Meteo meteorological wind direction to project the wind vector onto the home-plate-to-center-field axis;
3. if neither direction source exists, wind direction is neutral instead of inferred.

Wind gusts can strengthen the projected component within a bounded multiplier. Crosswind is tracked separately and receives only a small bounded effect. Existing park factor is not counted twice: it only scales weather sensitivity in this module.

Roof handling is explicit. Open-air venues use outside weather; fixed domes neutralize it; retractable venues use a verified game-level roof state or an explicit environment override. Unknown retractable-roof state fails neutral.

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
