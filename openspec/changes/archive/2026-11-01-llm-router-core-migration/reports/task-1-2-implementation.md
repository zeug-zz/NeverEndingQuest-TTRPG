# Task 1.2 Implementation Report

## Scope and API

Implemented only the optional router receipt observer and route-only tier hint.
The `LLMRouter.call` signature is:

```python
def call(
    self,
    task: str,
    messages: Any,
    json_output: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    retry_tier: Optional[str] = None,
    *,
    observer: Optional[Callable[[RouterReceipt, Any], Any]] = None,
    model_tier: Optional[str] = None,
    **kwargs: Any,
) -> Any:
```

Observer contract: `observer(receipt, raw_sdk_response_or_none)`. `receipt` is
frozen `RouterReceipt` metadata (including recursively immutable local stats
snapshot). The raw response is available only for a successful SDK response;
error callbacks receive `None`, never exception text or exception objects.
`kind` is `response`, `transport_error`, or `constructor_error`; error events
include only the exception class name in `error_type`. Each successful SDK
response and raised SDK transport invocation gets one unique per-call attempt
ID and monotonically numbered attempt. Constructor errors have no attempt
ID/number and contribute no SDK usage/attempt count. This includes fallback
client construction and failures in `_disable_sdk_retries` before SDK start.
JSON parse failures are accounted in router diagnostics as before but do not
emit a duplicate receipt; each returned SDK response gets one receipt.

Metadata distinguishes the selected transport provider from explicit upstream
provider metadata (unknown when absent; never inferred from a model name),
requested/resolved model, task/tier/profile, fallback state, `retry_tier`,
`transport_retry` (true for an SDK invocation after an earlier invocation in
this facade call, independent of reasoning policy), optional token/cache
observations, `usage_complete`, provider-reported cost including zero,
actual/estimated/unpriced cost provenance and completeness, safe `error_type`,
elapsed milliseconds when available, and a lock-consistent stats snapshot.
Missing or partial response usage remains `None` in receipt token fields and
cannot be used to estimate cost; an actual reported zero cost remains actual
even if usage is unavailable. Legacy router statistics retain their existing
zero-filled missing-token behavior. Accounting reuses existing calculations
and counter writes. Parsing/result materialization and accounting snapshot
occur before callback execution; callbacks execute outside the stats lock.
Ordinary callback exceptions are isolated; `BaseException` is not swallowed.
Mutating the raw SDK object cannot change the already-materialized return value
or stats. With no observer, UUID generation, receipt construction, and snapshot
work are skipped; the facade's ordinary accounting/results remain unchanged.

`model_tier` accepts only `None`, `"simple"`, or `"complex"`; validation runs
before provider resolution. A supplied tier changes profile tier selection,
does not reach SDK kwargs, and does not bypass an explicit `TASK_OVERRIDES`
model. Defaults remain task-derived. The factory is unchanged; zero SDK retries
remain enforced by `LLMRouter._disable_sdk_retries`.

The router test process arms `scripts.core_chat_test_safety` process-wide
constructor/network/write tripwires before production imports and asserts those
guards remained untouched at process teardown. Concurrent test patches are
installed outside worker threads and remain in place until all workers join;
workers synchronize on a barrier to force concurrent SDK-attempt overlap.

## Changed Files

- `utils/llm_router.py` - immutable receipt API, per-call identities, callback
  isolation, route-only tier hint.
- `scripts/test_llm_router.py` - fake-transport tests for identity/provider and
  model/cost provenance, JSON retry accounting, observer isolation, immutable
  snapshots/raw mutation, constructor errors, tier validation/precedence, and
  concurrent calls.
- `openspec/changes/llm-router-core-migration/reports/task-1-2-implementation.md`
  - this implementation evidence.

No factory, model configuration, facade golden, source-contract, caller,
adapter/session-reset, recovery, terminal-classifier, or runtime activation
changes were made.

## Primary Software Verification

Primary verification confirms the source/provenance/guard changes and records a
fresh software-only PASS: 162 tests across seven separate processes (router 79,
benchmark profiles 6, GPT-5.4 chat contract 10, GPT-5.4 mini shim 6, GPT-5.6
Luna direct OpenAI contract 41, source inventory 9, and request contracts 11).
No ignored cleanup exceptions were used. Strict/scoped diff verification
passed. This software result does not assert a G4 or other live PASS. Task 1.2
is checked for its software verification; planner review remains outstanding.

## Verification

All commands used `PYTHONPYCACHEPREFIX=tmp/pycache`; tests use fake clients and
transports only, with provider/network tripwires in the router suite.

- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python scripts/test_llm_router.py`
  - PASS: 79 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_benchmark_model_profiles`
  - PASS: 6 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_gpt54_chat_params_contract`
  - PASS: 10 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_gpt54_mini_chat_params_shim`
  - PASS: 6 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_gpt56_luna_direct_openai_contract`
  - PASS: 41 tests.
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_core_chat_inventory_contract`
  - PASS: 9 tests (task 1.1 inventory contract).
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m unittest -q scripts.test_core_chat_request_contracts`
  - PASS: 11 tests (task 1.1 request contract).
- `PYTHONPYCACHEPREFIX=tmp/pycache .venv/bin/python -m py_compile utils/llm_router.py scripts/test_llm_router.py`
  - PASS.
- `python3 scripts/check_ascii_compliance.py --summary-only`
  - PASS: 1,138 files scanned, 0 violations.
- `git diff --check -- utils/llm_router.py scripts/test_llm_router.py openspec/changes/llm-router-core-migration/reports/task-1-2-implementation.md`
  - PASS.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict`
  - PASS: change valid.

No additional live provider investigation was performed. **Incident record**:
the initial focused router run's console output (retained in the prior builder
run transcript; no separate logfile was produced) records failure in
`TestRouterUsageAccounting.test_snapshot_is_detached_reset_and_concurrent`.
Per-worker overlapping `mock.patch` scopes exposed the real factory client; the
trace reached the OpenAI SDK `Completions.create` and ended in
`openai.BadRequestError: Error code: 400` for an empty `messages` array. The
available stack does not establish whether an HTTP request reached a provider.
The factory path can read configured `OPENAI_API_KEY` and pass it to the SDK
constructor; credential value/use/exposure cannot be ruled out, and no value
was copied into this report. Subsequent test patches are process-wide around
the worker window, guards are armed before owner imports, and the rerun passes.
The original failing console output is preserved in-session; this report does
not claim the incident was blocked by a constructor/network guard or was
network-free. The current guarded PASS is not proof that the earlier attempt
was safe; no cleanup or recovery claim is made. Scratch/cache path:
`tmp/pycache/`.
