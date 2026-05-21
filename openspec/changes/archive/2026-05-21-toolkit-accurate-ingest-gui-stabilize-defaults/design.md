# Design: Accurate-Ingest GUI Default Stabilization

## Architecture Boundary

Contract Layer (MUST):

- `ModuleBuilder.build_module(...)` MUST remain the default creative authoring executor for accurate-ingest GUI builds in this change.
- `_execute_seed_writer_build(...)` MUST be treated as an explicit fallback, preview, fixture, or support-artifact path.
- Accurate-ingest status payloads MUST distinguish ModuleBuilder authoring from seed-writer fallback/preview.
- Fidelity review UI MUST remain available for diagnostics, blockers, waivers, and debugging, but clean builds MUST NOT require an approval pause before ModuleBuilder execution.

Guidance Layer (SHOULD):

- Use existing routing functions in `web/extensions/toolkit_homebrew_packet_builder.py` instead of introducing a new build orchestrator.
- Keep the GUI state machine copy explicit: `source_enhanced_modulebuilder` vs `blueprint_seed_fallback`/`blueprint_seed_preview`.
- Prefer source-contract tests that prove the default path cannot reach `_execute_seed_writer_build(...)` without an explicit fallback condition.

## Key Decisions

1. Default accurate-ingest GUI authoring returns to ModuleBuilder.
2. Seed writer remains installed, importable, and testable.
3. New fallback flag defaults to disabled.
4. Diagnostics/review copy is reframed as optional inspection unless the backend marks a state as truly required.
5. Existing readiness, finisher, media, Homebrewery, benchmark, and publishability gates are preserved.

## Routing Model

Default ready accurate-ingest path:

```text
packet workspace -> source artifacts/blueprint -> builder narrative/input -> _execute_module_builder(...) -> readiness/finisher/publishability
```

Explicit seed fallback/preview path:

```text
packet workspace -> source artifacts/blueprint -> explicit fallback/preview flag -> _execute_seed_writer_build(...)
```

## Status Semantics

Contract Layer (MUST):

- Default ModuleBuilder path MUST report a handoff/build mode equivalent to `source_enhanced_modulebuilder` once implemented in routing.
- Seed writer path MUST report a seed-specific mode such as `blueprint_seed_fallback`, `blueprint_seed_preview`, or `blueprint_seed_support`.
- The normal GUI flow MUST NOT report `awaiting_review` merely because optional diagnostics are available.

Guidance Layer (SHOULD):

- Preserve existing fields consumed by polling code (`status`, `stage`, `pipeline_status`, `progress_stage`, `progress_message`).
- Additive metadata is preferred over replacing payload keys.

## Test Strategy

- Source-level tests proving default routing does not invoke `_execute_seed_writer_build(...)`.
- Integration-style mocked packet build test proving default accurate-ingest invokes `_execute_module_builder(...)`.
- GUI copy/source-contract tests proving clean diagnostics are not represented as mandatory approval.
- Existing publication parity tests proving downstream gates still run.

## Rollback

If default ModuleBuilder routing regresses, revert the routing and flag changes from this change. Do not delete seed-writer code during rollback.
