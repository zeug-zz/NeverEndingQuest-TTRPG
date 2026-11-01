# Task 2.4 Implementation Report

`main.py::generate_module_summary()` now makes one `llm.call(task="summaries", json_output=False)` request with the existing summary message array and explicit `temperature=0.7`. Model/profile, SDK construction, timeout, and provider fallback are router/factory-owned; the summary producer no longer constructs a client or contains a provider-fallback branch. The existing boundary selection, meaningful-message filtering, literal chronicle prompt, stripped text formatting, return values, and basic-summary fallback remain intact. Terminal quota/refusal/content-filter errors are re-raised before both the AI-summary fallback and the outer processing fallback.

The producer supplies `make_legacy_receipt_observer(...)` with endpoint `module_summary`, the exact messages, legacy endpoint/purpose/module/temperature context, `track_usage=USAGE_TRACKING_AVAILABLE`, and `api_log_before_tracker=True`. The callback proof uses the real adapter with fake logger/tracker sinks: one SDK response produced exactly one API log followed by one tracker event; disabling usage tracking retained the API log without a tracker event. No per-call SDK/client/timeout or caller provider fallback remains.

The prompt asset goldens remain unchanged. The request-contract golden was updated only for the migrated fifth operation's source-level request shape; the test also executes the entire actual summary function and asserts its exact emitted messages against the pre-migration prompt text.

## Focused verification

- `scripts.test_core_chat_request_contracts`: 17 tests passed. Includes exact prompt/message bytes, filtered meaningful-history boundary, plain-text summary/format parity, real adapter callback order and usage gate, terminal quota/refusal/filter propagation with one facade call and no returned basic/valid summary, nonterminal basic fallback, and short-history no-call behavior.
- `scripts.test_core_chat_inventory_contract`: 13 tests passed; inventory proves five migrated semantic operations and ten still-legacy operations, with one `llm.call` and no summary raw-SDK/client/fallback transport.
- `scripts.test_llm_runtime_receipt_adapter`: 15 passed.
- `scripts.test_llm_runtime_launch_reset`: 3 passed.
- Facade suites in separate processes: `scripts.test_llm_router.py` 88 passed; `scripts.test_benchmark_model_profiles` 6 passed; `scripts.test_gpt54_chat_params_contract` 10 passed; `scripts.test_gpt54_mini_chat_params_shim` 6 passed; `scripts.test_gpt56_luna_direct_openai_contract` 41 passed.
- `scripts.test_provider_empty_response_retry`: 37 passed in a separate process.
- Total: 236 tests passed across 10 separate processes.
- `PYTHONPYCACHEPREFIX=tmp/task-2-4-pycache .venv/bin/python -m py_compile main.py scripts/test_core_chat_request_contracts.py scripts/test_core_chat_inventory_contract.py`: passed.
- `python3 scripts/check_ascii_compliance.py --summary-only`: 1,141 files scanned, zero violations.
- Scoped `git diff --check` for `main.py`, both focused test modules, and the two owning reports: passed.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict`: valid.

Primary reviewed: summary str stripping, parsing, history, persistence, nonterminal fallback, terminal escape, and observer order. Primary software verification: PASS (236 tests across 10 separate processes: request 17, inventory 13, adapter 15, launch 3, router 88, bench 6, GPT-5.4-chat 10, mini 6, Luna 41, empty 37). Strict CORE, scoped diff, and no-ignored-cleanup checks: PASS. Core migration: 10/25 tasks checked; five of 15 semantic operations migrated, ten remain legacy. No live provider, server, full main loop, capture campaign, G4, or full-goal completion claim.
