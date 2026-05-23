# Change: Numillian Source-Fidelity Fix

## Why

The production accurate-ingest Numillian module is currently held with `source_fidelity_status: blocked`. The remaining 16+ dirty files cannot be committed while three blocker classes remain:

1. **Punctuation mismatch in build-fidelity atom matching.** Required NPC at `Red Skull:`, `Blue Skull:`, and `Yellow Skull:` (from markdown source table punctuation) are compared against module entries `Red Skull`, `Blue Skull`, `Yellow Skull` without trailing colons. The `_normalize_name` helper in `utils/toolkit_build_fidelity.py` strips spaces and replaces hyphens with underscores but does not strip trailing markdown/table punctuation such as `:`. This produces false `Required npc 'Red Skull:' not found in module` blockers.

2. **Entity pollution from prose emphasis phrases.** The narrative assertion `but this is not true` is emitted as an NPC entry in `module_context.json`, `npcs_seed.json`, and seed data. The previous enrichment change (`toolkit-accurate-ingest-llm-blueprint-enrichment`) added fixture regressions preventing this, but the production rebuild produced those artifacts before enrichment was active. The source graph or seed writer must not classify emphasized prose clauses as NPC actors.

3. **Missing puzzle preservation in benchmark output.** The Numillian benchmark fixture requires three puzzles (`skull_riddle`, `flooding_room`, `kill_the_dog_mindscape`) to be preserved in module artifacts. Current benchmark reports only `flooding_room` as found. The synthetic blueprint fallback in `scripts/rebuild_numillian_accurate_ingest.py` sets `puzzle_graph=[]`, which causes the seed writer to emit zero puzzle artifact that the benchmark can detect.

## What Changes

- Add trailing-markdown-punctuation stripping to `_normalize_name()` in `utils/toolkit_build_fidelity.py` so colon-bearing source atom labels match canonical generated names.
- Fix the Numillian synthetic blueprint fallback to carry puzzle/trial/clue graph data forward from `plot_topology_report.json` and any normalized packet puzzle fields instead of setting `puzzle_graph=[]`.
- Ensure the fidelity-blocked synthetic fallback path respects existing entity-candidate triage semantics so `but this is not true` cannot become an NPC/actor, while legitimate Numillian NPCs remain preserved.
- Rebuild Numillian production artifacts from the fixed pipeline.
- Reassess publication readiness.

## Impact

- This change is narrow and targeted. It does not alter the broader accurate-ingest architecture, publication gate composition, fidelity scoring, or ModuleBuilder direction.
- All planning in `plans/accurate-ingest-fix.md` about the ModuleBuilder recovery path remains unaffected.
- The archived `toolkit-accurate-ingest-llm-blueprint-enrichment` change already has `but this is not true` fixture regressions; those should now be enforceable at the source graph/blueprint level, not only at enrichment time.

## Out Of Scope

- Changing default accurate-ingest authoring path away from existing ModuleBuilder orchestration.
- Modifying publication gate composition or source-fidelity scoring thresholds.
- Changing the Numillian benchmark fixture expectations.
- Making structural changes to the accurate-ingest rebuild pipeline beyond the three narrow fixes above.
- Replacing the existing triage system with a broad new heuristic.
- The broader `toolkit-accurate-ingest-numillian-release-proof` change is deferred until this bridge fix passes.

## Important Existing Context

This change is a bridge fix for the currently held Numillian production artifacts. It does not replace the broader recovery plan in `plans/accurate-ingest-fix.md`.

Existing triage support already lives in `utils/toolkit_entity_candidate_triage.py`, `utils/toolkit_homebrew_normalizer.py`, and `utils/toolkit_builder_blueprint.py`. The defect to fix is that the fidelity-blocked synthetic rebuild path in `scripts/rebuild_numillian_accurate_ingest.py` currently rebuilds a minimal blueprint directly from the normalized packet and can bypass richer topology/triage artifacts. The fix should reuse those artifacts where possible rather than inventing a second classification model.
