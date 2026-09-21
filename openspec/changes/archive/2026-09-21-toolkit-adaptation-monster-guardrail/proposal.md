## Why

The LLM adaptation lane currently treats every value in `location.monsters[]` as a monster identity. Narrative encounter phrases, NPCs, allies, quantities, and scene descriptions are therefore converted into artificial monster references. The subsequent closure step also writes generated files to `modules/<slug>/` while validating a temporary staging directory, causing otherwise complete staged modules to be blocked and leaving orphaned live artifacts.

This change restores the accurate-ingest source-aware monster contract for adaptation builds and makes monster materialization staging-safe before another adaptation module is attempted. It also lets the existing Module Builder LLM complete mechanics for explicitly approved canonical identities, using bounded source context and 5e SRD exemplars, without allowing the provider to invent identities from prose.

## What Changes

- Add a provider-free adaptation monster guardrail that derives bounded monster vocabulary from the adaptation dossier and canonical monster sources.
- Normalize generated area monster entries into semantic monster IDs before reference closure; classify NPCs, allies, and prose-only encounter descriptions as non-monster content.
- Reuse schema-sufficient module, shared, or bestiary monster artifacts before any generation attempt.
- Search supplied reusable roots comprehensively so exact or payload-named artifacts are not skipped by a small candidate cap.
- Allow bounded LLM stat generation for explicitly approved canonical identities when the existing adaptation generation policy permits it.
- Provide bounded source/encounter context and 5e SRD exemplar guidance to canonical stat generation without permitting identity substitution or arbitrary file edits.
- Make generated monster materialization accept an explicit output directory and write only inside the active adaptation staging target.
- Prevent adaptation builds from invoking the legacy blind prose-to-monster generation path.
- Preserve the existing legacy ModuleBuilder closure behavior for non-adaptation builds.
- Persist concrete adaptation blocker classifications and current build results on early closure failures.
- Add provider-free and provider-seam regression tests for semantic normalization, comprehensive reuse, bounded generation, staging isolation, legacy compatibility, and truthful reporting.

## Capabilities

### New Capabilities

- `adaptation-monster-semantic-guardrail`: Keeps adaptation monster references semantic, canonical, bounded, and connected to encounter seeds.
- `adaptation-staging-safe-monster-materialization`: Resolves or generates monster artifacts inside the adaptation staging tree without live-module side effects.
- `adaptation-blocker-reporting`: Reports concrete monster guardrail, reuse, generation, and closure failures through the adaptation job contract.

### Modified Capabilities

- None. Existing accurate-ingest and legacy module-builder requirements remain unchanged; this slice adds adaptation-specific behavior and compatibility boundaries.

## Impact

- Affected implementation areas: `utils/accurate_ingest_monster_materialization.py`, a new adaptation guardrail utility, `utils/monster_reference_closure.py`, `core/generators/monster_builder.py`, the monster-generation prompt seam, `web/extensions/toolkit_homebrew_packet_builder.py`, adaptation reporting, and related tests.
- Adaptation staging output becomes the sole write target until publication promotion succeeds.
- Legacy single-player and non-adaptation ModuleBuilder flows retain their current closure path.
- Python decides which identities are allowed to become combatants. The LLM may generate mechanics only for those approved identities and its output is schema-verified before closure.
- The existing provider factory and bounded monster-builder subprocess are reused; no new external dependency or provider architecture is introduced.
- Runtime module publication remains registry-last and is not considered complete until the promoted module artifacts and registry entries verify successfully.
