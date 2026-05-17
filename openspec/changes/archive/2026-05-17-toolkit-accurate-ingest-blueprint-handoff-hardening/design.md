## Context

The Phase 4 blueprint implementation introduces the right artifacts, but the final write path and handoff classification need tightening. The important invariant is simple: if the pipeline says the source-blueprint handoff is ready, the builder must actually consume the source-blueprint narrative, not a later legacy narrative overwrite.

## Contract Layer (MUST)

- Normalizer persistence MUST write final `builder_narrative.md` exactly once per successful result path, after deciding whether the source is `source_blueprint` or `legacy`.
- When blueprint status is `ready`, final persisted `builder_narrative.md` MUST contain the serialized blueprint narrative and `SOURCE-FAITHFUL BUILD LOCK`.
- When blueprint status is `ready`, the normalizer return payload MUST expose the same blueprint-derived builder narrative that is persisted.
- Legacy narrative generation MUST NOT run after blueprint narrative selection in a way that can overwrite the final artifact.
- Packet builder MUST classify a workspace as blueprint-required when blueprint handoff is enabled and accurate-ingest source/fidelity artifacts are present.
- Packet builder MUST fail closed before executor invocation when a blueprint-required workspace lacks ready blueprint artifacts.
- Packet builder MUST preserve legacy behavior when blueprint handoff is disabled or the workspace lacks accurate-ingest source/fidelity artifacts.
- Packet-builder tests MUST NOT invoke real `ModuleBuilder.build_module(...)` or provider-backed generation.
- User-facing Python log/console text introduced by implementation MUST be ASCII-only.

## Guidance Layer (SHOULD)

- Prefer a small helper in `web/extensions/toolkit_homebrew_packet_builder.py` for blueprint requirement classification rather than scattering conditional checks.
- Prefer a single local variable such as `selected_builder_narrative` in `utils/toolkit_homebrew_normalizer.py` to make overwrite ordering obvious.
- Tests should use injected mock executors for success paths and raising/no-call executors for fail-closed paths.
- Regression tests should assert narrative content, narrative source metadata, and no executor invocation for blocked handoff.

## Required Blueprint Classification

Recommended classification logic:

1. If `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF` is false, blueprint is not required.
2. If ready `builder_blueprint.json` and ready `builder_blueprint_report.json` exist, handoff mode is `source_blueprint`.
3. If `builder_blueprint_report.json` exists and status is not `ready`, blueprint is required and build fails closed.
4. If accurate-ingest evidence exists, such as `source_graph.json`, `normalization_fidelity_report.json`, `identity_resolution_report.json`, or `plot_topology_report.json`, blueprint is required and missing blueprint artifacts fail closed.
5. If no accurate-ingest evidence exists, treat as legacy workspace and preserve existing behavior.

This distinguishes old packet-builder workspaces from new accurate-ingest workspaces where a missing blueprint indicates a broken Phase 4 pipeline.

## Normalizer Narrative Selection

The normalizer should compute one final narrative value:

```python
selected_builder_narrative = legacy_builder_narrative
selected_builder_narrative_source = "legacy"
if blueprint_ready:
    selected_builder_narrative = blueprint_narrative
    selected_builder_narrative_source = "source_blueprint"
```

Only `selected_builder_narrative` should be passed to `persist_builder_narrative_artifact(...)` and returned in the result payload.

## Test Isolation

Packet builder tests should never rely on default executor behavior. Success tests pass `builder_executor=mock_executor`. Fail-closed tests pass a raising executor or assert a sentinel was not called. This prevents accidental real `ModuleBuilder` execution and avoids OpenAI/OpenRouter API traffic during unit tests.

## Rollback

Rollback remains disabling `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF`. The code should continue to support old legacy workspaces without source/fidelity artifacts.
