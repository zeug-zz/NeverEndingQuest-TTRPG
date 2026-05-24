# Change: Numillian NPC and Location Preservation

## Why

The archived `toolkit-accurate-ingest-numillian-source-fidelity-fix` bridge change removed the immediate punctuation, puzzle, and prose-phrase blockers, but the production Numillian benchmark remains blocked on the two structural preservation categories:

- `npc_preservation`: blocked, `1/23` source NPCs found.
- `location_preservation`: blocked, `0/13` source locations found.

Puzzle preservation is now passing at `3/3` and MUST remain passing. The next step is not the final Numillian release proof. The next step is a focused source-preservation change that ensures required source NPCs and keyed source locations survive the accurate-ingest path as source-bound module content or explicit unresolved blockers.

## What Changes

- Add deterministic regression locks for the current Numillian NPC and location preservation blockers.
- Ensure source NPC candidates from the benchmark fixture and source graph can be propagated into blueprint/module artifacts with source refs and bindings.
- Ensure source keyed locations can be propagated into blueprint/module artifacts with stable source names, aliases, area grouping, and benchmark-visible final artifacts.
- Require location/NPC bindings so real minor NPCs are not merely preserved as names with empty `appears_in` metadata.
- Preserve the previous bridge-fix outcomes: puzzle preservation remains passing, and prose phrases such as `but this is not true` remain rejected as actors.

## Impact

- Accurate-ingest source fidelity becomes stricter for source-backed NPC and location omissions.
- Numillian remains held until benchmark status improves from blocked or blockers become explicit and reviewable.
- Existing ModuleBuilder orchestration remains the creative build path. This change does not replace ModuleBuilder with the deterministic seed writer.

## Non-Goals

- Do not change the Numillian benchmark thresholds to make current output pass.
- Do not weaken build-fidelity, benchmark, readiness, or publishability gates.
- Do not hand-edit production Numillian module artifacts as a substitute for source-preservation pipeline fixes.
- Do not implement final release proof or publication commit/push behavior.
- Do not make `MODULE_SUMMARY.md` a source-fidelity repair input.

## MUST Constraints

- The source NPC preservation path SHALL preserve benchmark-required NPC names or produce explicit unresolved-source blockers.
- The source location preservation path SHALL preserve benchmark-required source location names or approved aliases in benchmark-visible artifacts.
- Kept source NPCs SHALL carry at least one source role, location binding, plot binding, faction binding, or explicit source ref.
- Source keyed locations SHALL carry source refs and enough identity metadata to survive final build-fidelity and benchmark checks.
- Puzzle preservation SHALL remain passing for `skull_riddle`, `flooding_room`, and `kill_the_dog_mindscape`.
- `but this is not true` SHALL remain rejected as NPC, monster, scene actor, semantic NPC authority entry, or seed actor.
- The deterministic seed writer SHALL NOT become the default accurate-ingest GUI authoring path.

## SHOULD Guidance

- Prefer source graph, normalized packet, entity triage, and builder blueprint fixes over production artifact hand edits.
- Prefer small pipeline seams with deterministic tests before any production rebuild.
- Treat Dog-Growl, Book-shut, and Deflation as a key underbound-entity regression: valid minor NPCs must be preserved and bound to `The Rookery`.
- Treat the 13 benchmark source locations as stable source names unless an explicit alias map is approved and tested.

## Rollback

Each preservation change SHOULD be independently revertible. If a fix causes broad module-builder regressions, revert the specific propagation or matching change while keeping deterministic regression tests that describe the blocker.

## Dependencies

- `toolkit-accurate-ingest-numillian-source-fidelity-fix` is archived and completed background work.
- `toolkit-accurate-ingest-llm-blueprint-enrichment` is archived background work.
- `plans/accurate-ingest-fix.md` remains the broader recovery plan.
