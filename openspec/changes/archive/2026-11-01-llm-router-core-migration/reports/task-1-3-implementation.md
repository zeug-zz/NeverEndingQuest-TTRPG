# Task 1.3 Implementation Report

## Result and API

Added `GameLLMTerminalError(GameLLMError)` in `utils/llm_router.py`. Its
`terminal_kind` discriminator is validated and restricted to `quota`,
`refusal`, or `content_filter`; the safe exception message contains only that
kind. It remains catch-compatible with existing `GameLLMError` handlers.

Quota decisions continue to call the existing `LLMRouter._quota_error`
predicate unchanged. The router now raises the typed terminal subclass for
quota identified in primary client construction, SDK transport, fallback
client construction, and fallback-after-transport client construction.
Refusal and content-filter responses are classified using the existing
`utils.provider_response_recovery.classify_chat_completion(response)` with
its `refusal` and `content_filter` classifications. The response is accounted
and observed once, then a typed terminal error is raised before normal content
parsing or JSON retry. Empty/no-choice responses retain existing behavior;
ordinary malformed nonempty JSON retains the existing three-attempt bound.

Receipt metadata contains only its existing safe fields and the response's
usage/cost/model facts; terminal messages do not copy prompts, credentials,
provider response bodies, or exception messages. Constructor errors remain
pre-attempt events with no fabricated response usage. No factory, classifier,
caller, configuration, or runtime handling changes were made.

## Tests and guards

Expanded the guarded fake-transport router suite to cover quota, refusal, and
content-filter outcomes in text and JSON modes; exactly one SDK call/response
receipt; no JSON retry or provider fallback; actual usage and zero-cost
preservation with unknown model retained; quota constructor, SDK, and nested
fallback-constructor paths; transient fallback; ordinary malformed JSON
retry bounds; and a typed terminal exception raised by an observer remaining
an isolated callback exception.

The existing process-wide fatal constructor/SDK/network/BaseException/outside-
write tripwires remain armed before production imports. New shared-factory
patches are held on the test thread, not installed from workers. All test
transports are fakes; no live provider investigation or server was used.

## Verification

All commands used project-local `PYTHONPYCACHEPREFIX=tmp/pycache` where Python
bytecode was generated. Each unittest command below ran as a separate process.

- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python scripts/test_llm_router.py`
  - PASS: 82 tests, including terminal, transient, fallback, guard, and JSON
    retry cases.
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
  - PASS: 1,138 files scanned, zero violations.
- `git diff --check -- utils/llm_router.py scripts/test_llm_router.py`
  - PASS.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict`
  - PASS: change valid.

Scratch/cache path: `tmp/pycache/`. No other scratch artifacts were created.

## Primary Review

Primary reviewed the fresh software verification and recorded **PASS** for
Task 1.3. The eight isolated processes passed with 202 tests total: router 82,
benchmark profiles 6, GPT-5.4 chat contract 10, GPT-5.4 mini shim 6,
GPT-5.6 Luna contract 41, empty-response retry 37, core chat inventory 9, and
core chat request contracts 11. Strict OpenSpec validation and scoped
whitespace validation also passed; there were no ignored cleanup errors.

This is a software-only PASS. It makes no live-server or G4 claim and does not
change any other task status.
