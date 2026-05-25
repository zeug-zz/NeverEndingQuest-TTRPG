# Design: Accurate-Ingest Generator Source Locks

## Architecture Boundary

The packet builder owns source-contract extraction and builder input persistence. ModuleBuilder and sub-generators own creative generation. This change bridges those layers by making source contracts visible to generator prompts without replacing the generator pipeline.

Hard ownership boundaries:

- `web/extensions/toolkit_homebrew_packet_builder.py` owns `builder_input` enrichment and build-mode metadata.
- `core/generators/module_builder.py` owns orchestration and should pass source context downward only when present.
- `core/generators/module_generator.py`, `area_generator.py`, `location_generator.py`, and `plot_generator.py` own prompt assembly for their generation stages.
- Source-fidelity and build-fidelity scanners remain deterministic validators and SHALL NOT be weakened.

## Key Decisions

### Decision 1: Add Monster/Encounter Fields Before Stat Materialization

Numillian currently has source monster refs in `normalized_packet.json`, but `monsters_seed.json` is empty and no `monsters/*.json` files exist. This change MUST first make those source refs visible in `builder_input` and generator prompt context. Monster stat creation is a later change.

### Decision 2: Source Context Is Optional And Additive

Generator source locks MUST activate only when source-enhanced builder input exists. Legacy concept builds MUST not require source fields and MUST not inherit stale source fields from accurate-ingest workspaces.

### Decision 3: Prompt-Level Locking Comes Before Runtime Rebuild Proof

This change SHOULD add provider-free source-contract tests that assert prompt/context inclusion. It should not depend on live LLM calls or production module rebuilds.

### Decision 4: Minimal Context Format

The first pass SHOULD use a compact source context structure or serialized text block containing:

- required source NPC names
- required source location names
- required puzzle/challenge identifiers
- source monster refs
- source encounter seeds or bounded encounter plan
- tone requirements
- source-lock rules and forbidden invention/replacement guidance

## Migration Sequence

1. Add failing/provider-free tests proving `builder_input` includes monster/encounter fields for a Numillian-like v2 workspace.
2. Add minimal extraction from normalized packet/blueprint artifacts into `builder_input`.
3. Add tests proving ModuleBuilder receives and preserves source context for downstream calls.
4. Add source-lock prompt/context tests for generator classes.
5. Add minimal generator prompt/context injection.

## Rollback Strategy

All changes SHOULD be independently revertible. If prompt injection breaks legacy builds, revert only source-context injection and keep tests documenting the source-enhanced path expectations.

## Observability

Build artifacts SHOULD continue to report `build_mode`, `handoff_mode`, `builder_input_path`, source artifact paths, and source lock fields. Added monster/encounter fields SHOULD be visible in `builder_input.json` and provider-free tests.

## Compatibility

- Non-source concept-builder flows MUST remain functional.
- Explicit seed writer support modes MUST remain available.
- No production module artifacts SHOULD be modified during scaffold or source-contract steps.
