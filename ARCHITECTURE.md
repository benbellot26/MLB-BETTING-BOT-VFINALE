# V14 architecture and change boundaries

Pulsar is intentionally split into three logical zones even though historical code
remains in the same repository for rollback/reference reproducibility.

## 1. Production champion

The production champion is the frozen V14 probability/decision path. Predictive files
covered by the champion manifest must not be changed under the current generation merely
to make a backtest look better.

**Rule:** a predictive change requires an explicit new generation/policy decision and
prospective validation.

## 2. Research / shadow

Challengers, ablations, sensitivity analysis, baselines and regime diagnostics live
outside the betting authorization path.

New governance additions:

- `v14/structural_sensitivity.py` — coefficient perturbation shadow with default parity.
- `v14/ablation_shadow.py` — no-X probability counterfactuals from persisted PIT inputs.
- `v14/ablation_report.py` — preregistered post-registration ablation scoring.
- `v14/research_diagnostics.py` — simple baselines, paired sharp comparison and regime slices.
- `v14/research_registry.py` — append-only registration; strict new experiments can seal
  minimum sample, analysis plan, stopping rule and promotion scope.

Research output can nominate a change. It cannot authorize a bet or silently modify the
champion.

## 3. Historical / archive compatibility

`v11/` and older artifacts remain for frozen reference construction, parity and rollback
reproducibility. They are not a license for production V14 to import arbitrary legacy
prediction logic. Existing import-boundary and generation-identity tests remain the
enforcement layer.

Moving historical modules solely for cosmetic directory cleanliness would create more
risk than value. The separation is therefore **contractual and tested**, not a destructive
file move.

## Data ownership

Mutable operational/performance evidence is hydrated/persisted through the dedicated
runtime-data state branch. Main contains code, reference fixtures and manifests; it must
not become an accidental mutable ledger.

## Read-only reporting

`v14/champion_dashboard.py` aggregates authoritative artifacts and keeps a daily history.
It is explicitly non-authoritative for betting. `data/v14_betting_certification.json`
remains the betting gate.

## Change matrix

| Change | Allowed under current champion? | Evidence needed |
|---|---:|---|
| Documentation / dashboard | Yes | regression tests |
| Runtime-data isolation / provenance | Yes | regression + fail-closed tests |
| Research challenger | Yes, shadow only | preregistration before promotion evidence |
| Ablation / sensitivity diagnostic | Yes, shadow only | post-registration paired evidence for conclusions |
| New production feature/weight/calibrator | No silent change | new generation/policy + OOS/prospective proof |
| Lower betting threshold to create more bets | No | explicit policy review and new certification |
