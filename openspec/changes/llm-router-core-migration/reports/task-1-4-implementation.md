# Task 1.4 Implementation Report

## Result and API

Added keyword-only `empty_retry_limit: Optional[int] = None` to
`LLMRouter.call()`. `None` preserves the default-off behavior. Explicit values
must be exact integers from 0 through the existing
`EMPTY_RESPONSE_RETRY_LIMIT` value of 2; booleans, floats (including non-finite
values), negative values, oversize values, and non-integers are rejected before
provider resolution or client construction. An explicit policy is limited to
`dm_main` text calls and is rejected with `json_output=True`.

Opted-in responses use the existing `classify_chat_completion()` classifier
and `EmptyProviderResponseError`. The selected provider gets at most
`empty_retry_limit + 1` empty responses; after its exhaustion, one fallback
transition may start a fresh per-provider response budget. The shared fallback
flag and SDK invocation count are not reset. The absolute SDK ceiling is
`2 * (empty_retry_limit + 1)`, at most six invocations. Empty responses are
recorded and observed once before retry/transition/exhaustion. Transport errors
retain the existing transient fallback policy without consuming the empty
response counter; switching to fallback resets only that per-provider counter.
Constructor failures remain pre-attempt errors with no fabricated usage, and
the existing one-transition behavior remains intact.

When the preferred provider exhausts its empty-response budget, the router
constructs `EmptyProviderResponseError` and passes it once to the existing
`ai_client_factory.handle_provider_error()`. The router transitions only when
that handler returns `should_fallback`; denial raises the same exhaustion error
without constructing a fallback client. The existing factory-owned notification
state and `get_fallback_notification()` path are used, with no synthetic SDK
error receipt or second usage accounting event for exhaustion. Exhaustion on an
already-used fallback does not request another transition.

Refusal, content-filter, and quota outcomes stop immediately. Existing JSON
retry behavior and default-off empty/malformed JSON behavior remain unchanged.
No caller/raw-SDK recovery wrapper was added. No factory, quota classifier,
model configuration, caller, task status, or baseline/golden/incident artifact
was changed.

## Tests and guards

Added provider-free router tests for default-off behavior; three preferred
empties followed by fallback success; three empties per provider and six-call
exhaustion; exact once-only receipts and router usage; two preferred empties,
then transport error, then fallback exhaustion within six SDK calls; preferred
constructor failure and bounded fallback; immediate refusal/filter/quota stop;
policy validation before client construction; the real factory recovery handler
and once-consumed fallback notification; and denied recovery with exactly three
preferred SDK calls and no fallback construction. Existing process-wide SDK,
constructor, network, BaseException, and outside-write tripwires remain armed
before production imports. All transport tests use fakes; no provider, server,
key, or main caller was exercised. The existing factory error handler and
notification getter were exercised with patched in-memory status and fake
clients; no factory code was changed.

## Verification

Each unittest command ran in a separate process. Bytecode used the project-local
`tmp/pycache/` path.

- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python scripts/test_llm_router.py`
  - PASS: 88 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_benchmark_model_profiles`
  - PASS: 6 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_gpt54_chat_params_contract`
  - PASS: 10 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_gpt54_mini_chat_params_shim`
  - PASS: 6 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_gpt56_luna_direct_openai_contract`
  - PASS: 41 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_provider_empty_response_retry`
  - PASS: 37 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_core_chat_inventory_contract`
  - PASS: 9 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_core_chat_request_contracts`
  - PASS: 11 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m py_compile utils/llm_router.py scripts/test_llm_router.py`
  - PASS.
- `.venv/bin/python scripts/check_ascii_compliance.py --summary-only`
  - PASS.
- `git diff --check -- utils/llm_router.py scripts/test_llm_router.py openspec/changes/llm-router-core-migration/reports/task-1-4-implementation.md`
  - PASS.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict`
  - PASS.

Primary software review: PASS. Fresh verification passed 208 tests across eight
separate processes: router (88), benchmark (6), GPT-5.4 chat (10), GPT-5.4 mini
(6), GPT-5.6 Luna (41), empty-response retry (37), core chat inventory (9), and
core chat request contracts (11). Strict PASS; no ignored cleanup errors.
Scratch/cache path: `tmp/pycache/`; no other scratch files. This review covers
the bounded one-fallback terminal-stop behavior described above.
