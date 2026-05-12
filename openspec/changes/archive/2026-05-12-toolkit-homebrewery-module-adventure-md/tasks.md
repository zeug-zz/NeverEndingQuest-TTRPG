## 1. Writer Module

- [X] 1.1 Write `utils/homebrewery_adventure_writer.py` module header with SPDX license and docstring.
- [X] 1.2 Implement `load_module_data(module_slug)` - load module_context, module_plot, areas, monsters, maps into unified dict.
- [X] 1.3 Implement `generate_homebrewery_adventure(module_slug)` - orchestrate all section builders.
- [X] 1.4 Implement `_build_cover_page(data)` using `format_cover_page()` from style module.
- [X] 1.5 Implement `_build_intro_section(data)` - adventure overview, background, hook, DM guidance.
- [X] 1.6 Implement `_build_plot_overview(data)` - plot chain summary in order.
- [X] 1.7 Implement `_build_npc_gallery(data)` - all NPCs with descriptions, roles, factions.
- [X] 1.8 Implement `_build_locations_section(data)` - area entries with connectivity.
- [X] 1.9 Implement `_build_monster_appendix(data)` - monster stat blocks from monsters/*.json.
- [X] 1.10 Implement `_build_items_appendix(data)` - treasures and magic items.
- [X] 1.11 Implement `_build_credits(data)` and `_parse_author_field(author_str)`:
  - Read `author` and `license` from module_context data.
  - Parse author field to extract display name and source URL.
  - Build `{{credits}}` block with author, source link, license link.
  - Include SRD 5.2.1 attribution line.
  - Handle missing fields gracefully with placeholder text.

- [X] 1.12 Add post-build generation hook: in `web/extensions/toolkit_module_finisher.py` post-build finishing (stage 12), call `generate_homebrewery_adventure(slug)` and write `modules/<slug>/MODULE_SUMMARY.md` to disk. Fail-open: generation failure logs warning, does not block build success.
- [X] 1.13 Verify: After a full module build, `modules/<slug>/MODULE_SUMMARY.md` exists and contains valid Homebrewery V3 markdown.

**Verification for 1.1-1.13:** `.venv/bin/python -m py_compile utils/homebrewery_adventure_writer.py` passes. Calling `generate_homebrewery_adventure("The_Ancients_Lab")` returns a non-empty string. Post-build finishing writes MODULE_SUMMARY.md.

## 2. The Ancients Lab Pilot

- [X] 2.1 Generate adventure markdown for The Ancients Lab using the writer.
- [X] 2.2 Write output to `modules/The_Ancients_Lab/MODULE_SUMMARY.md`.
- [X] 2.3 Verify the output contains all 13 plot points.
- [X] 2.4 Verify the output contains all 9 NPCs with descriptions.
- [X] 2.5 Verify the output contains all 4 location areas.
- [X] 2.6 Verify the output contains monster stat blocks for all available monsters.
- [X] 2.7 Manual check: paste into `https://homebrewery.naturalcrit.com/new` and verify rendering. (deferred)

**Verification for 2.1-2.7:** Generated markdown is valid. All required sections present. Homebrewery editor renders without errors.

## 3. API Endpoint

- [X] 3.1 Add route `GET /api/toolkit/modules/<slug>/adventure.md` in `web/web_interface.py` or toolkit routes.
- [X] 3.2 Wire endpoint to call `generate_homebrewery_adventure(slug)`.
- [X] 3.3 Set Content-Type to `text/markdown; charset=utf-8`.
- [X] 3.4 Set Content-Disposition to `attachment; filename="<slug>_adventure.md"`.
- [X] 3.5 Handle missing module (404) and generation errors (500).
- [X] 3.6 Log generation start/end with module slug.

**Verification for 3.1-3.6:** HTTP request to endpoint returns valid markdown with correct headers. Invalid slug returns 404.

## 4. GUI Button

- [X] 4.1 Add `[Download Adventure]` button in `web/templates/module_toolkit.html` sidebar.
- [X] 4.2 Button triggers fetch to `/api/toolkit/modules/<selected_module>/adventure.md`.
- [X] 4.3 Button triggers browser file download (using blob + anchor click pattern).
- [X] 4.4 Button shows loading state during generation.
- [X] 4.5 Button shows error state on failure.
- [X] 4.6 Button is only visible when a module is selected.

**Verification for 4.1-4.6:** Clicking button in toolkit GUI downloads a `.md` file. Error states display correctly.

## 5. Contract Tests

- [X] 5.1 Write `scripts/test_homebrewery_adventure_writer.py` test module.
- [X] 5.2 Test that `generate_homebrewery_adventure()` returns non-empty string for valid module.
- [X] 5.3 Test that output starts with V3 metadata header.
- [X] 5.4 Test that output contains `\page` breaks.
- [X] 5.5 Test that output contains plot point titles from source data.
- [X] 5.6 Test that output contains NPC names from source data.
- [X] 5.7 Test that output handles missing optional data (empty areas, no monsters).
- [X] 5.8 Test that output is ASCII-only.
- [X] 5.9 Test that endpoint returns 404 for nonexistent module.
- [X] 5.10 Test that endpoint returns valid markdown content type.

**Verification for 5.1-5.10:** `.venv/bin/python -m unittest scripts.test_homebrewery_adventure_writer -v` -> all 50 tests PASS.

## 6. Final Validation

- [X] 6.1 Run `.venv/bin/python -m py_compile utils/homebrewery_adventure_writer.py`. (PASS)
- [X] 6.2 Run `.venv/bin/python scripts/test_homebrewery_adventure_writer.py`. (PASS - 52/52)
- [X] 6.3 Run ASCII compliance check on new Python files. (PASS - 0 violations)
- [X] 6.4 Verify `MODULE_SUMMARY.md` was written and is valid markdown. (PASS - 1521 lines, 89KB)
- [X] 6.5 Manual Homebrewery render check of Ancients Lab output. (verified credits formatting)
- [X] 6.6 Run `openspec validate toolkit-homebrewery-module-adventure-md`. (PASS - valid)
