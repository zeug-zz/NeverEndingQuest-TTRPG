## Why

The current accurate-ingest pipeline treats literal source fidelity as the publication objective and repeatedly fails on editorial extraction mismatches, especially for non-room sources such as item catalogues. The system needs an LLM-led adaptation lane that creates a coherent NEQ-TTRPG module while leaving Python responsible for validation, artifact safety, Markdown output, and world registration.

## What Changes

- Make LLM adaptation the default workflow for readable Homebrew uploads that do not require literal structural import.
- Add a versioned adaptation dossier contract for the LLM-to-ModuleBuilder handoff.
- Add source profiles for adventures, catalogues, locations, lore, encounters, and sandboxes.
- Feed the adaptation dossier into ModuleBuilder without requiring every extracted source atom to appear in the final module.
- Add a bounded final LLM semantic adaptation audit after content or semantic build failure.
- Rebuild from a revised dossier in a fresh staging target instead of allowing arbitrary LLM patches to live files.
- Separate adaptation status and provenance from legacy source-fidelity status.
- Add optional bounded world-narrative seed context and persist proposed hooks without allowing direct canon mutation.
- Make Markdown quality and registry verification required before a build can report completion.
- Add adaptation provenance and the `Adapted for NEQ-TTRPG` notice to generated module metadata and Markdown credits.
- Preserve accurate-ingest as an explicit legacy and diagnostic mode.

## Non-Goals

- No claim of perfect textual or atom-level source reproduction.
- No new deterministic source-atom triage layer as the primary authoring mechanism.
- No direct LLM writes to arbitrary module files, `world_registry.json`, `campaign.json`, or mechanical runtime state.
- No unbounded provider retry or regeneration loop.
- No weakening of schema, readiness, semantic, report-agreement, or registry verification gates.
- No automatic legal determination of source ownership or adaptation rights.

## Capabilities

### New Capabilities

- `toolkit-llm-adaptation-authoring`: Defines source interpretation, adaptation dossiers, source profiles, and the ModuleBuilder handoff.
- `toolkit-adaptation-final-revision`: Defines the bounded LLM semantic audit and fresh rebuild behavior after a failed adaptation build.
- `toolkit-adaptation-publication-transaction`: Defines staging, gate ordering, registry-last publication, rollback, and campaign visibility verification.
- `toolkit-adaptation-markdown-download`: Defines the required readable `MODULE_SUMMARY.md` artifact and download contract.
- `toolkit-adaptation-provenance`: Defines source rights metadata, adaptation status, model provenance, and the `Adapted for NEQ-TTRPG` notice.
- `toolkit-adaptation-world-narrative-seed`: Defines bounded read-only world-narrative context and proposed module hooks.

### Modified Capabilities

- None. The adaptation lane is an additive publication mode; legacy accurate-ingest requirements remain available behind explicit routing.

## Impact

- `web/routes/toolkit_homebrew_routes.py` for adaptation-mode routing and terminal states.
- `utils/toolkit_homebrew_normalizer.py` or a new adaptation authoring helper for source context and dossier persistence.
- `web/extensions/toolkit_homebrew_packet_builder.py` for dossier handoff and fresh rebuilds.
- `core/generators/module_builder.py` and related generators for adaptation-mode prompts and context.
- `web/extensions/toolkit_homebrew_readiness_gate.py` for failure classification and repair boundaries.
- `web/extensions/toolkit_module_finisher.py` for adaptation-aware report handling and publication ordering.
- `utils/toolkit_llm_final_reconciliation.py` safety primitives, with a separate adaptation response contract.
- `utils/homebrewery_adventure_writer.py` and the toolkit adventure download route.
- World narrative retrieval and provenance surfaces.
- New provider-free prompts, reports, fixtures, and regression suites.
- No direct changes to campaign mechanical truth.

## Rollout And Fallback

- Keep adaptation behind an explicit feature flag during the first rollout.
- Land GPT-5 build-path compatibility before enabling adaptation by default.
- Use one final semantic revision by default, with a hard maximum of two if configured.
- Treat provider, quota, timeout, dependency, and file failures as infrastructure failures rather than semantic failures.
- Do not register a module until all validation, Markdown, report, and registry checks pass.
- If adaptation fails, preserve source and workspace diagnostics and leave no completed registry entry.
- Roll back by disabling adaptation routing and returning to the legacy accurate-ingest path without deleting generated diagnostic artifacts.

## Merge Safety And Compatibility

- Prefer an extension runner and thin route hooks over broad host-file rewrites.
- Mark required host changes with `# TABLETOP MODE:`.
- Preserve existing single-player behavior and existing published modules.
- Keep `world_registry.json` and `campaign.json` runtime-only.
- Use atomic writes for all persisted reports and module state.
- Keep all user-facing Python output ASCII-only.
