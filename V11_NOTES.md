# MLB Betting Bot V11 — Predictive development branch

## V11.0.0 validated foundation

The validated V10.0.15 baseball engine remains the independent prediction core. V11 adds the sharp-market benchmark, point-in-time validation, bookmaker-level learning and the evidence-gated ML blend. Winamax remains execution/information only; Pinnacle, Betfair Exchange EU, Matchbook and BetOnline are the default sharp references.

The model+sharp blend remains OFF unless its chronological holdout passes the minimum sample, Brier, LogLoss, paired-bootstrap and multi-reference gates. The first complete V11 GitHub Actions run passed successfully; the branch remains intentionally separate from `main` while predictive development continues.

## V11.1.0 — six baseball upgrades

The next modification adds all six requested predictive blocks in shadow first. None may alter official picks merely because the feature exists.

1. **Reliever-level bullpen availability**
   - individual reliever workloads for D-1 / D-2 / D-3;
   - pitch counts and consecutive-day use;
   - probable availability rather than a team-level bullpen average;
   - extra penalty when a high-quality/high-leverage reliever is likely unavailable.

2. **Starting-pitcher recent form with shrinkage**
   - recent starts are compared with season skill rather than replacing it;
   - FIP-like strikeout/walk/home-run information is preferred to raw recent ERA;
   - recent innings/depth is included;
   - small recent samples are shrunk back toward season performance.

3. **Directional wind**
   - Open-Meteo wind direction is converted from meteorological `from` direction to travel direction;
   - wind is projected onto the ballpark home-plate-to-center-field azimuth when that venue field is available;
   - out-to-center wind raises the shadow run expectation, in-from-center wind lowers it, crosswind has limited effect;
   - fixed-roof/dome games receive no outdoor wind correction.

4. **Lineup provenance and quality**
   - lineup state becomes `PROJECTED`, `PARTIAL` or `OFFICIAL_FEED`;
   - the posted lineup is evaluated against the club's normal high-usage hitters;
   - batter OPS is shrunk toward league average when plate-appearance samples are small;
   - important regulars missing from the posted lineup are explicitly journaled.

5. **Lineup x opposing starter interaction**
   - batting handedness is evaluated against the opposing starter's throwing hand;
   - switch hitters and opposite-handed hitters receive platoon-advantage treatment;
   - matchup strength is weighted by batting-order position and hitter quality;
   - the matchup correction is separated from the lineup-strength correction to avoid hiding which feature adds value.

6. **Shadow validation / ablation before activation**
   - persist the independent base probability and separate shadow variants for bullpen, starter, lineup, platoon matchup and the combined model;
   - persist base and shadow run expectations when the underlying run means are available;
   - grade one closest-to-first-pitch observation per final game;
   - compare Brier, LogLoss and paired bootstrap evidence for ML;
   - compare per-team run MAE for run projections;
   - report feature coverage and individual ablations;
   - no automatic official activation: a future production change still requires explicit evidence-gate integration.

## V11.1 activation philosophy

The new baseball layer is deliberately a **relative correction layer** so it does not simply duplicate information already present in V10. For example, starter recent form is measured relative to season skill, lineup strength is measured relative to the club's normal lineup, and bullpen impact focuses on current availability/fatigue.

The planned future-candidate gate is conservative: at least 80 final point-in-time games, at least 30 chronological holdout games, Brier gain of at least 0.0015, paired bootstrap probability of improvement of at least 85%, no worse LogLoss, and sufficient full-feature coverage. Passing that gate would only make the feature set a candidate for production; it would not silently change official picks.

## Existing V11 sharp benchmark

- sharp books: Pinnacle, Betfair Exchange EU, Matchbook, BetOnline;
- Winamax: execution/information only;
- Betclic, Unibet, PMU and NetBet: auxiliary line sources;
- probabilities are de-vigged book by book;
- stale feeds and outliers receive lower weight;
- empirical book weights require at least 80 independent settled observations and are capped to +/-15%;
- the production ML sharp blend itself still requires at least 40 chronological holdout games, Brier gain >= 0.0015, paired-bootstrap gain probability >= 85%, LogLoss no worse, and >= 60% multi-sharp-reference coverage.

## GitHub safety

`main` remains untouched. Development stays on `agent/v11-predictive-core` / PR #20. The workflow remains manual (`workflow_dispatch`) and data commits occur only after successful validation.
