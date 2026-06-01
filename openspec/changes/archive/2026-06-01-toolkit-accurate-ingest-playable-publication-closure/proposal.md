## Why

The accurate-ingest pipeline now preserves Numillian source fidelity, but it still does not reliably produce a playable, publishable NEQ-TTRPG module from a 5e adventure narrative/PDF/MD entered through the web GUI Module Builder. This change closes the gap between source-fidelity success and actual gameplay readiness for library staff and patrons.

## What Changes

- Add a fail-closed playable-publication gate for GUI accurate-ingest builds.
- Normalize generated party tracker defaults so emitted modules are schema-valid without manual JSON repair.
- Reconcile generated plot point location references against actual emitted area/location IDs.
- Enforce canonical artifact-set cleanliness for generated modules, including live/BU parity and no stale deleted map/area drift.
- Enforce report agreement across benchmark, source-fidelity, toolkit build, validation, and publishability reports before declaring a module playable.
- Add Numillian as the first end-to-end acceptance target for playable-publication closure.

Non-goals:

- Do not weaken source-fidelity benchmarks, scanners, validation gates, or publishability gates.
- Do not use `MODULE_SUMMARY.md` as source input.
- Do not solve all possible media polish or narrative enrichment issues beyond playability gates.
- Do not manually patch generated module JSON as the success path; fixes must be in pipeline utilities or deterministic post-build repair steps.

## Capabilities

### New Capabilities

- `accurate-ingest-playable-publication-gate`: GUI accurate-ingest builds must fail closed unless the emitted module is playable/publishable by deterministic gates.
- `accurate-ingest-plot-location-id-reconciliation`: Generated plot points must reference actual emitted area/location IDs.
- `accurate-ingest-party-tracker-schema-normalization`: Generated party tracker defaults must satisfy schema requirements.
- `accurate-ingest-canonical-artifact-cleanliness`: Generated module artifact sets must avoid stale/deleted canonical drift and preserve live/BU parity.
- `accurate-ingest-report-agreement-gate`: Benchmark, source-fidelity, toolkit build, validation, and publishability reports must agree before a module is surfaced as playable.

### Modified Capabilities

- `toolkit-build-fidelity-gate`: The gate must compose source fidelity with schema/readiness/publishability for playable output status.
- `toolkit-module-build-reporting`: Reports must distinguish source-fidelity pass from playable/publication pass and provide next-action routing.
- `toolkit-homebrew-review-status-ux`: GUI status must not imply playable completion while validation or publishability blockers remain.

## Impact

- Affected code: accurate-ingest GUI build flow, module finisher/report generation, validation/publishability orchestration, module artifact writer, plot/area ID reconciliation utilities, party tracker defaults.
- Affected artifacts: `module_plot*.json`, `party_tracker_BU.json`, `areas/*_BU.json`, `map_*.json`, source-fidelity/toolkit/validation/publishability reports.
- Compatibility: single-player and tabletop modes must remain compatible; the gate only changes accurate-ingest publication readiness behavior.
- Fallback: if a build cannot pass playable-publication gates, the GUI must surface a deterministic blocker report and keep the module unpublished.
