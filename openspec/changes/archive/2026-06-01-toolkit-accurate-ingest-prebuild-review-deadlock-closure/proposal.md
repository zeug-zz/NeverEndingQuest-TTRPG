## Why

Accurate-ingest GUI jobs can deadlock before ModuleBuilder because source-fidelity diagnostics currently promote degraded or misclassified pre-build findings into a mandatory `awaiting_review` state and prevent `builder_blueprint.json` from being generated. This blocks useful module artifacts from being produced, while downstream validation, report agreement, and playable-publication gates already provide the correct fail-closed safety boundary.

## What Changes

- Pre-build source-fidelity diagnostics MUST be nonblocking by default for accurate-ingest builds when source artifacts are readable and a bounded blueprint can be generated.
- Accurate-ingest blueprint generation MUST continue under degraded fidelity diagnostics by emitting source-backed warning/report metadata instead of requiring a human approval step.
- Deterministic source atom classification SHOULD recognize heading-based locations, numbered room headings, appendix/section headings, prose fragments, NPC-like names, and creature/monster-like names so fidelity diagnostics are less noisy.
- GUI status and terminal guidance MUST distinguish rejected/blocked/no-module states from successful build completion and MUST NOT tell the operator to open MMG when no module folder exists.
- Existing final gates MUST remain authoritative: schema validation, source-fidelity benchmark, toolkit build report, publishability, playable-publication, and report-agreement gates are not weakened.
- Strict fidelity review behavior MUST remain intact for jobs that explicitly enter required `awaiting_review` with a current non-approvable review payload.

## Capabilities

### New Capabilities

- `accurate-ingest-blueprint-generation-under-degraded-fidelity`: Covers bounded blueprint/materialization continuation when pre-build fidelity diagnostics are degraded but source artifacts are readable.
- `accurate-ingest-source-atom-classification-coverage`: Covers deterministic source atom extraction/classification coverage for heading locations, room headings, prose fragments, appendices, NPC-like names, and creature/monster-like names.

### Modified Capabilities

- `toolkit-accurate-ingest-diagnostics-nonblocking`: Clarifies that pre-build source-fidelity diagnostics are advisory/nonblocking unless the backend explicitly marks a current required-review state.
- `toolkit-homebrew-review-status-ux`: Clarifies that rejected/blocked/no-module statuses must not be rendered as successful build completion or MMG-ready guidance.

## Impact

- Affected code areas: `web/routes/toolkit_homebrew_routes.py`, `web/templates/module_toolkit.html`, `utils/toolkit_source_manifest.py`, `utils/toolkit_normalization_fidelity.py`, `utils/toolkit_builder_blueprint.py`, `utils/toolkit_homebrew_normalizer.py`, and related accurate-ingest tests.
- Affected systems: Module Toolkit accurate-ingest GUI upload flow, source-fidelity diagnostics, blueprint precheck, build status rendering, and post-build publication/report gates.
- Compatibility: No breaking change to single-player runtime, tabletop runtime, or existing strict review approval endpoints.
- Fallback strategy: If blueprint artifacts cannot be generated from readable source/packet data, the job MUST fail with explicit missing-artifact diagnostics rather than entering a false success state.
- Non-goals: Do not bypass final playable-publication gates; do not weaken source-fidelity benchmarks; do not add broad force approval; do not manually patch report status fields.
