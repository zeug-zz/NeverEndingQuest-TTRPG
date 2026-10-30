# Task 5.1 - Startup Bootstrap and Narration Slices

Status: **Task 5.1 primary verification PASS. G3 remains open and is not passed.**

## Responsibility moved

- Added `core/combat/bootstrap.py` to own history ownership selection, the fresh
  system-prompt head, fresh history hydration, and resumed player/NPC narrative
  payload refresh. These operations form one startup history-bootstrap boundary;
  they are split among named selection, prompt construction, payload, and
  hydration functions, not a renamed oversized owner.
- This slice also moved the real fresh initial-scene generation/validation retry
  body, resume re-engagement request, fast-lane early return, history update, and
  initial/resume narration output. It is implemented as `_run_resume_narrative`,
  `_build_initial_scene_prompt`, `_run_initial_scene_generation`, and the
  `run_startup_narrative` branch owner; each has an explicit typed input or
  dependency/result contract.
- The third slice moved party/module path resolution, encounter read and early
  failure, session creation/binding, phase-1 normalization and its writes, manager
  reuse/creation, queue and persisted-round sync, history selection/fresh head,
  secondary-history resets, and PC/unique-monster/fuzzy-NPC template loading into
  `load_encounter_and_bind_session`, `load_combatant_templates`, and
  `initialize_combat_session`. The output types preserve the same session,
  encounter/history aliases, path/party state, player file/info, templates,
  resume/multi-PC flags, and legacy tuple early return.
- `CombatHistoryDependencies` explicitly injects file existence/size/read/write,
  prompt selection, formatters, dynamic/encounter filters, logging, output, and
  cache removal. `CombatHistoryResult` explicitly hands back the exact mutable
  history list and fresh/resume decision. The legacy `CombatSession` remains the
  same object and still owns/binds history, encounter, manager, active PC, and
  phase; semantic payload application still uses that session.
- `CombatInitializationDependencies` binds the existing owner loader,
  normalization callback, manager getter/factory, NPC loader, file I/O, and
  diagnostics on demand. The extracted helpers import no SDK or configuration
  modules at module import time.
- The final slice moved initial HP/status/condition/spell-slot/roster/preroll
  preparation to `prompts.py`; per-turn sync/status/history/actor prompt/input to
  `begin_combat_turn_iteration`; existing phase/fast/deterministic/stat/decision/
  inventory/context glue to `prepare_combat_normal_turn`; bounded action trace
  metadata to `trace_combat_action_batch_metadata`; and final summary/encounter
  cleanup/history save/last-player read to `finalize_combat_session`.
- `_run_combat_simulation_internal` is now 479 lines versus 1,059 before this
  final slice (580 lines reduced; 1,153 lines reduced from the supplied 1,632-line
  baseline). AST inspection covered all 261 functions in `core/combat/`: none
  exceed 600 lines. The 17-line legacy shim remains below 100.

## Final AST maximum-function table

The table is the 20 largest functions from the full 261-function AST scan; all
remaining functions are smaller, and the scan found no function over 600 lines.

| Lines | Owner | Function |
|---:|---|---|
| 479 | `core/combat/combat_manager.py` | `_run_combat_simulation_internal` |
| 413 | `core/combat/prompts.py` | `assemble_combat_context` |
| 343 | `core/combat/multi_pc/manager.py` | `handle_combat_command` |
| 307 | `core/combat/validation.py` | `validate_combat_response` |
| 230 | `core/combat/turn.py` | `run_combat_provider_retry_stage` |
| 205 | `core/combat/combat_manager.py` | `_build_compact_combat_truth_pack` |
| 185 | `core/combat/turn.py` | `prepare_combat_normal_turn` |
| 180 | `core/combat/turn.py` | `run_input_phase_gate` |
| 170 | `core/combat/turn.py` | `begin_combat_turn_iteration` |
| 158 | `core/combat/combat_manager.py` | `summarize_dialogue` |
| 153 | `core/combat/combat_manager.py` | `format_character_for_combat` |
| 145 | `core/combat/combat_manager.py` | `compress_old_combat_rounds` |
| 141 | `core/combat/combat_manager.py` | `format_npc_for_combat` |
| 134 | `core/combat/prompts.py` | `prepare_initial_combat_state` |
| 127 | `core/combat/persistence.py` | `process_combat_action_batch` |
| 125 | `core/combat/bootstrap.py` | `_run_initial_scene_generation` |
| 111 | `core/combat/multi_pc/manager.py` | `resolve_death_save_roll` |
| 104 | `core/combat/bootstrap.py` | `_run_resume_narrative` |
| 96 | `core/combat/combat_manager.py` | `_build_normal_turn_dependencies` |
| 94 | `core/combat/multi_pc/state.py` | `initialize_from_party` |

## Nine responsibility owners at their legacy call points

| Responsibility | Real owner / call boundary |
|---|---|
| Input/phase gate | `turn.run_input_phase_gate`, called by `prepare_combat_normal_turn` |
| Fast commands | `commands.run_fast_commands_stage`, called immediately after the gate |
| PC-action decision | `decisions.run_pc_action_decision`, before inventory/context fallback |
| Context/prompt | `prompts.assemble_combat_context` and `prepare_initial_combat_state` |
| Provider retry | `turn.run_combat_provider_retry_stage`, after the prompt is saved |
| Validation | `validation.validate_combat_response`, injected into the existing retry stage |
| Apply/commit | `persistence.process_combat_action_batch` and the existing consolidated update commit |
| Phase transitions | `turn.apply_reported_round_transition` and `complete_opening_enemy_batch` at the prior points |
| Narration/output | `narration.publish_combat_narration` before action application; startup branches remain in `bootstrap.py` |

## Preserved contracts

- History file existence and `>100` size gate, encounter-ID lookup among the
  first three system messages, matching-resume decision, stale-history discard,
  prompt asset choice and placeholder replacement remain explicit.
- Fresh history retains its five system-message slots. At the legacy point it
  clears the same two compression caches, applies semantic history payloads,
  preserves the no-monster early `(None, None)` return, appends NPC messages and
  encounter details, logs the structure, and writes history in that order.
- Resume keeps the semantic payload refresh, head update, old NPC-template and
  individual-NPC removal behavior, insertion position, save, and output order.
  Player/NPC formatter callbacks, dynamic-field filtering and encounter filtering
  remain injected legacy callables. No model/provider/client is constructed by
  the bootstrap module.
- The existing owner continues to bind the returned history to the same session
  instance and updates `active_pc` at its previous call point. This slice does
  not change cached HP/max/temp/preroll/round aliases, prompts, state mutation,
  persistence, or G7 publication ordering.

## Startup side-effect comparison

| Branch | Provider/compression/validation | Writes and history | Output/temperature handoff |
|---|---|---|---|
| Fresh fast-lane | Zero provider calls, compression calls, or validation calls | Zero history/debug-export writes; no synthetic narration | Same initiative prefill and immediate flush; input `temperature_used` is returned unchanged |
| Fresh initial scene | Same initial path: at most 3 provider attempts; compression/export once per attempt; JSON validation only for accepted JSON; response validation only after JSON validity | Initial user prompt is saved once; every attempted request writes the existing debug payload; history is truncated to the saved prompt length and rebound; a truthy final response is appended and saved | Same initial-scene prompt text, normal narration prefix or raw-response fallback, then immediate flush; final computed temperature and retry handoffs returned |
| Resume GPT-5 | One request, no new validation/retry; compressed history; no timeout or temperature override | Save resume prompt only when it is not already last; one debug export; append/save assistant response | GPT-5 mini request params and `{"branch":"gpt5","context":"re-engage"}` API-log metadata retained; initial temperature handoff is unchanged |
| Resume legacy model | One request, no new validation/retry; compressed history; no timeout | Same conditional resume-prompt save, one debug export, append/save assistant response | Temperature recomputed at attempt 0 and forwarded as `temperature_override`; legacy API-log metadata retained |
| Common initialization | No provider operation | Party tracker read, module path resolution, encounter read, normalization saves, manager/queue work, history selection, secondary-history resets, then ordered player/monster/NPC reads | Same diagnostics and early `(None, None)` adapter; persisted round and active-PC selection are returned with the same session |
| Initial mechanical context | No provider call | Reload current PC file, fuzzy-load NPC max HP, build roster, generate/cache prerolls, save the encounter once at the prior point | Return the exact player/template/HP/max/round/preroll handoffs to initial-scene generation |
| Per-turn input prelude | No provider call | When multi-PC is active, read party tracker; sync active actor/phase, clear status, sync encounter/HP, refresh player/encounter/NPC history, save history, then read input | Same status and actor prompt; EOF returns the same structured quit result, blank input and gate/command outcomes continue at their old points |
| Normal input to prompt | Existing gate, fast-command, deterministic-command, stat-command, parser-decision, inventory, and context operations only | Handled commands retain their writes; declined/unavailable parsing falls through; clean history, append the user prompt, and save before retry | The accepted prompt context and cached HP/max/player file/round are typed handoffs to the unchanged retry stage |
| Validated response through completion | No added provider call | Keep narrated output before immediate action/queue handling; complete phase transition, apply consolidated character updates, then summary, encounter cleanup, chat-history write, and final player reload | Output is immediately flushed; completion tuple and finally-based claim release remain owned by existing boundaries |

Usage-tracking failures remain fail-open in the initial and resume paths, with
their existing warning behavior. Resume request/parse errors still publish the
same fallback line and flush. Tests use fake clients, compressors, persistence,
validators, clocks, loggers, and status-independent callbacks; no live request or
campaign write occurred.

## Verification

- Focused first: `scripts.test_combat_bootstrap` -> 24/24 passed. Fatal network,
  SDK-import, and write guards are installed before importing the provider-free
  module. Cases cover fast-lane zero calls/writes; resume GPT-5 and legacy request
  contracts; duplicate resume-prompt handling; initial JSON retry, validation
  exhaustion and provider abort; usage-tracking fail-open; exact event/write,
  history, output, temperature and cached-session handoffs; 1-PC/4-PC active-PC
  state; EOF/quit, fast command and declined-parser fallthrough; action output,
  failed/successful response handoffs, finalization order, and trace metadata;
  cached-manager reuse versus creation; normalization/read/write order; templates;
  early aborts; and owner AST/signature bindings.
- The previous affected regression set ran in 32 separate unittest processes ->
  617 tests passed, zero failed. It covers the owner, C5, multi-PC, parser,
  prompt/validation, retry, persistence, resume, narration, encounter, capture,
  retry, validation, prompt authority, combat operation, and router contracts.
  The separate source-authority coverage includes GPT-5.6 request-parameter tests.
  A separate run of
  `scripts.test_supernatural_state_layer` remains one known unrelated failure in
  `test_character_sheet_ui_projects_supernatural_state`; that UI assertion was
  not changed or included in the final affected set.
- `py_compile` for the owner, bootstrap module, and touched source-contract tests
  -> PASS.
- `python3 scripts/check_ascii_compliance.py --summary-only` -> PASS (755 files,
  zero violations). `git diff --check` -> PASS.
- Final owner AST size check -> 479 lines; all 261 combat-package functions are
  <=600 lines and the legacy shim is 17 lines. Local structural gates pass;
  primary's full size/source-contract verification is recorded below.

## Primary verification note

- AST boundary gate: 261 combat-package functions inspected; maximum owner is
  `_run_combat_simulation_internal` at 479 lines, followed by
  `assemble_combat_context` at 413 lines; no function exceeds 600 lines and the
  legacy compatibility shim is 17 lines (below the 100-line limit).
- Reviewed actual typed bootstrap, turn, persistence, and call-graph ownership.
  The large loop is decomposed across the nine responsibility owners at their
  established call points; it was not relocated intact and no reflection-based
  relocation is used.
- Three frozen prompt cases and the 9-case static prompt parity check passed.
- This is the primary's 5.1 structural verdict only. It does not assert a G3
  capture, live readiness, or rollout acceptance.

## Remaining work / evidence boundary

- The requested size-fix slices and primary size/source-contract gate are
  complete. G3 remains a separate primary-owned live gate.
- No live capture, campaign/provider call, or G3 verdict is claimed here.
