# Predictive Analytics Mode

## Objective

The production bot is an MLB probability engine first and a betting selector second.

The primary objective is to make announced probabilities as close as possible to the true long-run frequency of the modeled event. A single loss does not invalidate a 65% forecast; calibration is evaluated across many comparable forecasts.

Primary validation metrics:

- Brier score: lower is better.
- LogLoss: lower is better and strongly penalizes unjustified confidence.
- Calibration / ECE: predicted probability bands should match observed frequencies.
- Point-in-time integrity: only information available at the forecast timestamp may be used.

Economic metrics such as executable-price EV, CLV and realized P/L remain useful secondary diagnostics, but they must not be allowed to contaminate the baseball probability itself.

## Probability products

Every analyzed market should preserve separate probability products:

1. `p_baseball_raw`: baseball-only probability before empirical calibration.
2. `p_baseball_calibrated`: baseball-only probability after the current calibration layer.
3. `p_market`: de-vigged sharp-market benchmark.
4. `p_posterior`: market-aware ensemble candidate. This is shadow-only until validated.
5. `p_predictive_final`: probability shown as the primary predictive output.

For the current V13.5.2 generation, `p_predictive_final` remains equal to `p_baseball_calibrated`. This is intentional. The market-aware posterior is not promoted from a small sample.

## Posterior promotion rule

The daily post-mortem compares posterior and baseball probability on the same independent settled targets.

A posterior may only become a promotion candidate after at least 300 paired observations for the evaluated market cohort and only when both conditions hold:

- Brier improvement versus calibrated baseball is at least 0.001.
- LogLoss improvement versus calibrated baseball is at least 0.002.

These thresholds identify a candidate for review; they do not silently switch production probability. Any promotion must preserve point-in-time integrity and be validated across phases/markets so a local short-term improvement does not create a global regression.

## Discord output

The main game message is analytics-first. It shows the primary probability, uncertainty interval, raw/calibrated baseball probability, sharp benchmark, posterior shadow candidate, calibration status, model-data quality, and available price context.

Ranking and betting-plan Discord cards are intentionally suppressed in predictive analytics mode. The user remains responsible for interpreting the probabilities and deciding whether a quoted price creates a sufficiently attractive opportunity.

## Profitability

Accurate probabilities are necessary but do not guarantee profitability. Long-run profitability also requires obtaining prices whose implied break-even probability is below the true event probability, while accounting for uncertainty, limits, execution quality and variance.
