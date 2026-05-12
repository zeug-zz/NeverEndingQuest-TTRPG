## Why

The Homebrewery `MODULE_SUMMARY.md` generator produces a complete adventure document with cover, introduction, plot overview, NPC gallery, monster stat blocks, and credits — but the Locations section renders "Room descriptions not yet authored" for every location. All 12 locations across 4 areas of The Ancients Lab have rich authored data (descriptions, dmInstructions, NPCs, monsters, plot hooks, DC checks, features, traps, doors, loot, cross-area connectivity) nested inside `area.locations[]` arrays that the current flat-field reader does not traverse. A DM receiving this document cannot see how locations connect to the plot, which NPCs and monsters populate each room, or what mechanical hooks exist — making the document incomplete as an adventure module reference.

## What Changes

- **Fix data traversal**: `load_module_data()` and `_build_locations_section()` read the nested `area.locations[]` structure instead of only top-level area fields, extracting 22+ fields per room
- **Deterministic per-location rendering**: Each room renders description, dmInstructions (full), NPCs (with attitudes), monsters, plot hooks, DC checks, features, traps, doors, loot, encounters, connectivity (intra-area + cross-area), danger level, and accessibility
- **LLM area overview prose**: A new `_llm_area_overview()` helper generates 2-3 paragraph DM narrative for each area, connecting rooms to plot points, NPCs, monsters, and cross-area travel paths — mirroring the existing `_llm_intro_narrative()` / `_llm_plot_hook()` pattern with deterministic fallback
- **Cross-area connectivity**: `areaConnectivity`/`areaConnectivityId` fields are parsed into a lookup index and surfaced in both the LLM narrative context and per-location connectivity lines
- **Schema flexibility**: Legacy flat-schema areas (without `locations[]`) fall back to rendering the area itself as a single location
- **Treasure index**: The Treasures appendix aggregates all `area.locations[].lootTable` entries across all locations into a deduplicated quick-reference catalog, replacing the hardcoded "refer to toolkit" stub

## Capabilities

### New Capabilities
- `homebrewery-location-nested-traversal`: Read nested `area.locations[]` arrays in BU area files and flatten into renderable location records with area context
- `homebrewery-location-deterministic-rendering`: Render per-location markdown sections covering all 22+ authored fields (description, dmInstructions, NPCs, monsters, plot hooks, DC checks, features, traps, doors, loot, encounters, connectivity, danger level)
- `homebrewery-location-llm-area-overview`: Generate LLM DM-facing area overview prose connecting locations to plot, NPCs, monsters, and cross-area travel, with deterministic fallback
- `homebrewery-cross-area-connectivity`: Build a cross-area edge index from `areaConnectivity`/`areaConnectivityId` fields and surface connections in both LLM context and deterministic rendering
- `homebrewery-treasure-index-aggregation`: Aggregate all `area.locations[].lootTable` entries across all areas into a deduplicated quick-reference treasure index in the Treasures appendix

### Modified Capabilities
<!-- None — no existing spec-level behavior changes -->

## Impact

- **`utils/homebrewery_adventure_writer.py`** — `load_module_data()` (+30 lines cross-area edge building), rewritten `_build_locations_section()` (+260 lines), new `_llm_area_overview()` (+90 lines), new `_resolve_area_name_to_id()` (+15 lines), new `_append_edge_name()` (+12 lines), new `_build_treasure_index()` (+40 lines), rewritten `_build_items_appendix()` (+20 lines)
- **`scripts/test_homebrewery_adventure_writer.py`** — 1 tightened existing test, 7 new contract tests (+90 lines)
- **`modules/The_Ancients_Lab/MODULE_SUMMARY.md`** — regenerated with rich location content and treasure index
- **`modules/A_Pottsfield_Burial/MODULE_SUMMARY.md`** — regenerated with rich location content and treasure index
- **LLM cost**: 4 summarization-model calls (~5600 tokens total) — negligible
- **No breaking changes**: existing section order, style conventions, and test contracts preserved; `load_module_data()` return shape additive only
- **Merge safety**: all changes in TABLETOP MODE plugin file; no upstream host file modifications
- **SP/MP compatibility**: unaffected — this is an offline build tool, not runtime code
