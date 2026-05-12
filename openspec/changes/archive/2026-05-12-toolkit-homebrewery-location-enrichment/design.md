## Context

The Homebrewery adventure writer (`utils/homebrewery_adventure_writer.py`) generates V3 Homebrewery markdown from NEQ module JSON. It already produces cover, introduction (LLM + fallback), plot overview (LLM + fallback), NPC gallery, monster stat blocks, and credits. The locations section is called `_build_locations_section()` and reads from `data["areas"]`.

The Ancients Lab module uses a BU area schema where location data lives in a nested `area.locations[]` array. Each area has 3 locations, each with 22+ fields (description, dmInstructions, NPCs, monsters, plot hooks, DC checks, features, traps, doors, loot, connectivity, areaConnectivity, areaConnectivityId, etc.). The current `_build_locations_section()` only reads top-level area fields (`area.description`, `area.dmInstructions`, `area.npcs`, `area.monsters`) — none of which exist at the area level in this schema — resulting in "Room descriptions not yet authored" for all 12 locations.

### Existing LLM pattern

The writer already has two LLM integration points:
- `_llm_intro_narrative()`: module-level intro prose (3 sections, ~800 tokens output, temperature 0.5)
- `_llm_plot_hook()`: plot overview lead-in paragraph (~250 tokens output, temperature 0.7)

Both use `DM_SUMMARIZATION_MODEL` via `create_chat_client()`, have deterministic fallbacks, and follow the same error handling pattern (try/except returning None).

### Area-Location Schema (The Ancients Lab BU files)

```python
area = {
    "areaId": "AC001",
    "areaName": "The Aberrant Wastes",
    "areaDescription": "...",       # area-level prose
    "areaType": "mixed",
    "dangerLevel": "...",
    "recommendedLevel": "3-5",
    "climate": "...",
    "terrain": "...",
    "locations": [
        {
            "locationId": "I01",
            "name": "Warped Sentinel Vestibule",
            "description": "375 chars narrative prose",
            "dmInstructions": "1756 chars DM guidance",
            "connectivity": ["I02"],
            "areaConnectivity": ["The Blackcrag Marches"],
            "areaConnectivityId": ["I01"],
            "npcs": [{"name": "...", "attitude": "...", "role": "..."}],
            "monsters": [{"name": "...", "description": "..."}],
            "plotHooks": ["...", "..."],
            "features": [{"name": "...", "description": "..."}],
            "dcChecks": ["Investigation DC 14: ..."],
            "traps": [{"detectDC": 16, "disableDC": 18, "damage": "..."}],
            "doors": [{"name": "...", "description": "...", "locked": True, "lockDC": 18}],
            "lootTable": ["Prototype Cure Vial", "..."],
            "encounters": [{"type": "roleplay", "description": "..."}],
            "dangerLevel": "High",
            "accessibility": "...",
            "adventureSummary": "...",
            "aliases": [...],
        },
        # ... 2 more locations
    ]
}
```

## Goals / Non-Goals

**Goals:**
- Render all 12 locations with full authored content across all 4 areas
- Add LLM-generated area-level DM overview prose for each area
- Surface cross-area connectivity in both LLM narratives and deterministic rendering
- Fall back gracefully to deterministic rendering when LLM unavailable
- Support both nested (`locations[]`) and flat (no `locations[]`) area schemas
- Preserve existing section order, style conventions, and test contracts

**Non-Goals:**
- Changing the BU area schema or migrating existing area files
- Adding inline images for room features (out of scope for this change)
- Generating ASCII room maps from `tactical_grid` field
- Supporting modules without BU area files (those already work via flat schema)
- Changing the LLM model selection or provider configuration
- Modifying NPC gallery, monster appendix, or plot overview sections

## Decisions

### D1: Traverse nested `locations[]` directly in render function

**Choice:** Read `area.locations[]` in `_build_locations_section()` rather than pre-flattening in `load_module_data()`.

**Rationale:** `load_module_data()` already stores the full area dict. Flattening would add another large intermediate data structure. Keeping the nested structure lets the render function control iteration granularity. The cross-area edge index is the only new structure needed in `load_module_data()`.

**Alternative considered:** Pre-flatten all locations into `data["locations"]` during load. Rejected because it adds ~12 dict copies and the area-level metadata (areaName, areaType, etc.) would need to be redundantly attached to each location dict.

### D2: LLM area overview as block-level prose, not blockquote

**Choice:** Render LLM area overview as plain markdown paragraphs under the `## AreaName (AreaCode)` heading.

**Rationale:** The area overview is DM-facing narrative text, not a citation or sidebar. Blockquote (`>`) would visually distinguish it but makes it look like a pull-quote rather than body content.

### D3: dmInstructions rendered last, not first

**Choice:** dmInstructions is the last field rendered per location, after description, features, NPCs, monsters, connectivity, etc.

**Rationale:** dmInstructions is the longest field (1500-2650 chars). Rendering it last means the quicker-reference fields (description, NPCs, monsters, plot hooks) appear first in the visual scan order. The DM reads the room description, checks who/what is here, then references the full guidance.

### D4: LLM prompt truncation by character count, not token count

**Choice:** Truncate fields for the LLM prompt context at fixed character lengths (description: 200 chars, areaDescription: 300 chars) rather than computing tokens.

**Rationale:** Simpler, faster, and `DM_SUMMARIZATION_MODEL` context windows are large relative to the data volume. The 4 areas combined produce ~3600 prompt tokens — far below any model limit.

### D5: `_resolve_area_name_to_id()` as simple string match

**Choice:** Match `areaConnectivity` names against `area.get("areaName")` using exact string equality.

**Rationale:** The names are authored canonical values, not user input. Fuzzy matching is unnecessary and could produce false matches. If a name doesn't resolve, the area ID is logged as a warning and the cross-area edge is skipped.

### D6: Single LLM call per area, serial execution

**Choice:** Call `_llm_area_overview()` once per area, sequentially in the section builder.

**Rationale:** 4 serial summarization calls complete in ~5-10 seconds total. Parallel execution would add complexity (ThreadPoolExecutor) without meaningful UX improvement for an offline build tool.

### D7: Cross-area edges built once in `load_module_data()`

**Choice:** Parse `areaConnectivity`/`areaConnectivityId` pairs during data load into `data["_cross_area_edges"]` — a list of `(from_area_id, from_loc_id, to_area_id, to_loc_id)` tuples.

**Rationale:** Building the index once avoids re-parsing the same fields during both LLM prompt construction and deterministic connectivity rendering. The index is small (6 edges across 4 areas).

### D8: Treasure appendix aggregates location lootTable entries

**Choice:** Walk `area.locations[].lootTable` across all areas, deduplicate by normalized name (case-insensitive, whitespace-smashed), and render as a consolidated bullet list under `# Appendix A: Treasures`. Append source location IDs in parentheses.

**Rationale:** The location-level lootTable data (35+ entries in The Ancients Lab, 55+ in A Pottsfield Burial) is already authored in the module JSON but only surfaced per-room in the Locations section. An aggregated index gives the DM a quick-reference treasure catalog without scrolling through 12 room entries. The Locations section retains per-room loot for context; the appendix is a lookup index.

**Alternative considered:** Keep the hardcoded stub text and rely on the Locations section alone. Rejected because it leaves the appendix section as wasted page space when rich treasure data is available.

## Risks / Trade-offs

### Risk: LLM hallucinates location details that contradict authored data

**Mitigation:** The LLM prompt explicitly says "Do NOT list individual room names." The deterministic rendering below the overview section provides the authoritative room-by-room data. Any LLM factual errors are shadowed by the authoritative JSON-derived content.

### Risk: dmInstructions length makes documents very long

**Mitigation:** User explicitly requested full dmInstructions. Homebrewery handles documents of 2000+ lines without issue. The page-break-per-section pattern in the existing generator ensures clean PDF pagination.

### Risk: Cross-area name resolution fails for renamed areas

**Mitigation:** If `_resolve_area_name_to_id()` cannot match a name, the edge is skipped with a warning log. The connectivity line for the affected location omits only the unresolvable cross-area reference. Intra-area connectivity is unaffected.

### Risk: LLM summarization model lacks capacity for area-level narrative

**Mitigation:** The LLM prompt includes only structured data, not full dmInstructions. The prompt is ~900 tokens per area. The fallback (`areaDescription` text) ensures content exists even if LLM fails.

### Trade-off: Serial LLM calls increase generation time

**Trade-off accepted.** 4 serial calls add ~5-10s to an already offline operation. Parallelism would add complexity (thread safety concerns with shared client) for minimal UX gain.

## Open Questions

None. All decisions are resolved above.
