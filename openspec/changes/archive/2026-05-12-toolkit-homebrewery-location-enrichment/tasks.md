## 1. Data Loading — Cross-Area Edges

- [X] 1.1 Add `_resolve_area_name_to_id(areas, name)` helper in `utils/homebrewery_adventure_writer.py` — exact match on `area.areaName`, returns `areaId` or empty string
- [X] 1.2 Build `_cross_area_edges` list in `load_module_data()` after area-loading loop: iterate `area.locations[]`, parse `areaConnectivity` + `areaConnectivityId` pairs, resolve via `_resolve_area_name_to_id`, append `(from_aid, from_lid, to_aid, to_lid)` tuples
- [X] 1.3 Handle edge cases: mismatched array lengths (zip to shorter), unresolvable names (skip with warning), empty arrays (skip)
- [X] 1.4 Verify: `python3 -m py_compile utils/homebrewery_adventure_writer.py` -> PASS

## 2. Location Rendering — Deterministic

- [X] 2.1 Rewrite `_build_locations_section()`: iterate `data["areas"]`, then `area.get("locations", [])` for each area; for each location extract all 22+ fields
- [X] 2.2 Render area-level header: `## AreaName (AreaCode)` + LLM area overview (placeholder, wired in Section 3) + metadata line (`**Area Type:** ... | **Recommended Level:** ...`)
- [X] 2.3 Render per-location block with heading `### LocationId -- LocationName`, then fields in order: description, dangerLevel, accessibility, adventureSummary, features, dcChecks, plotHooks, traps, doors, lootTable, encounters, npcs, monsters, connectivity + cross-area, dmInstructions
- [X] 2.4 Implement flat-schema fallback: if `area.locations` is absent/empty, treat area as single location using `areaName`, `area.description`, `area.dmInstructions`, etc.
- [X] 2.5 Guard empty field categories: skip rendering section header and bullets when field list is empty
- [X] 2.6 Verify: `python3 -m py_compile utils/homebrewery_adventure_writer.py` -> PASS
- [X] 2.7 Verify: `python3 scripts/test_homebrewery_adventure_writer.py` -> existing tests still PASS

## 3. LLM Area Overview

- [X] 3.1 Add `_llm_area_overview(area, data)` function: build prompt with area name, type, truncated areaDescription, per-location names + truncated descriptions + NPC/monster names, relevant plot points (matched by area ID in descriptions), incoming/outgoing cross-area edges
- [X] 3.2 Prompt content contract: instruct model to write 2-3 paragraphs in third-person present tense covering atmosphere, plot connections, key NPCs/monsters, cross-area travel paths; explicitly instruct "Do NOT list individual room names"
- [X] 3.3 Use `DM_SUMMARIZATION_MODEL` via `create_chat_client()`, temperature 0.6, max_completion_tokens 500
- [X] 3.4 On exception: catch all, return None (fail-open per existing LLM helper pattern)
- [X] 3.5 On empty location text: return None without LLM call (early return)
- [X] 3.6 Return value: plain paragraph text wrapped in `sanitize_markdown_text()` (NOT blockquoted)
- [X] 3.7 Wire into `_build_locations_section()`: call `_llm_area_overview()` for each area; on `None`, fall back to `area.areaDescription`; if both absent, skip overview
- [X] 3.8 Verify: `python3 -m py_compile utils/homebrewery_adventure_writer.py` -> PASS
- [X] 3.9 Verify: existing tests still PASS

## 4. Cross-Area Connectivity in Rendering

- [X] 4.1 Compose per-location connectivity line from intra-area `connectivity` and cross-area `areaConnectivity`/`areaConnectivityId` pairs
- [X] 4.2 Format: `*Connected to: Within area: I02, I03; The Blackcrag Marches / I01*`
- [X] 4.3 Omit connectivity line entirely when both `connectivity` and `areaConnectivity` are empty
- [X] 4.4 Verify: `python3 -m py_compile utils/homebrewery_adventure_writer.py` -> PASS
  *(Completed during Phase 2 — connectivity data was available and deterministic)*

## 5. Regeneration & Smoke

- [X] 5.1 Regenerate `modules/The_Ancients_Lab/MODULE_SUMMARY.md` via `.venv/bin/python -c "from utils.homebrewery_adventure_writer import generate_homebrewery_adventure; ..."`
- [X] 5.2 Smoke check: verify output contains area names ("The Aberrant Wastes", "The Blackcrag Marches", "The Abandoned Vaultways", "The Shuddering Wilds")
- [X] 5.3 Smoke check: verify output contains location names ("Warped Sentinel Vestibule", "Fleshforged Observation Nook", etc.)
- [X] 5.4 Smoke check: verify output contains `**DM Guidance:**` headers (12 of 12)
- [X] 5.5 Smoke check: verify output no longer contains "Room descriptions not yet authored"
- [X] 5.6 ASCII compliance: output passes `.encode("ascii")`

## 6. Test Updates

- [X] 6.1 Tighten `test_location_section_exists`: assert location section contains actual room name (e.g. "Warped Sentinel Vestibule"), not just "Room descriptions not yet authored"
- [X] 6.2 Add `test_locations_contain_room_names`: assert all 4 area names + 12 room names present in output
- [X] 6.3 Add `test_locations_contain_dm_guidance`: assert "DM Guidance" appears at least 12 times (once per room)
- [X] 6.4 Add `test_locations_contain_npcs`: assert "Rambling Dwarven Survivor", "Damaged Security Overseer", "Archivist Automaton" appear
- [X] 6.5 Add `test_locations_contain_monsters`: assert monster names appear (e.g. "Aberrant Creeper", "Fleshforged Aberrant")
- [X] 6.6 Add `test_locations_contain_plot_hooks`: assert "**Plot Hooks:**" headers appear
- [X] 6.7 Add `test_locations_have_area_overview`: assert area-level prose exists between area heading and first location heading (either LLM or fallback)
- [X] 6.8 Verify full test suite: `.venv/bin/python -m unittest scripts.test_homebrewery_adventure_writer -v` -> all 47 tests PASS
- [X] 6.9 Verify ASCII compliance test passes: `test_output_is_ascii`

## 7. Validate & Close

- [ ] 7.1 Run `openspec validate toolkit-homebrewery-location-enrichment` -> VALID
- [ ] 7.2 Run `.venv/bin/python scripts/test_homebrewery_adventure_writer.py` -> PASS
- [X] 7.3 Verify `modules/The_Ancients_Lab/MODULE_SUMMARY.md` renders correctly in Homebrewery (paste check)

## 8. Treasure Index Aggregation

- [X] 8.1 Add `_build_treasure_index(data)` helper: iterate all `area.locations[]`, collect `lootTable` entries, deduplicate by normalized name (case-insensitive, whitespace-collapsed), format as `- **Item Name** -- description, value (AreaCode/LocationId)`
- [X] 8.2 Pass all rendered text through `sanitize_markdown_text()` for ASCII compliance
- [X] 8.3 Rewrite `_build_items_appendix()`: call `_build_treasure_index()`; on empty result, render fallback "No curated treasure data available for this module."; on non-empty, render header + bullet list
- [X] 8.4 Add `test_treasure_index_present` to `TestGeneratedSections`: assert `# Appendix A: Treasures` section contains at least 10 bullet items (both modules have 35+ loot entries)
- [X] 8.5 Regenerate `modules/The_Ancients_Lab/MODULE_SUMMARY.md` and `modules/A_Pottsfield_Burial/MODULE_SUMMARY.md`
- [X] 8.6 Verify: `python3 -m py_compile utils/homebrewery_adventure_writer.py` -> PASS
- [X] 8.7 Verify: `.venv/bin/python -m unittest scripts.test_homebrewery_adventure_writer -v` -> all 48 tests PASS
- [X] 8.8 Verify ASCII compliance: `test_output_is_ascii` PASS
