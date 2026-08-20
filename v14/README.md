# V14 clean shadow foundation

V14 is a new, minimal MLB probability engine. It does **not** inherit the V11/V12/V13 runtime stack and it does not replace V13.10 until it wins a chronological out-of-sample comparison.

## Production contract

`pregame data -> home/away run means -> one score distribution -> 8 probabilities -> optional validated calibration -> tracking/validation`

The first shadow foundation intentionally contains only the pieces needed to prove that contract:

1. `model.py` — small immutable input/output contracts and fail-closed surface checks.
2. `distribution.py` — one negative-binomial score distribution generating ML, both standard ±1.5 runlines, and one half-run total pair.
3. `shadow.py` — transition adapter that may read V13 run means for paired comparison but forbids V13 probabilities, market probabilities, selector scores, and betting decisions as V14 model inputs.
4. `validation.py` — Brier/LogLoss scoring on four independent canonical targets rather than double-counting complementary sides.

## Eight displayed probabilities

- Away ML / Home ML
- Away +1.5 / Home -1.5
- Away -1.5 / Home +1.5
- Over / Under at the canonical half-run total line

Every pair must sum to exactly 1 within numerical tolerance. Invalid or incomplete surfaces fail closed.

## Explicit foundation assumptions

- Score family: independent negative binomial.
- Baseline dispersion: 7.5 until a replacement independently passes evidence gates.
- MLB regulation ties are split 50/50 for the moneyline foundation. A more detailed extra-inning model must beat this assumption OOS before replacing it.
- Total display lines must be half-run lines; integer lines with pushes are not silently normalized.
- No market probability is a baseball feature.
- No V14 output can affect production, Discord betting selection, or the V13 probability journal.

## Promotion philosophy

V13.10 stays frozen champion. V14 remains shadow until enough paired, current-generation, point-in-time games show that V14 is at least as good on:

- Brier score,
- LogLoss,
- calibration/reliability,
- run projection error,
- ML, RUNLINE and TOTAL separately,
- chronological stability / bootstrap evidence.

A new layer is added to V14 only if its OOS evidence improves the simpler champion. Otherwise it stays research-only or is removed.
