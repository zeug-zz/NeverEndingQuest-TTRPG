# Tasks

## 0. Scaffold And Roadmap

- [x] 0.1 Update `plans/accurate-ingest-fix.md` to reflect archived builder-audit briefing and ModuleBuilder handoff, and identify generator source locks as next step.
- [x] 0.2 Create OpenSpec proposal, design, tasks, delta specs, and builder prompt artifact.
- [x] 0.3 Validate the OpenSpec scaffold.

> `openspec validate toolkit-accurate-ingest-generator-source-locks` -> valid.

## 1. Builder Input Monster/Encounter Source Contract

- [x] 1.1 Add provider-free regression tests proving source-enhanced `builder_input` includes `source_monster_refs` and `source_encounter_seeds` when the normalized packet contains them. (Provider-free tests added for ready-blueprint and degraded packet-only fixtures.)
- [x] 1.2 Implement minimal extraction of monster refs and encounter seeds into `builder_input` without leaking into legacy/non-source paths.
- [x] 1.3 Add persistence assertions proving `builder_input.json` contains the new fields.
- [x] 1.4 Verify existing explicit seed writer modes and legacy concept-builder path remain compatible.

## 2. ModuleBuilder Downstream Source Context

- [x] 2.1 Add provider-free tests proving ModuleBuilder receives source-enhanced context from `_execute_module_builder(...)`. (Provider-free source-context handoff test added.)
- [x] 2.2 Add a compact source-context serialization helper for ModuleBuilder use.
- [x] 2.3 Ensure source context includes NPCs, locations, puzzles, monsters, encounters, tone, and source-lock rules.
- [x] 2.4 Verify no live provider calls are required for tests.

## 3. Generator Prompt Source Locks

- [x] 3.1 Add source-contract tests for `ModuleGenerator` prompt/context inclusion.
- [x] 3.2 Add source-contract tests for area/location generation prompt/context inclusion.
- [x] 3.3 Add source-contract tests for plot generation prompt/context inclusion.
- [x] 3.4 Add minimal source-lock prompt/context injection while preserving legacy generation behavior.

## 4. Final Verification

- [x] 4.1 Run compile checks for modified Python files. (PASS — all 7 files compile clean)
- [x] 4.2 Run targeted packet builder and generator source-contract tests. (16/16 PASS)
- [x] 4.3 Run existing blueprint and GUI unified-flow tests for compatibility. (142/142 PASS — cross-suite: gui_unified_flow + blueprint_v2_contract + generator_source_locks)
- [x] 4.4 Validate the OpenSpec change. (PASS — `openspec validate` valid; `git diff --check` clean)

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py core/generators/module_builder.py core/generators/module_generator.py core/generators/area_generator.py core/generators/location_generator.py core/generators/plot_generator.py
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end
openspec validate toolkit-accurate-ingest-generator-source-locks
```
