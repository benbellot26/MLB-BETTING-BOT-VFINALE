# V14 experiment protocol

This protocol controls predictive research. It is intentionally stricter than “try an
idea and inspect the backtest.”

## Before the first eligible observation

A new strict-governance experiment must seal:

- immutable experiment id;
- falsifiable hypothesis;
- exact model/module and feature set;
- training and validation periods;
- one primary metric and declared secondary metrics;
- success rule;
- **minimum independent games**;
- **analysis plan**;
- **stopping rule**;
- **promotion scope**;
- code commit SHA;
- multiplicity/research-budget family.

`v14.research_registry` fingerprints this immutable specification. Changing a hypothesis,
feature definition, threshold or analysis rule after looking at prospective outcomes
requires a **new experiment id**.

Existing preregistrations created under the earlier registry contract are not
retroactively rewritten; the registry audit labels them as legacy governance.

## Evidence hierarchy

1. Native prospective, exact-generation, exact-policy observations.
2. Chronological untouched holdouts declared before scoring.
3. Historical/PIT reconstructions for nomination and debugging.
4. Exploratory/post-hoc slices for hypothesis generation only.

A lower tier cannot silently certify a higher-tier claim.

## Multiple testing / researcher degrees of freedom

Experiments declare a `multiplicity_family` / `research_budget_family`. Many near-identical
challengers should not be interpreted as independent discoveries. Only preregistered
primary metrics can support promotion; secondary/regime slices are supporting diagnostics.

## Sample size is not a pass button

Reaching 250, 400 or 600 observations does not certify a model. A decision must combine
sample size with calibration, proper scores, paired sharp comparison, CLV where relevant,
temporal/regime stability, execution quality and confidence intervals.

## Ablation protocol

`V14-ABLATION-01` is the sealed simplification experiment. Counterfactuals are computed
only from persisted pregame PIT components and never use outcomes or market probabilities.
Only predictions made after experiment registration count toward its promotion evidence.
