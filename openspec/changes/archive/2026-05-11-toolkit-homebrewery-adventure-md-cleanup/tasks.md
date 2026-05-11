## 1. Style Module Template Fixes

- [x] 1.1 Update `METADATA_TEMPLATE` in `utils/homebrewery_style.py` from triple-backtick to HTML comment format (`<!--\nmetadata\n...\n-->`).
- [x] 1.2 Update `MONSTER_STATBLOCK_TEMPLATE` in `utils/homebrewery_style.py`:
  - Change `> ## {name}` to `> ### {name}` (H3).
  - Rename `abilities_section` placeholder semantics to hold special abilities (passive traits).
  - Add `actions_section` as separate block containing `> ### Actions` header and attack lines.
- [x] 1.3 Add `_format_action_line(action: dict) -> str` helper that renders structured action data as 5e attack syntax: `***Name.*** *Melee/Ranged Weapon Attack:* +N to hit, reach 5 ft., one target. *Hit:* avg (dice + bonus) damage_type.`
- [x] 1.4 Update `format_monster_statblock()` signature if needed to separate special abilities from actions.

**Verification:** `.venv/bin/python -m py_compile utils/homebrewery_style.py`. Metadata output starts with `<!--`. Stat block output contains `> ###`. (PASS)

## 2. Data Loader Merge

- [x] 2.1 Add `_merge_live_narrative(bu_data: dict, live_data: dict) -> dict` in `utils/homebrewery_adventure_writer.py` that overlays live file narrative fields onto BU-loaded structures:
  - NPCs: description, role, faction (overlay if BU empty or live longer).
  - Plot points: description (overlay if live longer).
  - Author and license (always overlay if live field is non-empty).
- [x] 2.2 Wire merge into `load_module_data()` after both BU and live context files are loaded.
- [x] 2.3 Deduplicate areas by `areaId` in `load_module_data()` after area loading loop.
- [x] 2.4 Read `areaName` as primary display field in `_build_locations_section()`, falling back to `locationName` then `areaId`.

**Verification:** `load_module_data("The_Ancients_Lab")` returns 4 unique areas (not 8), all with `areaName` display names, and all 9 NPCs have descriptions. (PASS)

## 3. Heading Level Corrections

- [x] 3.1 Change `_build_plot_overview()` section header from `## Plot Overview` to `# Plot Overview`.
- [x] 3.2 Change `_build_npc_gallery()` section header from `## NPC Gallery` to `# NPC Gallery`.
- [x] 3.3 Change `_build_locations_section()` section header from `## Locations` to `# Locations`.
- [x] 3.4 Change `_build_monster_appendix()` appendix header from `# Appendix A: Creatures` (already H1, verify).
- [x] 3.5 Change `_build_items_appendix()` appendix header to `# Appendix B: Treasures`.

**Verification:** Generated output contains `# Plot Overview` not `## Plot Overview`. Similarly for NPC Gallery and Locations. (PASS)

## 4. Plot Abstract

- [x] 4.1 Implement `_build_plot_abstract(data: dict) -> str` in `utils/homebrewery_adventure_writer.py`:
  - Build plot text from all plot point titles and descriptions.
  - Attempt LLM summarization via `utils.ai_client_factory.create_chat_client()` using `DM_SUMMARIZATION_MODEL`.
  - Prompt: "Summarize the following adventure plot chain into a 2-3 paragraph narrative abstract suitable for a DM introduction. Focus on the overall arc, key locations, and central conflict. Do not list individual plot points. Write in third person past/present tense."
  - temperature=0.3, max_tokens=400.
  - Fallback on exception: concatenate first 300 chars of PP001 description + "The adventure culminates in..." + first 300 chars of final plot point description.
  - Empty plot points -> `*No plot data available for summary.*`
- [x] 4.2 Insert `_build_plot_abstract()` call in `_build_intro_section()` before the running-the-adventure text.

**Verification:** Generated output contains narrative abstract text between the intro overview and the individual plot points. Fallback works when LLM is unavailable. (PASS)

## 5. Ancients Lab Regeneration

- [x] 5.1 Run `generate_homebrewery_adventure("The_Ancients_Lab")` and write to `modules/The_Ancients_Lab/MODULE_SUMMARY.md`.
- [x] 5.2 Verify metadata starts with `<!--` (not triple backtick). (PASS)
- [x] 5.3 Verify all 4 locations show `areaName` values, no duplicates. (PASS)
- [x] 5.4 Verify all 9 NPCs have descriptions (none empty). (PASS)
- [x] 5.5 Verify stat blocks use `> ### Name` and include attack/damage lines. (PASS)
- [x] 5.6 Verify credits include author "Kuhal" and license URL. (PASS)
- [x] 5.7 Verify plot abstract paragraph exists before individual plot points. (PASS)

## 6. Test Updates

- [x] 6.1 Update `scripts/test_homebrewery_style_definitions.py`:
  - Metadata test expects HTML comment format (starts with `<!--`).
  - Stat block test expects `> ###` not `> ##`.
- [x] 6.2 Update `scripts/test_homebrewery_adventure_writer.py`:
  - Updated all `## Heading` assertions to `# Heading`.
  - Updated location section split for H1 format.
  - All 78 tests pass (37 style + 41 writer).
- [x] 6.3 Run all tests: `scripts.test_homebrewery_style_definitions` + `scripts.test_homebrewery_adventure_writer` — all pass. (PASS)

**Verification:** All test suites pass with updated assertions. (PASS)

## 7. Final Validation

- [x] 7.1 Run `.venv/bin/python -m py_compile` on all modified Python files. (PASS)
- [x] 7.2 Run all test suites. (PASS - 78/78)
- [x] 7.3 Run ASCII compliance check on modified files. (PASS - 0 violations in new/changed files)
- [x] 7.4 Run `openspec validate toolkit-homebrewery-adventure-md-cleanup`. (PASS - valid)
- [x] 7.5 Verify regenerated `MODULE_SUMMARY.md` content against all 8 issue fixes. (PASS)
