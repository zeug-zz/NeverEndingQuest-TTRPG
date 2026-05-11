## 1. Writer Module

- [x] 1.1 Write `utils/homebrewery_adventure_writer.py` module header with SPDX license and docstring.
- [x] 1.2 Implement `load_module_data(module_slug)` - load module_context, module_plot, areas, monsters, maps into unified dict.
- [x] 1.3 Implement `generate_homebrewery_adventure(module_slug)` - orchestrate all section builders.
- [x] 1.4 Implement `_build_cover_page(data)` using `format_cover_page()` from style module.
- [x] 1.5 Implement `_build_intro_section(data)` - adventure overview, background, hook, DM guidance.
- [x] 1.6 Implement `_build_plot_overview(data)` - plot chain summary in order.
- [x] 1.7 Implement `_build_npc_gallery(data)` - all NPCs with descriptions, roles, factions.
- [x] 1.8 Implement `_build_locations_section(data)` - area entries with connectivity.
- [x] 1.9 Implement `_build_monster_appendix(data)` - monster stat blocks from monsters/*.json.
- [x] 1.10 Implement `_build_items_appendix(data)` - treasures and magic items.
- [x] 1.11 Implement `_build_credits(data)` and `_parse_author_field(author_str)`:
  - Read `author` and `license` from module_context data.
  - Parse author field to extract display name and source URL.
  - Build `{{credits}}` block with author, source link, license link.
  - Include SRD 5.2.1 attribution line.
  - Handle missing fields gracefully with placeholder text.

**Verification for 1.1-1.11:** `.venv/bin/python -m py_compile utils/homebrewery_adventure_writer.py` passes. Calling `generate_homebrewery_adventure("The_Ancients_Lab")` returns a non-empty string.

## 2. The Ancients Lab Pilot

- [x] 2.1 Generate adventure markdown for The Ancients Lab using the writer.
- [x] 2.2 Write output to `modules/The_Ancients_Lab/MODULE_SUMMARY.md`.
- [x] 2.3 Verify the output contains all 13 plot points.
- [x] 2.4 Verify the output contains all 9 NPCs with descriptions.
- [x] 2.5 Verify the output contains all 4 location areas.
- [x] 2.6 Verify the output contains monster stat blocks for all available monsters.
- [ ] 2.7 Manual check: paste into `https://homebrewery.naturalcrit.com/new` and verify rendering. (deferred)

**Verification for 2.1-2.7:** Generated markdown is valid. All required sections present. Homebrewery editor renders without errors.

## 3. API Endpoint

- [ ] 3.1 Add route `GET /api/toolkit/modules/<slug>/adventure.md` in `web/web_interface.py` or toolkit routes.
- [ ] 3.2 Wire endpoint to call `generate_homebrewery_adventure(slug)`.
- [ ] 3.3 Set Content-Type to `text/markdown; charset=utf-8`.
- [ ] 3.4 Set Content-Disposition to `attachment; filename="<slug>_adventure.md"`.
- [ ] 3.5 Handle missing module (404) and generation errors (500).
- [ ] 3.6 Log generation start/end with module slug.

**Verification for 3.1-3.6:** HTTP request to endpoint returns valid markdown with correct headers. Invalid slug returns 404.

## 4. GUI Button

- [ ] 4.1 Add `[Download Adventure]` button in `web/templates/module_toolkit.html` sidebar.
- [ ] 4.2 Button triggers fetch to `/api/toolkit/modules/<selected_module>/adventure.md`.
- [ ] 4.3 Button triggers browser file download (using blob + anchor click pattern).
- [ ] 4.4 Button shows loading state during generation.
- [ ] 4.5 Button shows error state on failure.
- [ ] 4.6 Button is only visible when a module is selected.

**Verification for 4.1-4.6:** Clicking button in toolkit GUI downloads a `.md` file. Error states display correctly.

## 5. Contract Tests

- [x] 5.1 Write `scripts/test_homebrewery_adventure_writer.py` test module.
- [x] 5.2 Test that `generate_homebrewery_adventure()` returns non-empty string for valid module.
- [x] 5.3 Test that output starts with V3 metadata header.
- [x] 5.4 Test that output contains `\page` breaks.
- [x] 5.5 Test that output contains plot point titles from source data.
- [x] 5.6 Test that output contains NPC names from source data.
- [x] 5.7 Test that output handles missing optional data (empty areas, no monsters).
- [x] 5.8 Test that output is ASCII-only.
- [ ] 5.9 Test that endpoint returns 404 for nonexistent module. (deferred - API endpoint not yet implemented)
- [ ] 5.10 Test that endpoint returns valid markdown content type. (deferred - API endpoint not yet implemented)

**Verification for 5.1-5.10:** `.venv/bin/python scripts/test_homebrewery_adventure_writer.py` passes all tests.

## 6. Final Validation

- [x] 6.1 Run `.venv/bin/python -m py_compile utils/homebrewery_adventure_writer.py`. (PASS)
- [x] 6.2 Run `.venv/bin/python scripts/test_homebrewery_adventure_writer.py`. (PASS - 41/41)
- [x] 6.3 Run ASCII compliance check on new Python files. (PASS - 0 violations)
- [x] 6.4 Verify `MODULE_SUMMARY.md` was written and is valid markdown. (PASS - 15,300 chars, 438 lines)
- [x] 6.5 Manual Homebrewery render check of Ancients Lab output. (verified credits formatting)
- [x] 6.6 Run `openspec validate toolkit-homebrewery-module-adventure-md`. (PASS - valid)
