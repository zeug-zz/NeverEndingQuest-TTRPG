# Task 3.2 Implementation Report

## Scope and private seams

`run_combat_provider_retry_stage` now routes each of its three former SDK
parameter-family branches through the injected `dependencies.llm_call` seam
with task `combat_main` and `json_output=False`. The owner lazily binds that
seam to `utils.llm_router.llm.call` and binds
`utils.llm_runtime.make_legacy_receipt_observer` through a separate private
factory, following the Task 3.1 owner pattern. Public retry inputs, result
fields, function signature, exports, and legacy dependency constructor fields
remain intact; the legacy client/parameter/timeout fields are retained but are
not used for provider transport in this stage.

Prompt preparation, compression, export, tracing of prompt preparation, and
control flow remain in their original locations and ordering. The existing
`max_retries`, feedback insertion, validation history, multiple-update and
integrity checks, and exhaustion behavior are unchanged. The GPT-5 initial
branch makes a temperature-free facade call. Only the existing
`attempt >= 1 and gpt5_high_reasoning_on_retry` branch passes
`retry_tier="high"`. The legacy non-GPT-5 branch still computes
`get_temperature(encounter_data, validation_attempt=attempt)` and passes that
value explicitly as facade `temperature`; no call-site timeout or model is
passed.

Each call creates one observer from the injected factory. The stage's old
manual provider trace and usage callback were removed so the receipt callback
owns both once per actual SDK response/error. `trace_site="combat_main"` and
`track_usage=usage_tracking_available` are supplied; endpoint/messages are
omitted because this producer had no legacy API logger. Adapter consumer order
is trace then usage tracker. `GameLLMTerminalError` is checked before the
stage's existing generic error/retry handler and re-raised, preventing
semantic retry, validation, parsed-result acceptance, or stage result handoff.

`reports/core-chat-inventory.md` records the migrated operation and the current
eight-of-fifteen inventory state. Primary source review covered STR/legacy
conditions, receipt callbacks, typed terminal raises, stale-caller avoidance,
and the real-facade/fake-SDK stage integration.

## Focused verification completed

All commands were run in separate processes unless noted:

- `scripts.test_combat_retry_stage`: 14 tests, PASS.
- `scripts.test_combat_retry_hygiene`: 3 tests, PASS.
- `scripts.test_combat_bootstrap`: 29 tests, PASS.
- `scripts.test_combat_validation_stage`: 15 tests, PASS.
- `scripts.test_combat_validation_routing`: 11 tests, PASS.
- `scripts.test_combat_manager_decomposition_contract`: 35 tests, PASS.
- `scripts.test_combat_runtime_prompt_authority`: 7 tests, PASS.
- `scripts.test_combat_decomposition_contract`: 9 tests, PASS.
- `scripts.test_core_chat_inventory_contract`: 13 tests, PASS.
- `scripts.test_core_chat_request_contracts`: 17 tests, PASS; all prompt
  assembly and prompt-asset digest goldens remained unchanged.
- `scripts.test_llm_runtime_receipt_adapter`: 15 tests, PASS.
- `scripts.test_llm_runtime_launch_reset`: 3 tests, PASS.
- `scripts.test_llm_router.py`: 88 tests, PASS.
- `scripts.test_benchmark_model_profiles`: 6 tests, PASS.
- `scripts.test_gpt54_chat_params_contract`: 10 tests, PASS.
- `scripts.test_gpt54_mini_chat_params_shim`: 6 tests, PASS.
- `scripts.test_gpt56_luna_direct_openai_contract`: 41 tests, PASS.
- `PYTHONPYCACHEPREFIX=tmp/llm-router-core-3-2-pycache .venv/bin/python -m py_compile`
  on modified Python files: PASS.
- `python3 scripts/check_ascii_compliance.py --summary-only`: 1,141 files,
  zero violations, PASS.
- `git diff --check`: PASS.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate
  llm-router-core-migration --strict`: valid, PASS.

## Primary software verification

Fresh primary verification passed 322 tests in 17 separate processes:

| Suite | Tests |
| --- | ---: |
| `scripts.test_combat_retry_stage` | 14 |
| `scripts.test_combat_retry_hygiene` | 3 |
| `scripts.test_combat_bootstrap` | 29 |
| `scripts.test_combat_validation_stage` | 15 |
| `scripts.test_combat_validation_routing` | 11 |
| `scripts.test_combat_manager_decomposition_contract` | 35 |
| `scripts.test_combat_decomposition_contract` (static) | 9 |
| `scripts.test_combat_runtime_prompt_authority` | 7 |
| `scripts.test_core_chat_inventory_contract` | 13 |
| `scripts.test_core_chat_request_contracts` | 17 |
| `scripts.test_llm_runtime_receipt_adapter` | 15 |
| `scripts.test_llm_runtime_launch_reset` | 3 |
| `scripts.test_llm_router.py` | 88 |
| `scripts.test_benchmark_model_profiles` | 6 |
| `scripts.test_gpt54_chat_params_contract` | 10 |
| `scripts.test_gpt54_mini_chat_params_shim` | 6 |
| `scripts.test_gpt56_luna_direct_openai_contract` | 41 |
| **Total** | **322** |

Strict OpenSpec validation, scoped diff review, and no-ignored-cleanup checks
also PASS. Core migration stands at 12/25 tasks checked: eight of 15 semantic
operations migrated and seven remain legacy. All G4 work remains pending. No
live verification or full-goal completion is claimed.

## Actual facade and caller verticals

The retry-stage suite now composes the actual `LLMRouter.llm.call` and actual
`make_legacy_receipt_observer` with a fake SDK factory and the actual
`run_combat_provider_retry_stage`. The fake client's `with_options` observes
`max_retries=0`; factory construction is called once without caller options,
and no facade or SDK request receives a `timeout` kwarg. The existing router
factory-timeout tests in `scripts.test_llm_router.py` independently verify the
factory's 120-second total and 10-second connect timeout contract.

The actual facade verticals assert: text returned from the facade is trimmed
and parsed unchanged; valid output uses one provider call; invalid JSON followed
by valid text uses two calls with the legacy feedback at the end of the second
message; high reasoning is absent on GPT-5's initial call and is passed only on
the qualifying retry; disabling the existing high-retry flag prevents that
retry tier; GPT-5 calls omit temperature; and the legacy branch forwards the
computed temperature. A three-retry input with nonterminal SDK errors makes
exactly three facade/SDK attempts and returns the existing invalid/exhausted
handoff without fallback. Actual adapter callbacks run trace then tracker
exactly once per response. Quota errors, refusal responses, and filtered responses each
stop after one SDK invocation, do not construct a fallback client, and produce
`GameLLMTerminalError`. Quota produces an error trace receipt without usage;
refusal/filter each produce one trace and one tracker receipt.

For terminal outcomes at the actual combat coordinator, the test AST-selects
the direct retry-stage assignment from the current owner function containing
it (`run_combat_simulation_session`), the following `retry_result` consumption
assignments, the actual history-admission `if`, and source statements for
history persistence, narration publication, and action-batch execution. Those
side-effect boundaries are forbidden spies. Quota/refusal/filter escape before
any spy is reached, and source encounter/party inputs remain deeply equal. A
late provider quota following one parsed but semantically rejected candidate
uses exactly two SDK invocations (response then terminal error), produces
trace/tracker/trace receipt order, and does not return a stale retry result. A
terminal from the validation callback after one parsed response also propagates
without returning a stage result; it emits exactly one response receipt.

Task 3.2 is checked after primary software verification. No full combat owner
loop, provider, network, server, or live call was run. Scratch/cache path used:
`tmp/llm-router-core-3-2-pycache/`.
