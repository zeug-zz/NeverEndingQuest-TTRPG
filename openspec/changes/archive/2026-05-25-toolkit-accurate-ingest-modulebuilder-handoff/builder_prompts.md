# Builder Prompts: Accurate-Ingest ModuleBuilder Handoff

## Step 0 Verification

Step 0 updated `plans/accurate-ingest-fix.md` to reflect the archived Numillian source-fidelity pass and scaffolded `toolkit-accurate-ingest-modulebuilder-handoff`.

Current state:

- Active OpenSpec changes: none before this scaffold.
- Numillian source fidelity: pass.
- NPC: 23/23.
- Location: 13/13.
- Puzzle: 3/3.
- Dirty Numillian module artifacts remain intentionally uncommitted.

Step 0 artifacts:

- `proposal.md`
- `design.md`
- `tasks.md`
- `specs/accurate-ingest-modulebuilder-default-handoff/spec.md`
- `specs/accurate-ingest-builder-input-source-contract/spec.md`
- `specs/accurate-ingest-seed-writer-explicit-support-role/spec.md`
- `specs/accurate-ingest-handoff-artifact-reporting/spec.md`
- `builder_prompts.md`

Verification:

```bash
openspec validate toolkit-accurate-ingest-modulebuilder-handoff
```

## Step 1.1 Verification

Step 1.1 test already exists and passes.

**Existing test**: `TestPacketBuilderV2Integration.test_default_no_seed_mode_uses_module_builder` in `scripts/test_toolkit_homebrew_gui_unified_flow.py:344`.

**Coverage against MUST requirements:**

- [x] Provider-free regression test with v2 workspace, no `seed_writer_mode`.
- [x] Patches `_execute_module_builder(...)` and `_execute_seed_writer_build(...)`.
- [x] Asserts `_execute_module_builder(...)` called exactly once (`mock_executor.assert_called_once()`).
- [x] Asserts `_execute_seed_writer_build(...)` not called (`mock_seed.assert_not_called()`).
- [x] Asserts `build_mode` is `source_enhanced_modulebuilder`.
- [x] Asserts no `seed_writer_mode` in result when none supplied.
- [x] No live LLM/provider calls.
- [x] Existing explicit seed writer mode tests pass.
- [x] Full suite passes: 79/79 tests.

## Verification Gate After Step 1.1

- [x] Test file compiles.
- [x] GUI unified-flow test suite passes.
- [x] OpenSpec change validates.
- [x] No module files changed.

## Next Step Ready

After Step 1.1 passes, proceed to Step 1.2.

---

## Step 1.2 Verification

Step 1.2 test added. Added `test_seed_writer_mode_explicit_fallback` to `TestPacketBuilderV2Integration` matching the `preview`/`support` pattern.

- [x] `fallback` mode: `_execute_seed_writer_build` called once, `build_mode == "blueprint_seed_fallback"`, `seed_writer_mode == "fallback"`.
- [x] `preview` mode: existing test asserts `build_mode == "blueprint_seed_preview"`, `seed_writer_mode == "preview"`.
- [x] `support` mode: existing test asserts `build_mode == "blueprint_seed_support"`, `seed_writer_mode == "support"`.
- [x] Invalid mode: `test_seed_writer_mode_invalid_fails_closed` asserts `seed_writer_mode_invalid` + `allowed_modes`.
- [x] All provider-free.
- [x] Full suite passes: 80/80 tests.

## Verification Gate After Step 1.2

- [x] Test file compiles.
- [x] GUI unified-flow test suite passes.
- [x] OpenSpec change validates.
- [x] No module files changed.

## Next Step Ready

After Step 1.2 passes, proceed to Step 1.3.

---

## Step 1.3 Verification

Step 1.3 test added. Added `test_handoff_includes_source_contract_npc_location_puzzle_tone` to `TestPacketBuilderV2Integration`.

Coverage:

- [x] Patches `_execute_module_builder` and captures `builder_input` argument.
- [x] Asserts `handoff_mode == "source_blueprint"`.
- [x] Asserts all four `source_lock` fields: `canonical_names_locked`, `invented_major_entities_forbidden`, `replacement_plotlines_forbidden`, `puzzle_rule_rewrite_forbidden`.
- [x] Asserts source artifact paths (`source_graph`, `plot_topology_report`).
- [x] Asserts Numillian source NPC names (Adhagal, Belrik Dumma-dhur, Xaereal the Constructor) present in referenced workspace blueprint.
- [x] Asserts Numillian source location names (Charion Tamer, The Rookery, Handworks Guild) present.
- [x] Asserts puzzle/challenge tokens (`skull_riddle`, `flooding_room`, `kill_the_dog_mindscape`) present.
- [x] Asserts tone marker (`quirky_character_driven_hidden_city`) present.
- [x] Provider-free (no live LLM).
- [x] Full suite passes: 81/81 tests.

Note: NPC/location/puzzle/tone tokens are currently verified in the workspace blueprint (which `builder_input.blueprint.blueprint_path` references). Step 2.2 will add direct serialization of these tokens into the `builder_input` artifact itself.

## Verification Gate After Step 1.3

- [x] Test file compiles.
- [x] GUI unified-flow test suite passes: 81/81.
- [x] OpenSpec change validates.
- [x] No module files changed.

## Next Step Ready

After Step 1.3 passes, proceed to Step 1.4.

---

## Step 1.4 Verification

Step 1.4 added 3 fail-closed tests:

- [x] `test_blocked_blueprint_does_not_call_module_builder`: blocked blueprint (`blueprint_status="blocked"`) patches `_execute_module_builder`, asserts `mock_executor.assert_not_called()`, asserts result `status == "failed"` with `blueprint_not_ready`.
- [x] `test_blocked_report_does_not_call_module_builder`: ready blueprint + blocked report (`blueprint_status="blocked"`) asserts executor not called.
- [x] `test_empty_blueprint_fails_closed`: empty `{}` blueprint + ready report asserts executor not called.
- [x] All patch `_execute_module_builder` and assert not called.
- [x] Provider-free.
- [x] Full suite passes: 84/84 tests.

Note: All three work because `_classify_blueprint_handoff` returns `blueprint_required_not_ready` when either artifact is non-ready (line 356-357). The existing `test_v2_required_but_not_ready_fails_closed` (line ~278) covers the `ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD=True` gate for blocked blueprints but does not assert executor was skipped — the new tests cover that gap.

## Verification Gate After Step 1.4

- [x] Test file compiles.
- [x] GUI unified-flow test suite passes: 84/84.
- [x] OpenSpec change validates.
- [x] No module files changed.

## Next Step Ready

All Section 1 handoff regression locks are complete. Proceed to Section 2: Handoff Artifact Enrichment.

---

## Section 2 Verification

Section 2 implemented source-contract enrichment on `builder_input`:

- [x] 2.1: Current `builder_input` shape documented. Builder input had `packet_identity`, `review_snapshot`, `derived_builder_parameters`, `builder_narrative`, and optionally `blueprint` metadata with `source_lock` + `source_artifacts`. NPC/location/puzzle/tone tokens were only in the referenced workspace blueprint.
- [x] 2.2: Added extraction from `blueprint_artifact` into `builder_input` at lines ~569-602 of `toolkit_homebrew_packet_builder.py`. Four new fields: `source_npc_names`, `source_location_names`, `source_puzzle_ids`, `source_tone`.
  - NPC/location names: reads `name` or `display_name` (production blueprints use `display_name`).
  - Puzzle IDs: reads `puzzle_id` or `chain_id` or `title` (production blueprints use `chain_id`/`title`).
  - Tone: normalizes string to single-item list (production blueprints use a tone string).
- [x] 2.3: `persist_builder_input_artifact` serializes the dict as JSON — new fields included automatically.
- [x] 2.4: Strengthened test with production-like fixture (`display_name`, `chain_id`/`title`, tone as string) and persistence assertion (reads `builder_input.json`). Corrective patch 2026-05-25.
- [x] Full suite passes: 84/84 tests.
- [x] OpenSpec validates.

## Verification Gate After Section 2

- [x] Test file compiles.
- [x] Packet builder compiles.
- [x] GUI unified-flow test suite passes: 84/84.
- [x] OpenSpec change validates.
- [x] No module files changed.

## Next Step Ready

Proceed to Section 3: Routing and Reporting Verification.

---

## Section 3 Verification

Section 3 verified routing and reporting across all build paths:

- [x] 3.1: `test_default_no_seed_mode_uses_module_builder` asserts `build_mode == "source_enhanced_modulebuilder"`.
- [x] 3.2: Existing fallback/preview/support tests assert correct `build_mode` for each seed writer mode.
- [x] 3.3: Added `test_legacy_non_source_path_routes_to_module_builder` — patches `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF=False`, asserts executor called, `build_mode == "packet_workspace_v1"`.
- [x] 3.4: 28 Numillian files have pre-existing diffs from `56bab1d` (May 23). Our change touched only 2 files. No new Numillian modifications.
- [x] Full suite passes: 85/85 tests.
- [x] OpenSpec validates.

## Verification Gate After Section 3

- [x] Test file compiles.
- [x] GUI unified-flow test suite passes: 85/85.
- [x] OpenSpec change validates.
- [x] No new Numillian module changes.

## Next Step Ready

Proceed to Section 4: Final Verification.

---

## Section 4 Builder Prompt (full variant)

```text
Implement OpenSpec `toolkit-accurate-ingest-modulebuilder-handoff` Section 4 only (tasks 4.1-4.4).

Goal: Final compile, test, and validation sweep before closing the change.

Allowed:
- Read-only reference to:
  - `scripts/test_toolkit_homebrew_gui_unified_flow.py`
  - `web/extensions/toolkit_homebrew_packet_builder.py`
  - `openspec/changes/toolkit-accurate-ingest-modulebuilder-handoff/**`

Required MUSTs:
- Run compile checks for all modified files.
- Run full GUI packet builder test suite.
- Run blueprint v2 contract tests.
- Run Numillian end-to-end tests.
- Validate the OpenSpec change.
- Confirm no Numillian module artifacts were modified.

Verify:
- `.venv/bin/python -m py_compile web/extensions/toolkit_homebrew_packet_builder.py scripts/test_toolkit_homebrew_gui_unified_flow.py scripts/test_toolkit_blueprint_v2_contract.py scripts/test_accurate_ingest_numillian_end_to_end.py`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow`
- `.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract`
- `.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_end_to_end`
- `openspec validate toolkit-accurate-ingest-modulebuilder-handoff`
- `git diff --stat modules/The_Hidden_City_of_Numillian/` (confirm no new diffs)

Stop:
- Do not archive the change.
```

## Section 4 Verification

Section 4 final verification sweep complete:

- [x] 4.1: Compile check passes for all 4 targets (`toolkit_homebrew_packet_builder.py`, `test_toolkit_homebrew_gui_unified_flow.py`, `test_toolkit_blueprint_v2_contract.py`, `test_accurate_ingest_numillian_end_to_end.py`).
- [x] 4.2: GUI packet builder tests: 85/85 pass.
- [x] 4.3: Blueprint v2 contract tests: 33/33 pass.
- [x] 4.4: Numillian end-to-end tests: 46 pass, 3 skipped.
- [x] OpenSpec validates.
- [x] No Numillian module artifacts modified by this change (29 Numillian diffs are pre-existing from `56bab1d`).

## Verification Gate After Section 4

- [x] Compile checks pass.
- [x] All 3 test suites pass.
- [x] OpenSpec validates.
- [x] No new Numillian module changes.

## Ready for Archive

All 4 sections complete. Change can be archived when confirmed.


