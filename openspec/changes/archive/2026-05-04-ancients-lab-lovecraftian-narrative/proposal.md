# Proposal: Ancients Lab Lovecraftian Narrative Enhancement

## Problem

`modules/The_Ancients_Lab` is mechanically complete (4 areas, 12 locations, 13 plot points, 24 side quests, 6 decision points) but narratively flat. The central entity "The Thing" has no JSON description (0 chars). Six of nine NPCs have empty descriptions. The plot provides binary choices (help/harm) without cosmic or philosophical depth. The module reads as a standard fantasy dungeon-crawl with body-horror motifs rather than a Lovecraftian descent into forbidden knowledge and cosmic horror.

## Objective

Transform `The_Ancients_Lab` into a layered Lovecraftian experience where five competing truths about the central entity coexist, the Narrator weaves them dynamically based on player behavior, and the module supports 15 distinct endings (3 per playline). All content MUST flow through existing JSON text fields -- NO new fields, NO schema changes, NO location/connectivity/stat modifications.

## Five Playlines

1. **The Dreamer Beneath** -- The Thing is a sleeping god; mutations are dream-ripples
2. **The Containment** -- The Thing is a warden holding back something older
3. **The Communion** -- The Thing is a precursor inviting symbiotic evolution
4. **The Inheritance** -- The Thing is the dwarves' ancestor; corruption is reversion
5. **The Mirror** -- The Thing has no fixed nature; it reflects the party's fears

## Non-Goals

- Do NOT add new JSON fields or change the module schema
- Do NOT modify location connectivity, room structure, or area layout
- Do NOT change monster stats, loot tables, or mechanical difficulty
- Do NOT add code paths to the stitcher or narrator loader
- Do NOT alter the existing linear plot point sequence (PP001-PP013)
- Do NOT remove or restructure existing content

## Risk Analysis

| Risk | Severity | Mitigation |
|------|----------|------------|
| Token bloat from expanded descriptions | Low | dmInstructions is per-location (1 at a time); other expansions are bounded |
| Narrator confusion from multiple playlines | Low | Emergence cues are behavior-based; the Narrator emphasizes one thread at a time |
| JSON syntax errors from long string edits | Medium | Validate after each phase; use python3 JSON parse check |
| Cross-playline inconsistency | Medium | Standardize emergence cue format across all dmInstructions |
| PP013 description too large for JSON | Low | Keep it as framework; full ending drafts in standalone guide |

## Rollout

Single-phase enrichment: modify 6 JSON files (module_context.json, module_plot_BU.json, 4 area BU files) and create 1 reference guide. No code changes required. All validation passes through existing tooling (`python3 -m py_compile` JSON parse check, `.venv/bin/python core/validation/validate_module_files.py`).

## Merge Safety

No code files modified. Module-published JSON files updated (BU files are canonical, runtime mirrors will regenerate). All changes are additive text enrichment within existing fields. Zero impact on upstream behavior, SP/MP compatibility, or other modules.
