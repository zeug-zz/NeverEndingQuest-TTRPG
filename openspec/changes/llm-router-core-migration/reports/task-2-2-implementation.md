# Task 2.2 Implementation Report

## Scope

`main.py::validate_ai_response` now sends each of its existing maximum three
provider attempts through `llm.call(task="dm_validation", json_output=False)`.
It preserves temperature 0.1, the pre-call validation-message assembly, the
nonterminal invalid-JSON retry loop, validation result parsing, and tuple
returns. The facade owns model selection, timeout, and SDK retry policy.

Each call uses the receipt adapter with the existing `validation` API endpoint,
`validate_dm_response` tracker purpose, per-attempt/max-retries labels, the
existing usage-tracking gate, and API-log-before-tracker callback order. The
quality-control `model_used` field comes from that call's resolved receipt model
or the honest value `unknown`; it no longer reports the legacy configured model
as if that were necessarily the selected provider model. Terminal router errors
are explicitly re-raised before another attempt or the existing invalid-JSON
fail-open result.

The inventory records this as the third migrated operation. The other 12
operations retain their inventoried raw/helper transport variants. No prompt
assets, global response state, action acceptance rules, main-loop handlers, or
factory/router implementation were changed for this task.

## Focused Verification

- `scripts.test_core_chat_request_contracts`: 13 tests passed, including the
  source-derived message assembly digest, fake router request, one-attempt
  terminal escape with no mutation, and unchanged three malformed-JSON
  nonterminal attempts.
- `scripts.test_core_chat_inventory_contract`: 12 tests passed, including the
  exact 15-operation inventory and validation route/task/options assertions.
- `scripts.test_llm_runtime_receipt_adapter`: 15 tests passed.
- `scripts.test_llm_runtime_launch_reset`: 3 tests passed.
- `scripts.test_llm_router.py`: 88 tests passed.
- `scripts.test_benchmark_model_profiles`: 6 tests passed.
- `scripts.test_gpt54_chat_params_contract`: 10 tests passed.
- `scripts.test_gpt54_mini_chat_params_shim`: 6 tests passed.
- `scripts.test_gpt56_luna_direct_openai_contract`: 41 tests passed.
- `scripts.test_provider_empty_response_retry`: 37 tests passed.
- Python compilation passed with `PYTHONPYCACHEPREFIX=tmp/task-2-2-pycache`.
- ASCII compliance: 1141 files scanned, zero violations; `git diff --check`
  passed; strict OpenSpec validation passed.

All test suites ran in separate processes with `OPENSPEC_TELEMETRY=0`
`DO_NOT_TRACK=1`. No live provider or server was used. The primary-reviewed
software verification is PASS. Three of the 15 semantic operations are
migrated; the other 12 remain legacy. This is not a G4/live verification or
full-goal completion claim. Incident details, path uncertainty, and historical
goldens/baselines remain preserved and were not rewritten.
