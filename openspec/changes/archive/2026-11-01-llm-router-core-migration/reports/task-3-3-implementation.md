# Task 3.3 Implementation Report

## Scope and private seams

Migrated only `core/combat/validation.py::validate_combat_response` and the
validation dependency builder/wrapper seams in `core/combat/combat_manager.py`.
The existing public five-argument owner wrapper and return contract remain
unchanged. The dependency dataclass retains legacy client/model/parameter/
timeout/trace/tracker/logger fields and adds optional private `llm_call` and
receipt-observer-factory injections. The owner binds both lazily to
`utils.llm_router.llm.call` and `utils.llm_runtime.make_legacy_receipt_observer`;
precheck returns still happen before facade call, observer creation, or client
construction.

Each of the existing five validation attempts now invokes the facade with task
`combat_validation`, `json_output=False`, explicit temperature `0.3`, the
unchanged `validation_conversation`, and a per-attempt observer. The caller
strips the facade's text result; it no longer reads SDK `choices`, supplies a
model/timeout, or owns provider transport. The factory retains configured
120/10-second timeouts and the router retains zero SDK retries. The receipt
adapter receives endpoint `combat_validation`, the exact messages, attempt and
temperature metadata, `USAGE_TRACKING_AVAILABLE`, and
`api_log_before_tracker=True`; consumers run trace -> API logger -> usage
tracker. Manual trace/log/tracker producer calls were removed. Receipt-owned
requested/resolved model and actual/estimated/unpriced cost facts remain sourced
from the receipt, not legacy configuration.

`GameLLMTerminalError` is re-raised before the broad provider/parse catch can
retry or fail open to `True`. Ordinary malformed/transport failures retain all
five nonterminal attempts and exhaustion still returns `True`; valid results
still return `True`, invalid feedback remains the existing string, and parser
and prompt construction were not changed. No prompt, asset, truth-pack,
canonical-facts, precheck, phase-routing, or replay behavior was modified.

## Actual-facade tests

The validation-stage tests compose the actual `LLMRouter.llm.call`,
`make_legacy_receipt_observer`, the actual validation function, and fake SDK
clients. They cover text stripping and valid `True`, invalid-feedback string,
five malformed-response exhaustion and transport-error exhaustion, and quota,
refusal, and content-filter one-call terminals. Receipt checks verify callback
order, endpoint/messages, attempt/temperature metadata, and actual requested/
resolved model metadata. A bad validation JSON response followed by terminal
quota consumes exactly two SDK invocations and does not return stale validation
success.

The retry-stage tests additionally execute the actual facade -> actual
`validate_combat_response` -> actual `run_combat_provider_retry_stage` path.
Initial combat text followed by validation quota causes terminal propagation
after exactly two SDK attempts; a finite admission block's action/persistence
spies remain untouched, and encounter/history inputs remain deeply unchanged.
Precheck rejection tests continue to show zero provider calls; the new observer
factory is not constructed on the phase-rejection path.

## Verification

Focused verification passed in separate processes with
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`:

| Suite | Tests |
| --- | ---: |
| `scripts.test_combat_validation_stage` | 17 |
| `scripts.test_combat_validation_routing` | 11 |
| `scripts.test_combat_retry_stage` | 15 |
| `scripts.test_combat_bootstrap` | 29 |
| `scripts.test_combat_manager_decomposition_contract` | 35 |
| `scripts.test_combat_decomposition_contract` | 9 |
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
| `scripts.test_combat_truth_pack` | 8 |
| `scripts.test_combat_canonical_validation_facts` | 3 |
| **Total** | **333 in 18 processes** |

Also passed:

- `PYTHONPYCACHEPREFIX=tmp/llm-router-core-3-3-pycache .venv/bin/python -m py_compile`
  for the modified combat source and focused tests.
- `python3 scripts/check_ascii_compliance.py --summary-only`: 1,141 files,
  zero violations.
- `git diff --check`.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate
  llm-router-core-migration --strict`.
- AST audit: 12 `core/combat/` files, 154 functions, maximum 480 lines,
  zero functions above 600 lines.
- Prompt/message assembly AST and static asset SHA-256 goldens passed unchanged
  in `scripts.test_core_chat_request_contracts`; G3 static/decomposition
  contracts passed unchanged.

One intermediate run surfaced a stale GPT-5.4 source assertion that expected
caller-owned combat timeout kwargs. It was updated to assert no timeout kwargs
remain at combat caller seams and to assert the migrated validation task/options;
the suite then passed. A test-only mixed event list in the late-terminal probe
was separated into SDK and receipt events; the corrected probe passed.

Primary verification reviewed the facade STR, fixed temperature `0.3`, five-
attempt nonterminal policy, typed terminal escape, no-true-on-terminal behavior,
receipt context, prompt parity, and actual finite stage-to-retry integration.
The fresh primary run passed 333 tests in 18 separate processes (the earlier
builder tally of 332 was corrected; suite counts are listed above). Task 3.3 is
checked. Core migration stands at 13/25 tasks and nine of 15 semantic operations
migrated, with six legacy. All G4 work remains pending. No full combat
simulation, main loop, server, network, live provider, or campaign gate was run.
Scratch/cache used:
`tmp/llm-router-core-3-3-pycache/`.
