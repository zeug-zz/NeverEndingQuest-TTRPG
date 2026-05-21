# Change: LLM Blueprint Enrichment

## Why

Accurate ingest now has safer GUI defaults, explicit entity candidate triage, and a truthful enrichment status contract. The next recovery slice is to replace the placeholder enrichment layer with bounded provider-backed enrichment that improves source-blueprint facts before the existing ModuleBuilder orchestration receives them.

The deterministic source pipeline can preserve names, source refs, IDs, topology, and schema constraints. It cannot reliably infer NPC motives, location atmosphere, clue placement, puzzle intent, or encounter purpose from human-authored adventures. Those interpretation and prose fields are the right role for an LLM, but only if Python keeps structural authority.

## What Changes

- Add a real bounded enrichment pipeline in `utils/toolkit_blueprint_enrichment.py`, starting with an NPC pass.
- Use small source excerpts and source refs rather than monolithic full-source prompts.
- Require JSON-only provider output that is parsed and validated before any patch is applied.
- Reuse the existing patch validator so enrichment may only update approved prose/source-context fields.
- Require applied patches to carry source refs or source-derived justification.
- Degrade safely on provider failures, parse failures, invalid patches, or structural mutation attempts.
- Add fixture tests that run without live provider calls by default.

## Impact

- This change enriches builder-blueprint data before ModuleBuilder handoff; it does not route GUI builds through a different authoring executor.
- Default feature flags remain off unless existing configuration explicitly enables enrichment.
- Provider-backed smoke tests are optional and must be explicitly enabled.
- Numillian fixtures become the primary regression target for false-positive rejection and underbound NPC enrichment.

## Out Of Scope

- Changing the default accurate-ingest authoring path away from the existing ModuleBuilder orchestration.
- Rebuilding production Numillian artifacts.
- Modifying publication gate composition or source-fidelity scoring.
- Making seed writer the primary authoring path.
