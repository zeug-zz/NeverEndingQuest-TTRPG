# Task 3.5 Apply/Commit and Phase-Transition Extraction

Status: **Task 3.5 checked from parent-primary verification supplied for this checkpoint. This report is not a G3/live verdict.**

## Parent-primary bookkeeping evidence

The parent-primary supplied verification for this checkpoint: **17 separate provider-free suite processes, 291 tests passed, and 9 static prompt hashes unchanged**. This verifies task 3.5 only; it does not establish or claim G3/live acceptance. The detailed task-scoped run record below retains its prior 270-test/14-suite breakdown and describes implementation evidence, not the newer aggregate count.

## Ownership and call-order result

The extracted helpers are called at the validated legacy points; the responsibility labels do not add a linear runtime pipeline.

| Legacy point | State work and existing write intent | New owner | Order retained |
|---|---|---|---|
| Parsed response, before narration | Accept only an integer forward round; set `combat_round` and compatibility `current_round`; start/sync manager round; apply `roundStartsWith` phase/marker state; save encounter; optionally compress and save history | `turn.apply_reported_round_transition` | First, before narration; encounter save precedes compression; when history shrinks, session history binds after compression and before the conditional history save |
| Narration publication | Print the same `Dungeon Master: {narration}` content and flush stdout | Existing owner / forthcoming task 3.6 | Remains between round prep and action handling |
| Per-action processing | Queue character changes/ops; apply each `updateEncounter` immediately, normalize/reload returned state and sync non-PC queue; preserve XP history writes, auto-exit decision and per-action turn queue transitions | `persistence.process_combat_action_batch` | Runs after narration/flush; individual action order and post-action checks remain inside the original loop position |
| After all actions | Clear `openingEnemyBatchPending`, reset `pc_phase_complete`, emit phase diagnostics and save encounter | `turn.complete_opening_enemy_batch` | Remains after action/turn bookkeeping and before consolidated character updates |
| Consolidated character writes | Per-character deterministic ops first, prose updates second; sync successful persisted character state back to manager; preserve failure logging/continue behavior | `persistence.apply_final_character_updates`, through owner compatibility wrapper | Remains after post-batch phase handling |

Exit summary/active encounter cleanup, final history publication and return remain after consolidated character updates. No encounter-last commit, receipt, round-authority, or publication-order change was introduced; those remain deferred to G7. No new narration call was added.

## State and compatibility details

- Round metadata provenance remains AI-reported: only forward integer rounds advance; backwards integers warn and do not change state; non-integers remain ignored.
- Phase 1 initiative gates are untouched. Round `dmGroup`/`pcGroup` marker calls and stable diagnostic strings are retained inside the round owner. Opening-batch completion remains a separate post-action call.
- Immediate encounter mutation still uses the current `update_encounter.update_encounter` owner binding, preserves ops forwarding, result normalization/reload, and immediate queue sync. Removed an unused `encounter_path` keyword at the owner call (the helper never accepted or used it); AST-to-`inspect.signature.bind` coverage locks all three new stage calls and their dependency constructors against signature drift.
- Character ops/prose payloads remain queued and are persisted in the established ops-then-prose order. Successful writes still reload persisted character JSON before manager sync. Old `_queue_final_character_update`, `_sync_multi_pc_character_state`, and `_apply_final_character_updates` callable surfaces remain; the apply helper injects the current owner bindings, including the patchable sync helper. The session encounter is rebound only if immediate update processing supplies a replacement encounter object; when it mutates the existing object, the session alias remains intact.
- Existing early returns, breaks, continues, validation failure behavior, death-save gates, roster eligibility, replay guards, active-PC updates and loop owner remain unchanged in placement. The new unit fixture does not invoke the full loop.

## Function sizes and remaining owner loop

AST line-span measurements after extraction:

| Function | Lines |
|---|---:|
| `persistence.process_combat_action_batch` | 119 |
| `persistence.apply_final_character_updates` | 42 |
| `turn.apply_reported_round_transition` | 68 |
| `turn.complete_opening_enemy_batch` | 17 |
| `_run_combat_simulation_internal` owner | 1,535 |
| Largest remaining owner `while` body | 715 |

The owner loop still owns the full orchestration and preserved control-flow edges, including retry/validation handoff consumption, narration publication, loop continue/return decisions, final combat summary/cleanup and history save. It is not claimed to be fully decomposed; remaining work belongs to later assigned tasks and the overall planner.

## Verification

All commands were run as separate processes where specified.

### Task-required suites

| Command | Result |
|---|---|
| `.venv/bin/python -m unittest -q scripts.test_combat_pc_action_parser` | PASS, 28 tests |
| `.venv/bin/python -m unittest -q scripts.test_combat_resume_replay_guards` | PASS, 7/7 tests. The brittle assertions now check helper imports/calls, source argument identity, user-history append shape, and absence of fresh action/reward operations via AST. `main.py` and `core/ai/action_handler.py` were not edited. |
| `.venv/bin/python -m unittest -q scripts.test_update_encounter_ops_runtime` | PASS, 4 tests |
| `.venv/bin/python -m unittest -q scripts.test_combat_persistence_phase_stages` | PASS, 10 tests |

The new focused tests exercise actual extracted stage APIs with injected callbacks for 1-PC/4-PC round processing, initiative tie resolution and opening `dmGroup` marker ordering, mixed queued character ops/prose and immediate enemy ops, authoritative encounter normalization/roster resync, allied-NPC auto-advance, ACTED-PC advancement, exit XP-history writes, apply-failure fallthrough, and immediate encounter-error continuation. The actual owner AST calls are bound against each current helper and dependency signature with `inspect.signature.bind` (including `CombatActionDependencies`), catching extra/missing parameters such as the removed unused `encounter_path` keyword; the test also asserts validation/replay handoff precedes round/action stage calls. Tests arm the shared provider/network tripwire, use `BaseException`-derived write guards on file/OS mutation APIs, and use fake persistence/status/compression/logger/manager callbacks. They do not invoke the owner loop, a real SDK/provider, campaign data, or a global API logger.

### Previous 270-test suite set, each in a separate process

Fourteen suites ran as separate processes, accounting for 270 tests: **270 passed; 0 failed**. The task-3.5 source anchors were repointed to the extracted phase/action owners using positive AST/import-binding and semantic assertions. The historical-summary caller tests now verify helper imports/calls, user-history append shape, and absence of fresh action/reward operations without depending on formatting.

| Suite | Result |
|---|---|
| `scripts.test_combat_retry_stage` | PASS 11/11 |
| `scripts.test_combat_validation_stage` | PASS 8/8 |
| `scripts.test_combat_validation_routing` | PASS 11/11 |
| `scripts.test_combat_phase_integrity_precheck` | PASS 14/14 |
| `scripts.test_combat_retry_hygiene` | PASS 3/3 |
| `scripts.test_combat_truth_pack` | PASS 6/6 |
| `scripts.test_combat_runtime_prompt_authority` | PASS 7/7; round marker/phase sync anchor points to `turn.apply_reported_round_transition`. |
| `scripts.test_combat_manager_decomposition_contract` | PASS 27/27 |
| `scripts.test_combat_payload_hygiene` | PASS 4/4 |
| `scripts.test_multi_pc_combat` | PASS 73/73 |
| `scripts.c5_regression_combat` | PASS 59/59; relocated ops/resync and phase-marker contracts now inspect their actual helper owners and keep positive semantic checks. |
| `scripts.test_combat_pc_action_parser` | PASS 28/28 |
| `scripts.test_combat_decisions` | PASS 10/10 |
| `scripts.test_combat_decomposition_contract` | PASS 9/9 |

Additional checks:

- `.venv/bin/python -m py_compile core/combat/persistence.py core/combat/turn.py core/combat/combat_manager.py scripts/test_combat_persistence_phase_stages.py scripts/c5_regression_combat.py scripts/test_combat_runtime_prompt_authority.py scripts/test_combat_resume_replay_guards.py` -> PASS.
- `python3 scripts/check_ascii_compliance.py --summary-only` -> PASS, 0 violations across 749 scanned files.
- `git diff --check -- core/combat/combat_manager.py` -> PASS.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate combat-manager-decomposition --strict` -> valid.
- The decomposition contract suite checked the nine frozen static combat-prompt hashes; it passed with all 9 unchanged. No prompt asset was edited.

## Planner follow-up

Task 3.5 is checked with parent-primary evidence above. No G3/live acceptance claim is made.
