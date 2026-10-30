# Task 4.3 - NPC Movement Router Migration

Status: scoped implementation and guarded software verification completed;
task checkbox remains unchecked for primary verification. This is not a live
G4 or full-goal completion claim.

## Implementation

- `get_ai_npc_movement_decision` now makes one `llm.call(task="updates",
  json_output=False, temperature=0.7, observer=...)` text request. The former
  caller-owned preferred/fallback clients, model selection, SDK parameter
  helper, and provider-error fallback branch are removed. Model, timeout, and
  transport fallback remain router/factory-owned.
- System/user prompt construction was left byte-for-byte intact, including the
  `Attempt: {attempt}/5` variation. The original `messages` expression remains
  inline at the facade boundary; no prompt/message baseline digest was changed.
  The facade's text result is stripped, then the original greedy regex JSON
  extraction, `json.loads`, decision object return, and `None` on malformed or
  ordinary failure remain intact.
- The existing receipt adapter is attached once, gated by
  `USAGE_TRACKING_AVAILABLE`, and opts in to trace site
  `npc_movement_decision`. It preserves the existing tracker behavior and
  introduces no API logger or manual duplicate tracking.
- `GameLLMTerminalError` is re-raised before the movement function's generic
  catch and before `move_background_npc`'s outer broad catch. The caller's
  existing validation-attempt loop therefore stops immediately; the decision
  validation/application/save path is not reached for a terminal outcome.
- The guarded vertical suite executes the complete actual function through the
  real router and real receipt adapter with fake SDK/tracker/trace consumers.
  It covers valid and malformed JSON, prompt attempt variation, ordinary
  router fallback, quota/refusal/content-filter one-attempt behavior, usage
  gating, and a finite actual caller-loop seam proving one attempt and zero
  validation/application. Dependency tripwire failures use a `BaseException`
  sentinel rather than being absorbed by production broad catches.
- Inventory now records 15/15 migrated semantic operations and zero legacy
  transport variants. Existing prompt baseline digests were not rewritten.

## Verification

Every test command ran in a separate process with
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 TMPDIR=tmp`.
Provider/network and outside-write guards were armed before owner imports in
the new NPC suite and the established focused contract suites. The five
facade suites and focused transition, starting-location, inventory/request,
adapter, and launch suites passed: **217 test executions across 12 processes**.

| Suite | Result |
|---|---:|
| `scripts.test_npc_movement_router_migration` | 6 passed |
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
| **Total** | **217 passed across 12 processes** |

The first `test_gpt54_mini_chat_params_shim` run exposed an obsolete source
assertion requiring the action handler to retain `get_chat_completion_params`.
That narrowly-scoped assertion now verifies the action handler has no such
legacy helper and contains the `updates` facade task; the separate rerun passed.

Additional checks:

- Scoped `py_compile` passed for the changed Python source/tests with
  `PYTHONPYCACHEPREFIX=tmp/llm-router-task-4-3-pycache`.
- `python3 scripts/check_ascii_compliance.py --summary-only` passed.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` passed.
- `git diff --check` passed; a separate explicit trailing-whitespace scan
  covered changed untracked files too.
- No auxiliary legacy follower suite, full `process_action`, main/game loop,
  `sys.settrace`, server, live API, or campaign preparation was run.

Scratch used: `tmp/llm-router-task-4-3-pycache`; `TMPDIR=tmp`. No task checkbox,
baseline hash, Git history, credentials, or runtime campaign data was changed.
