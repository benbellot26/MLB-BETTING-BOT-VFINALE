# Pulsar V14

V14 is the active production engine.

## Runtime

`acquisition -> mlb_inputs -> structural/run_stack -> context_overlay -> distribution -> validation -> production_runtime -> Discord`

There is no V11/V13 import in the native production path.

## Main files

- `acquisition.py`: MLB/Odds point-in-time acquisition.
- `mlb_inputs.py`: native baseball inputs.
- `structural.py`: structural run means.
- `run_stack.py`: V14 run stack.
- `park.py`: park factor handling.
- `context_overlay.py`: starter, confirmed lineup/matchup and bullpen residual context.
- `distribution.py`: coherent ML/RL/total probability surface.
- `pipeline.py`: model orchestration.
- `production_runtime.py`: production payload and publication.
- `market_edge.py`: post-model fair odds/no-vig/edge/EV diagnostics.
- `tracking.py`: pregame prediction ledger, settlement and performance.
- `preflight.py`: production tests.

## Rules

- market probabilities are never predictive features;
- only point-in-time information is eligible in production;
- missing context is a no-op, not a synthetic neutral score;
- contextual moves are capped;
- predictions are persisted before games and scored only after final results exist;
- V13.10 is rollback/history only.

## Validation

```bash
python -m py_compile v14/*.py
python -m v14.preflight
```

## Production

Use the GitHub Actions workflow `Pulsar V14 Production`.

Live predictions are persisted to `data/v14_predictions.jsonl`. The daily `Pulsar V14 Performance` workflow settles finished games and writes `data/v14_performance.json`.
