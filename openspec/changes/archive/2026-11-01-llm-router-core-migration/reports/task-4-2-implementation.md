# Task 4.2 - Transition Narration Router Migration

Status: implementation and fresh guarded verification of the 11 focused
transition and core suites completed. Primary scoped source review and software
verification: PASS. Task 4.2 is checked; 17/25 change tasks are checked and
14/15 semantic operations are migrated. This is not a live G4 or full-goal
completion claim. No live provider, server, or full `process_action`/game-loop
run was performed.

## Implementation

- Transition narration now calls `llm.call(task="dm_main", json_output=False)`
  with the original `temperature=0.7`. The `transition_messages` construction
  remains unchanged, and returned facade text is stripped at the former content
  boundary.
- The old caller-owned client/model/fallback SDK branches were removed. One
  per-call receipt observer preserves usage gating and opts into the existing
  `transition_narration` trace site. No API logger was added. Receipt consumers
  observe trace then tracker; router transport handles one transient fallback.
- `GameLLMTerminalError` is re-raised before the existing generic nonterminal
  narration fallback. Thus quota/refusal/content-filter stop after one SDK
  attempt, with no owner fallback narration or post-boundary assistant
  append/save. The generic nonterminal fallback remains unchanged.
- Deterministic location commit, traveling-follower synchronization,
  transition-marker append, and marker history-save remain before the narration
  boundary and in their existing order. No rollback/replay or other action
  handler owner was changed.
- The scoped transition suite now executes the actual finite owner statements
  from `transition_prompt = location_manager.handle_location_transition(...)`
  through the complete `if transition_prompt` body and success tail, in a small
  wrapper rather than running all of `process_action`. It uses an in-memory
  canonical location commit, in-memory follower sync/history, fake import/IO/
  campaign dependencies, and real router plus real receipt adapter over fake
  SDK/consumers. A source assertion independently proves the actual location
  manager persists `party_tracker.json` before returning its prompt.
- Event assertions cover commit -> party reload -> follower sync -> marker
  append -> pre-narration history save -> SDK/receipt callback order, then either
  successful narration append/save -> campaign detection/write -> success tail,
  or terminal exit retaining the pre-boundary state without assistant
  append/save, campaign/write/success publication, or needs-update tail. The
  nonterminal owner fallback path and transient router fallback are also covered.
  Unexpected fake-dependency failures use a `BaseException` sentinel so broad
  production `Exception` catches cannot turn them into passing fallback cases.
  The test-only wrapper catches the typed terminal solely to inspect its locals;
  the production branch still re-raises the terminal result.
  Prompt goldens remain unchanged.
- Inventory records 14 of 15 semantic operations migrated; NPC movement is the
  sole remaining legacy operation.

## Primary Scoped Review

- Reviewed the finite actual source path from the pre-narration deterministic
  location commit, follower synchronization, transition-marker append, and
  history save, through the real router using a fake SDK and the real receipt
  adapter, to the downstream campaign/success tail. This review covers the
  stated bounded owner statements, not a full `process_action` execution.
- Confirmed the source keeps the existing prompts unchanged and uses
  `temperature=0.7`. Quota/refusal/content-filter outcomes make one SDK attempt,
  do not enter owner fallback, and retain pre-boundary effects while preventing
  later narration append/save, campaign/success effects, or other later action
  effects. The focused test wrapper and real-router/fake-SDK coverage are
  described above.
- Primary scoped software result: PASS. The change now has 17/25 tasks checked
  and 14/15 semantic operations migrated. No claim is made that G4 or the full
  goal is complete.

## Verification

The 11 transition/core suites below ran in separate processes with
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 TMPDIR=tmp` and
the repository venv. These suites arm SDK, network, and outside-write guards
before importing owners. The only scratch artifact was the compile cache under
`tmp/llm-router-task-4-2-pycache`. No ignored cleanup was reported.

| Suite | Result |
|---|---:|
| `scripts.test_transition_router_migration` | 5 passed |
| `scripts.test_starting_location_router_migration` | 7 passed |
| `scripts.test_core_chat_inventory_contract` | 13 passed |
| `scripts.test_core_chat_request_contracts` | 17 passed |
| `scripts.test_llm_runtime_receipt_adapter` | 15 passed |
| `scripts.test_llm_runtime_launch_reset` | 3 passed |
| `scripts.test_llm_router` | 88 passed |
| `scripts.test_benchmark_model_profiles` | 6 passed |
| `scripts.test_gpt54_chat_params_contract` | 10 passed |
| `scripts.test_gpt54_mini_chat_params_shim` | 6 passed |
| `scripts.test_gpt56_luna_direct_openai_contract` | 41 passed |
| **Guarded transition/core total** | **211 passed across 11 processes** |

The original builder report stated **224 passed across 12 processes**. That
figure incorrectly included the following auxiliary legacy-suite run and is
retained here only as a historical claim, not as the verified safe total:

- The first requested import, `scripts.test_scene_follower_state_sync`, does
  not exist and produced a loader error; it yielded no passing tests.
- The request was corrected to the real
  `scripts.test_scene_follower_transition_sync`, which ran 13 tests and passed.
  This legacy suite does **not** arm the fatal guards before its imports. During
  the run it logged `[UpdateCharacterInfo] Creating OpenAI client for chat`.
  Therefore this auxiliary run is not guarded/provider-free verified and is
  excluded from the 211-test total. Configured credential reads/client
  construction and logger writes outside project `tmp/` cannot be ruled out
  from the available evidence. No HTTP was observed; this is an observation,
  not a claim that network activity was impossible. No secrets or runtime
  artifacts were inspected and no cleanup was performed to investigate.

Additional checks:

- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` - PASS.
- `PYTHONPYCACHEPREFIX=tmp/llm-router-task-4-2-pycache .venv/bin/python -m py_compile ...` on the changed Python files - PASS.
- `python3 scripts/check_ascii_compliance.py --summary-only` - 1,145 files scanned, zero violations.
- Scoped `git diff --check` - PASS.
- `scripts.test_authoritative_transition_inventory_runtime_reset` - 8 tests passed, 1 failed in the unrelated source-string assertion. The exact expected one-line string is absent from both `git show HEAD:main.py` and the worktree; the two underlying multiline nested-response `error_msg` assignment blocks are byte-identical between HEAD and worktree. This is a pre-existing formatting/source-contract mismatch, not a transition implementation failure. Record it for the Task 5.1 source-contract audit; do not count this suite as a PASS. No `main.py` or test change was made.
- A guarded rerun of the transition/core suites remains required under Task 5.1/finalgate and is not waived. The 211 passing tests above are the fresh reported guarded suite set; the separate legacy 13-test run does not satisfy that follow-up.
- Report-only ASCII/whitespace verification is required for this report correction; no source, product, history, campaign, or configuration cleanup was performed.

No facade/router/factory/adapter/config/prompt/manager changes, live capture,
installation, campaign preparation, task-4.3 work, changes to other task
checkboxes, or Git mutations were performed.
