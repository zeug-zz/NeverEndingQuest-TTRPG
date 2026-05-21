# Change: Blueprint Enrichment Real Status

## Why

The accurate-ingest recovery plan keeps the existing ModuleBuilder orchestration as the creative authoring path, but the current blueprint enrichment layer must stop overstating its progress. `utils/toolkit_blueprint_enrichment.py` contains patch-validation scaffolding and placeholder pass orchestration, but the GUI/build pipeline must be able to distinguish these states:

- Enrichment disabled by feature flag.
- Enrichment enabled but provider orchestration not implemented.
- Provider/pass failure or validation errors.
- Real patches applied successfully.
- Structural mutation attempts rejected.

If no-op enrichment reports `complete`, downstream readiness, source-fidelity, and operator diagnostics can treat a thin or skeletal module as if the enrichment layer produced real narrative content. This change makes enrichment status truthful before later changes add real bounded LLM enrichment passes.

## What Changes

- Normalize the enrichment status contract around `skipped`, `not_implemented`, `degraded`, `failed`, and `complete` outcomes.
- Ensure enabled no-op/provider-missing behavior cannot report `complete`.
- Ensure pass exceptions and pass-level errors degrade or fail clearly without corrupting blueprint or module artifacts.
- Preserve and harden patch validation for allowed text/prose fields while rejecting structural mutation attempts.
- Ensure enrichment reports expose status, reason, pass counts, applied/rejected/error/warning counts, and enough diagnostic detail for toolkit surfaces.
- Add regression coverage for disabled, no-provider, provider/pass error, no-op, applied-patch, and structural-rejection states.

## Impact

- No live provider calls are required in this change.
- No ModuleBuilder routing changes are included.
- No default flags are turned on.
- Existing seed-writer support and GUI accurate-ingest behavior remain compatible.
- Later LLM enrichment work can rely on a stable status/report contract.

## Out Of Scope

- Implementing real LLM blueprint enrichment passes.
- Routing accurate-ingest builds through source-enhanced ModuleBuilder handoff.
- Rebuilding Numillian production artifacts.
- Modifying source-fidelity scoring or publishability composition.
