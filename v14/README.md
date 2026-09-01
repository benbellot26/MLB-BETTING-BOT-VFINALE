# Pulsar V14

Current software identity:

- V14.6.0
- `pulsar-v14-context-v4-all-stats`
- `pulsar-v14-probability-policy-v1`

`v14/__init__.py` and the champion manifest are the source of truth.

## Runtime

`acquisition -> mlb_inputs -> structural/run_stack -> context_overlay/all_stats -> distribution -> calibration policy -> uncertainty -> market separation -> decision/certification -> production_runtime`

Market probability is not a baseball predictive feature.

## Production vs research

Production probability files are frozen under the current generation. Challengers and
diagnostics are shadow-only unless an explicit future generation/policy promotion is
accepted.

Research-only modules include:

- `structural_sensitivity.py`
- `ablation_shadow.py`
- `ablation_report.py`
- `research_diagnostics.py`
- challenger modules
- `research_registry.py`

`champion_dashboard.py` is read-only and cannot authorize a bet.

## Validation

```bash
python -m py_compile v14/*.py
python -m v14.reproducibility_guard --fail-on-external
python -m v14.preflight
python -m unittest discover -s tests -p 'test_v14_*.py' -v
```

## Reproducibility

The V14 core is standard-library only on Python 3.12. See `../REPRODUCIBILITY.md`.

## Research protocol

See `../research/V14_EXPERIMENT_PROTOCOL.md`.

## Architecture

See `../ARCHITECTURE.md`.

## Betting status

Do not infer betting readiness from this README. The authoritative runtime state is
`data/v14_betting_certification.json`.
