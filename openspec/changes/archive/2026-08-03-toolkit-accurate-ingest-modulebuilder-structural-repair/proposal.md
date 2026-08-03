## Why

Well of Ruin exposed structural accurate-ingest failures before the final editorial boundary: `validation_report.json` reports 86 failed checks, dominated by monster reference integrity, spatial contract failures, and an invalid party calendar month. These are not editorial source-fidelity disagreements, so the LLM Builder final editor must not be asked to repair or accept them.

This change restores deterministic ModuleBuilder structural repair after source-enhanced generation so accurate-ingest modules can reach the final-editor boundary only after full-module structural validation is clean.

## What Changes

Contract Layer (MUST):

- Add an accurate-ingest ModuleBuilder monster-reference closure step that runs after ModuleBuilder output and before final reconciliation routing.
- Add a deterministic spatial repair/relayout step that recomputes valid cardinal adjacency, map coordinates, and spatial contract artifacts after generated locations/connectivity are finalized.
- Add early party calendar normalization so invalid fantasy-calendar months such as `Hammer` are rewritten or rejected before final validation.
- Add structural blocker routing so fatal schema/reference/spatial/party validation failures block final-editor invocation even if an accepted final reconciliation report exists on disk.
- Preserve the existing full-module validation gate and source-fidelity honesty semantics.

Guidance Layer (SHOULD):

- Reuse existing monster closure, spatial normalization, readiness repair, and validator utilities where possible instead of adding new generator-specific rewrites.
- Keep provider-free tests for structural repair helpers and packet-builder routing.
- Prefer post-generation deterministic repair over widening LLM prompts, except for removing known-invalid prompt examples such as `Hammer`.

## Capabilities

### New Capabilities

- `accurate-ingest-modulebuilder-monster-closure`
- `accurate-ingest-modulebuilder-spatial-repair`
- `accurate-ingest-modulebuilder-calendar-normalization`
- `accurate-ingest-structural-blocker-routing`

### Modified Capabilities

- None. This change adds structural repair behavior around the accurate-ingest ModuleBuilder path without changing existing main-spec requirements.

## Impact

Affected code areas:

- `web/extensions/toolkit_homebrew_packet_builder.py` for accurate-ingest build orchestration and fatal routing.
- `core/generators/module_builder.py` for post-generation structural repair insertion points.
- `core/generators/module_generator.py` or a shared utility extracted from it for monster reference closure parity.
- `utils/toolkit_final_blocker_classifier.py` and `utils/toolkit_llm_final_reconciliation.py` for structural/fatal blocker protection around final-editor invocation.
- `web/extensions/toolkit_homebrew_readiness_gate.py`, `core/generators/location_generator.py`, and related validation helpers for party calendar normalization.
- `core/validation/validate_module_files.py` validation output consumers.

Rollout risks:

- Monster closure may create invalid or excessive monsters if source classification is weak. Mitigation: reuse existing schema-sufficiency validation and unresolved diagnostics; fail closed on unresolved required monsters.
- Spatial repair may alter creative location ordering. Mitigation: preserve authored/source location names and only recompute coordinates/connectivity/map representation needed for validator contract.
- Calendar normalization may hide upstream prompt defects. Mitigation: also remove the known-invalid prompt example and test the repair path.
- Final-editor routing may become too conservative. Mitigation: only classify schema/reference/spatial/party validation failures as fatal; editorial source-fidelity blockers still follow the existing final reconciliation path.

Fallback strategy:

- If deterministic repair cannot produce a valid module, the build remains blocked with explicit structural diagnostics. The final editor remains unavailable for that module until structural validation passes.

Merge-safety and compatibility:

- Single-player runtime behavior is unaffected; this is toolkit accurate-ingest build-time behavior.
- Host-file edits should remain small and marked with `# TABLETOP MODE:` when touching upstream-style core files.
