# Task 3.5 Implementation Report

## Scope and behavior

Migrated only `core/combat/initiative_tracker_ai.py::generate_live_initiative_tracker`
to `llm.call(task="combat_main", json_output=False)` with an explicit
`temperature=0.1`. The shared factory now owns provider credentials and model
selection; the caller no longer imports or gates on `OPENAI_API_KEY`, constructs
an SDK client, or supplies `DM_MAIN_MODEL`, a timeout, or a fallback client.
This intentionally transfers credential-gate ownership to the provider-neutral
factory. No secret value was read or added.

`extract_recent_combat_messages`, `create_initiative_prompt`, all prompt assembly,
the current compressed prompt asset, debug prompt export, and response append
remain unchanged. The tracker still appends the actual facade response text,
returns the complete text stripped only when `**Live Initiative Tracker:**` is
present, and returns `None` for absent markers or ordinary failures. The real
receipt adapter now accounts for the previously untracked core SDK response
once and emits the existing opt-in trace at `initiative_tracker`; endpoint,
function, and purpose context are truthful. No API logger was added. Error
receipts do not fabricate usage. Terminal quota/refusal/content-filter errors
re-raise before the function's generic `None` fallback. The existing combat
prompt owner had a broad catch around this provider-bearing fallback, so its
minimal typed terminal guard now rethrows before ordinary diagnostic handling;
the lazy wrapper and public API remain unchanged.

## Verification

Primary review confirmed facade behavior and tracker marker handling, no SDK
constructor/key gate in the semantic operation, factory ownership of the
credential gate, typed terminal-error propagation through the caller, once-only
usage and opt-in trace behavior, no API logging, and unchanged prompt goldens.

`scripts/test_initiative_tracker_router_migration.py` compiles and invokes the
complete current tracker function with the real extraction/prompt helpers, the
real facade and receipt adapter, and a fake SDK client. Fake I/O keeps debug
captures in memory. The tests cover valid marker/full instruction text and
whitespace stripping, absent marker, empty and malformed content, transport
failure, terminal quota/refusal/filter outcomes, no-creature/no-history early
returns, ordinary factory credential-construction failure with zero SDK calls,
once-only usage and opt-in trace, absence of API logging, and source absence of
the direct constructor and OpenAI-key gate. A current-source caller check proves
the initiative fallback terminal guard precedes its generic catch behavior.

Executed in separate processes with `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`,
`PYTHONDONTWRITEBYTECODE=1`, and `TMPDIR=tmp`:

- `scripts.test_initiative_tracker_router_migration`: 7 passed.
- `scripts.test_core_chat_inventory_contract`: 13 passed.
- `scripts.test_core_chat_request_contracts`: 17 passed, including unchanged
  literal initiative assembly and current prompt-asset SHA-256 baselines.
- `scripts.test_llm_runtime_receipt_adapter`: 15 passed.
- `scripts.test_llm_runtime_launch_reset`: 3 passed.
- `scripts.test_llm_router`: 88 passed.
- `scripts.test_benchmark_model_profiles`: 6 passed.
- `scripts.test_gpt54_chat_params_contract`: 10 passed.
- `scripts.test_gpt54_mini_chat_params_shim`: 6 passed.
- `scripts.test_gpt56_luna_direct_openai_contract`: 41 passed.
- `scripts.test_combat_bootstrap`: 29 passed.
- `scripts.test_combat_retry_stage`: 15 passed.
- `scripts.test_combat_validation_stage`: 17 passed.
- `scripts.test_combat_validation_routing`: 11 passed.
- `scripts.test_combat_summary_router_migration`: 6 passed.
- `scripts.test_combat_decomposition_contract`: 9 passed.
- `scripts.test_combat_manager_decomposition_contract`: 35 passed.
- `scripts.test_combat_runtime_prompt_authority`: 7 passed.

Total: 335 tests passed across 18 separate processes.

Primary software verification: PASS. Strict OpenSpec validation, scoped
whitespace check, and no-ignored-cleanup check: PASS. Core migration status is
15/25 tasks checked; 12 of 15 semantic operations are migrated and three remain
legacy, including the three Action Handler operations. All G4 work remains
pending; no live or full-goal completion claim is made.

These runs verify factory temperature policy through the actual facade: the
caller explicitly passes `0.1`, while the factory may omit sampling for a
model family that does not support it. No actual provider/client/network call
was made. The tracker used one fake SDK invocation for ordinary, refusal, and
filter responses, one for quota and transport failures, and zero for factory
credential-construction failure or no-creature/no-history short-circuits.
Successful/malformed returned responses were tracked once; transport/quota and
construction failures fabricated no usage. Safety tripwires were armed before
the test imported the owner and remained untouched. The AST size audit found no
`core/combat/` function above 600 lines; the scoped compatibility-shim contracts
also passed in the combat decomposition suites.

No full owner loop, combat simulation, server, network, live provider, G4 gate,
or full historical baseline was run.
