# Task 3.3 Context/Prompt Extraction Verification

Status: **Implementation and provider-free parity checks complete for Task 3.3. The task checkbox remains unchecked for planner verification. No G3/live-capture claim.**

## Scope and ownership

- Moved the post-decision context/prompt stage into `core/combat/prompts.py::assemble_combat_context(...)` with typed `CombatContextInputs`, `CombatContextDependencies`, and `CombatPromptResult`.
- The package stage now owns the fresh current-PC read, NPC max-HP reads, roster collection, preroll cache decision and save callback, initiative tracker parsing and fallback decision, AC lookup, required-response selection, dynamic-state/party context, and final user-prompt serialization.
- The old AI initiative-tracker fallback is passed as a callback. Its package import remains inside `_generate_live_initiative_tracker_fallback()` and is called only when the multi-PC tracker is absent or failed, as before. `prompts.py` has no provider/SDK/client/factory imports.
- Owner code performs the separately measured-excluded inventory enhancement through `enhance_combat_input_with_inventory(...)`, calls the package stage, handles its early `(None, None)` return, explicitly unpacks results, then proceeds to existing history cleanup and provider loop.
- The context API returns the post-stage locals used by the rest of the owner loop, including `encounter_data`, `player_info`, `player_file`, `path_manager`, `current_actor`, `current_round`, `current_hp`, `max_hp`, tracker/window/preroll values, dynamic state, and `user_input_with_note`. The owner explicitly unpacks returned HP/max HP so a later context invocation can receive the last observed values if the next fresh read fails. `check_all_monsters_defeated` now belongs to `prompts.py` because the owner uses that predicate again after action application.
- Inventory enhancement remains outside the reviewed parity boundary, as the guarded baseline started at `dynamic_state_parts`. Its separate provider-free test locks the character path/read/enhancer order, combat flag, input fallback, and carry-forward of the pre-context character read.

## Dynamic user-prompt parity (reviewed fixed fixtures)

The test invokes the **whole** `assemble_combat_context` API with the copied inline `FixtureManager`, synthetic encounter/party/character records, fake reads/writes/loggers, and lazy-fallback callback. It does not supply assembled prompt components or read `tmp/`/old Git source. SHA-256 and UTF-8 byte length are asserted against the reviewed `before_outputs.json` constants; dynamic-state bytes are also compared directly with inline fixed expected strings.

| Fixture case | Expected pre-extraction prompt SHA-256 | Bytes | Expected dynamic-state SHA-256 | Bytes | After API prompt | After dynamic bytes | Helper calls | Write intents |
|---|---|---:|---|---:|---|---|---:|---:|
| `one-pc-pc-phase` | `74ddf6085ae97c6cdf4db1f6e9c44efbf1215b9f686c8e69f5f5186df55c1abc` | 1842 | `aaf0c92a915390caae10808a3548bb128fa2f600483962eacd236b3e202722a0` | 571 | exact match | exact string/hash/length | 9, exact ordered sequence | 0 |
| `four-pc-active-rotation` | `d8a918288a02bc0bf0ad438ed6956774cbe54f33bcde658ae6ca46fc98813a6b` | 1925 | `63a10e4a90ad4373b279e011c8b4d36aa7b29924ba7b0567bc7272241ab8f412` | 625 | exact match | exact string/hash/length | 9, exact ordered sequence | 0 |
| `four-pc-enemy-phase-resume-ledger` | `6b8e0ca216870084f87f23d284142b460bdb5529c871d2f34d9287874538bba4` | 1976 | `2a221f491951f7138a071a3bfe242b51df0568e1d09baa6d45a589abc829b119` | 627 | exact match | exact string/hash/length | 9, exact ordered sequence | 0 |

The nine fixture helper observations per case are: current-player `safe_json_load`; `load_npc_with_fuzzy_match:Scout Kira`; authoritative roster collection; manager initiative tracker; current actor; required-response prompt; remaining enemies; party turn summary; active-PC prompt context. The actual tests assert each ordered list and `writes == []`; counts are not generated from the renderer. Static baseline fixture files under `tmp/combat_prompt_parity_33/` were only read and were not overwritten.

## Existing policy branches and byte sources

- **Cached preroll:** all three frozen cases use round 3/cache round 3; they retain the cached pool and record zero save intents.
- **Round advanced/cache missing:** provider-free changed-round coverage changes the encounter to round 4 and asserts one generator request, one `save_json_file` intent at the fixture encounter path, and the prior cache shape/ID policy (`4-1234`). A second branch keeps round 3 but omits cached rolls and asserts exactly one fallback generation/write with the existing `3-1234` ID format.
- **Tracker failure:** the fake deterministic tracker returns `None`; the injected lazy fallback receives precisely the last six history messages and round 3. When it also returns `None`, the stage returns the existing early `(None, None)` result. No production tracker import occurs in tests.
- **Fresh character read missing/error:** both a missing record and a fake `OSError` keep stale owner HP and spell-slot values, matching the prior stale-data fallback. The inventory pre-step has its own explicit read/enrichment order and fail-open-input test; that pre-step is not claimed as baseline parity coverage.
- **Static prompt bytes:** all 9 assets match their frozen SHA-256 values (the `test_static_combat_prompt_assets_retain_all_nine_frozen_hashes` test checks every literal path/hash).

## Before/after structure

- Reviewed source boundary: the old owner block began with `dynamic_state_parts` and ended at the user-prompt assignment, around 445 source lines including comments/whitespace. The pre-baseline inventory enrichment was immediately before this range and is now a separate helper.
- New `assemble_combat_context`: **410 source lines**, largest new function; other prompt module functions: `enhance_combat_input_with_inventory` 23, `check_all_monsters_defeated` 15, `build_dynamic_state` 27, `assemble_combat_prompt` 31 lines.
- Current `_run_combat_simulation_internal`: **1,912 source lines** (AST line span 2903-4814). The prior task-3.3 owner-loop line count was not separately recorded in the reviewed AST baseline, so no whole-loop delta is claimed. The owner now contains typed stage construction, early-result handling and explicit handoff assignments rather than the moved context body.
- Functions in `prompts.py` are below the 600-line contract. No production reflection, source slicing, dynamic execution, globals/locals dictionaries, or generated code was introduced.

## Verification

Each command ran in a separate process with `.venv/bin/python`:

- `scripts.test_combat_decomposition_contract` — **9 passed** (three exact prompt+dynamic-state fixtures, static nine-hash check, pure-module import/code-generation contract, changed-round and missing-cache write policy, failed-tracker fallback, missing/failed-fresh-read fallback, sequential HP/max-HP result handoff with stale `player_info` status/condition fallback and fresh spell-slot carry-forward, owner AST result-unpack contract, inventory pre-step contract).
- `scripts.test_combat_runtime_prompt_authority` — **7 passed**.
- `scripts.test_combat_payload_hygiene` — **4 passed**.
- `scripts.test_combat_manager_decomposition_contract` — **27 passed**.
- `scripts.test_multi_pc_combat` — **73 passed**.
- `scripts.c5_regression_combat` — **59 passed**.
- `scripts.test_combat_pc_action_parser` — **28 passed**.
- `scripts.test_combat_decisions` — **10 passed**.
- Targeted `py_compile` for the implementation and touched tests — **passed**.
- `git diff --check` — **passed**.

The new stage tests install the shared `ProviderTripwire`, assert it remained untouched, deny real `builtins.open` write modes, and trap direct `os` write/mutation APIs. They inject fake path/read/write/provider-fallback dependencies. No application combat loop, real initiative fallback, provider call, network request, credential read, or campaign runtime was used. The pre-existing full-loop harness failure and incident diagnostics remain unchanged. G3 is not established by these unit tests.
