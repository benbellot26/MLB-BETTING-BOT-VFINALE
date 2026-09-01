# Reproducibility contract

Pulsar V14 deliberately keeps its production/research core **standard-library only**.

## Runtime

- Python series: **3.12**
- Project metadata: `pyproject.toml`
- Third-party Python runtime dependencies: **none**
- GitHub Actions are referenced by immutable commit SHA in existing workflows.

A package lock file would currently contain no third-party dependency graph. Instead,
`python -m v14.reproducibility_guard --fail-on-external` scans every top-level V14
module and fails if an undeclared third-party import appears.

If a third-party package is introduced later, the same change must declare it, add a
deterministic lock/constraints artifact, document why it is needed, update the guard,
and pass the full V14 regression/preflight suite.

## Deterministic research

Research reports use persisted point-in-time observations. Paired bootstrap helpers use
deterministic seeds derived from the analysis label. A regenerated report from the same
commit, same artifacts and same Python 3.12 runtime must therefore be materially
reproducible.

## Source of truth

Software/model identity comes from `v14/__init__.py` and the champion manifest. Human
documentation must never override those constants.
