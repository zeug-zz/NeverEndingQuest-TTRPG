# Task 1.6 Implementation Report

## Scope

Added `utils.llm_runtime.make_legacy_receipt_observer(...)` as the documented
per-call adapter API for later producers. Producers pass its returned callback
as `observer=` to `llm.call()`. Tracker usage is lazily resolved through
`get_global_tracker().track(...)`; API logging is enabled only when a producer
supplies both its legacy `endpoint_name` and `messages`; combat trace is opted
into with `trace_site` and uses the existing `trace_enabled()` gate and
`emit_trace_event("provider", ...)` writer.

Response-kind receipts invoke each applicable consumer once even when the raw
response is `None`, empty, or malformed. SDK attempts deduplicate by
`attempt_id`; constructor failures deduplicate by per-call ID, kind, and
fallback state. The deduplication lock is released before callbacks. Tracker
receives a detached usage-only copy with validated prompt/completion/total
counts and receipt-verified reported cost (including top-level actual zero);
unknown or invalid counts result in `usage=None`, never zero-fill. Estimated
cost is not injected as provider-reported cost. Copied legacy context retains
producer labels while receipt-owned fields override conflicting values; a
legacy `model` label is kept as `legacy_context_model`. Router stats snapshots
and totals are not passed. Trace records distinguish requested from actual
resolved model and preserve unknown cost/usage. Constructor failures use a
gated `combat_observation` event, not an SDK `provider` row. The callback order
is trace, tracker, then applicable API logger; ordinary failures are isolated.

No producer call sites were wired or manually tracked events removed. No
router-local stats were aggregated into legacy totals, and no media, UI, or
accounting algorithm changes were made.

## Focused Evidence

`scripts/test_llm_runtime_receipt_adapter.py` uses real `LLMRouter` calls with
fake clients and injected consumers. It verifies three empty-`None` responses
followed by fallback success (four consumer events); `None` response receipts;
JSON retry/malformed and text-empty responses; concurrent calls; callback lock
release and reentrant stats queries; top-level actual costs zero and positive;
partial, unknown, and invalid counts; context-copy/trusted-field precedence;
trace/tracker/logger order and failure isolation; constructor de-duplication;
trace-off consumer activity; and exact real-writer model/cost behavior with
unchanged SDK response bytes. There is no network or provider access.

## Verification

Passed in separate processes with `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`:

- Adapter tests: 14.
- Router suite: 88.
- Runtime launch reset suite: 3.
- Benchmark model profiles: 6.
- GPT-5.4 chat contract: 10.
- GPT-5.4 mini shim: 6.
- GPT-5.6 Luna direct OpenAI contract: 41.
- Core chat inventory contracts: 11.
- Core chat request contracts: 11.
- Combat trace observation writer: 3.
- Adapter suite repeated in a second separate process: 14.
- Python compilation for the adapter and its tests; ASCII compliance (1141
  files, zero violations); `git diff --check`; strict OpenSpec validation.

## Focused Retry

The primary retry initially reported one failure in the 14-test adapter run:
the real-writer test used the fixed append path
`tmp/llm-runtime-receipt-adapter/combat.jsonl`, whose accumulated size from
prior runs was 8454 bytes. The failing assertion measured the entire historical
file against the per-event 8192-byte limit. The test now gives the real writer
a unique `TemporaryDirectory(dir="tmp")`, checks one event for this invocation,
and checks each serialized event against the unchanged 8192-byte limit. It
retains the off-gate, actual model, unknown cost, and unchanged response-byte
assertions. The old shared append artifact was neither truncated nor deleted.
Review found no other fixed append-path fixture in this adapter test module.

After the test-only correction, the adapter passed twice in separate processes
(14 tests each). The trace-writer (3), launch-reset (3), router (88), benchmark
(6), GPT-5.4 chat (10), GPT-5.4 mini (6), GPT-5.6 Luna (41), core inventory
(11), and core request contract (11) suites also passed in separate processes.
The successful runs total 207 test executions; no ignored cleanup errors were
reported. Compile, ASCII, diff, and strict OpenSpec validation passed.

Primary software verification: PASS. The 207 executions were run in 11
separate processes and cover 193 unique tests (the 14-test adapter suite ran
twice). Primary review confirmed the corrected adapter's once-only delivery,
context and usage/cost handling (including actual cost zero and unknown values),
constructor-error handling, and consumer order. The separately reviewed fatal-
denial guard compatibility proof remains independent and unchanged; this retry
did not modify the guard or writer tests. This is a software-verification
verdict only, not a new live-verification claim.

The existing guard and writer tests were not modified in this retry. The
separately reviewed guard compatibility correction remains independent of this
adapter implementation. All requested verification suites passed as separate
processes.

Task 1.6 remains unchecked for planner verification. Caller migrations and
producer-by-producer duplicate removal remain later tasks.
