# Task 3.1 Implementation Report

## Scope and private seams

Migrated only startup resume and initial-scene provider requests in
`core/combat/bootstrap.py`. `_startup_provider_call(...)` now returns assistant
text from the privately injected `dependencies.llm_call(task, messages,
json_output=False, observer=..., **options)` callable. The owner binds that
callable lazily to `utils.llm_router.llm.call` in
`_build_startup_narrative_dependencies`; a second private lazy binding creates
the existing `utils.llm_runtime.make_legacy_receipt_observer` adapter. Public
`run_startup_narrative` inputs/results and owner lifecycle signature are
unchanged. Legacy dependency fields remain present for compatibility; startup
does not use the client, parameter builder, or timeout for transport.

Resume keeps its GPT-5 branch temperature-free and passes the existing
`get_temperature(..., validation_attempt=0)` override only for the legacy
non-GPT-5 branch. Initial scene passes its existing per-attempt temperature.
Neither branch supplies an SDK model or timeout. The request task is
`combat_main`; caller-side parsing remains text-based and strips returned
text, not SDK `choices`.

Receipt ownership is unchanged but now adapter-backed: resume calls the
observer with endpoint `combat`, messages, trace site `combat_reengage`,
existing branch/context metadata, and `api_log_before_tracker=True`, so each
SDK response is consumed trace -> API logger -> usage tracker before
JSON/history/output processing. Initial scene opts into trace site
`combat_main` and usage only (no API logger), so order is trace -> usage before
JSON/validation. Manual provider-trace, logger, and usage calls were removed
from these two migrated paths; receipt metadata retains any old model variable
only as `legacy_context_model`, not as a claimed resolved model.

`GameLLMTerminalError` is resolved lazily only on broad-catch error paths to
avoid importing the SDK-backed router before the guarded test boundary. It is
re-raised before resume fallback narration and before initial loop retry,
last-response cleanup, assistant append/save, parse, or narration output.
Nonterminal single-shot resume fallback and the initial three-attempt
validation/exhaustion behavior remain intact. The `awaitingPcGroupRoll` fast
lane still exits before compressor, router, validation, save, export, or
observer-factory calls.

## Focused verification

The bootstrap suite retains the explicit injected-call seam tests and now also
composes the actual `router_module.llm.call`, the actual
`make_legacy_receipt_observer`, fake tracker/logger/trace consumers, and a fake
SDK client at `factory.create_chat_client`. The fake SDK implements only the
SDK methods used by the router (`with_options` and `chat.completions.create`);
it is not a facade-shaped mock. Tests exercise both resume model branches,
initial scene, three actual nonterminal initial attempts, quota/refusal/filter
terminals, and a nonterminal response followed by terminal refusal. They
assert text returned from the real facade, exact task/JSON setting, no caller
timeout at facade or SDK boundary, one receipt per SDK response, trace -> API
logger -> usage resume order, trace -> usage initial order without unsolicited
API logging, terminal zero assistant/fallback output, and no stale response
save/validation/output after the late terminal. The four-PC
`awaitingPcGroupRoll` test asserts no router/compressor/validation/save/export/
observer-factory call. Process-wide guards are armed before owner imports;
factory patches remain on the test thread. Existing 1.1 request-contract AST
coverage was repointed to the fake-facade seam; its prompt-assembly and asset
SHA-256 goldens were not changed.

Passed in separate processes:

- `scripts.test_combat_bootstrap`: 29 tests.
- `scripts.test_combat_validation_stage`: 15 tests.
- `scripts.test_combat_validation_routing`: 11 tests.
- `scripts.test_combat_decomposition_contract`: 9 tests.
- `scripts.test_combat_manager_decomposition_contract`: 35 tests.
- `scripts.test_combat_runtime_prompt_authority`: 7 tests.
- `scripts.test_core_chat_inventory_contract`: 13 tests.
- `scripts.test_core_chat_request_contracts`: 17 tests.
- `scripts.test_llm_runtime_receipt_adapter`: 15 tests.
- `scripts.test_llm_runtime_launch_reset`: 3 tests.
- `scripts.test_llm_router`: 88 tests.
- `scripts.test_benchmark_model_profiles`: 6 tests.
- `scripts.test_gpt54_chat_params_contract`: 10 tests.
- `scripts.test_gpt54_mini_chat_params_shim`: 6 tests.
- `scripts.test_gpt56_luna_direct_openai_contract`: 41 tests.
- `PYTHONPYCACHEPREFIX=tmp/llm-router-core-3-1-pycache .venv/bin/python -m py_compile`
  on the modified Python source and focused tests: passed.
- `python3 scripts/check_ascii_compliance.py --summary-only`: 1,141 files,
  zero violations.
- `git diff --check`: passed.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate
  llm-router-core-migration --strict`: valid.

Primary software verification: PASS (305 tests in 15 separate processes).
Primary review confirms strict OpenSpec validation and scoped `git diff --check`
PASS. No full combat/game loop, network, server, or live provider call was run;
G4 tooling and live/full-goal verification remain pending. No other migration
task was attempted. Scratch/cache path: `tmp/llm-router-core-3-1-pycache/`.
