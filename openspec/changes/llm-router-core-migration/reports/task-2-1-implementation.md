# Task 2.1 Implementation Report

## Scope and Result

Migrated only `main.py::generate_arrival_narration` and
`main.py::generate_seamless_transition_narration` to the explicit
`llm.call(task="dm_main", messages=..., json_output=False)` facade. Both
functions retain their signatures, dormant status, request content, response
parsing/sanitization, generic nonterminal fallback, and existing no-call
short-circuit. No SDK model, timeout, client, or provider fallback is supplied
by these callers.

The two existing API log events and usage-tracker labels now flow through
`make_legacy_receipt_observer`; there is no duplicate manual tracking or new
API-log site. The observer keeps the producer labels:

- Arrival: endpoint `narration_generator`, purpose
  `generate_narrative_summary`, API logger endpoint `narration_generator`.
- Stitching: endpoint `narrative_stitching`, purpose
  `stitch_location_descriptions`, API logger endpoint `narrative_stitcher`.

Each function explicitly re-raises `GameLLMTerminalError` before its generic
fallback handler. Fake quota, refusal, and content-filter terminal outcomes
each make one router call, escape unchanged, and do not produce fallback
narration. Ordinary runtime failures retain the original uneventful-arrival
and concatenation fallbacks.

Both calls pass the existing `TEMPERATURE` value through the facade's
`temperature` option. The adapter is told to preserve the historical
API-logger-before-tracker order for these two producers, and its optional usage
gate follows `USAGE_TRACKING_AVAILABLE`: when disabled, the tracker getter is
not called while the existing API logger still records one response.

## Prompt and Behavior Evidence

The existing literal request-message hashes were retained and pass unchanged:

- Arrival request messages:
  `679f1f24e08598cbab8a5d95f4679fe8d5baff71d7d83a50810c601e7f141431`
- Seamless transition request messages:
  `15a6c624f077e8e3de71e5b616c57593a0521cc9fc8e3a856ac8e426469aafce`

Tests execute the selected actual functions from `main.py`, not copied
implementations. The fake router returns text, invokes the observer separately
with its SDK-shaped raw response, and the additional integration case sends a
fake SDK response through the real `LLMRouter` and the selected arrival helper.
This proves that the facade's string return is consumed correctly and that the
raw response is still delivered independently to the receipt observer. The
integration case also proves the disabled usage gate never resolves its
tracker, while one existing API-log event still runs. Empty departure/arrival
cases return the other narration with zero router calls. Ordinary fake
failures retain both historical fallback strings. With usage enabled, injected
receipt consumers prove one API-log event followed by one tracker event per
response, with unchanged messages and producer labels.

The first implementation's helper test accidentally returned an SDK-shaped
object from its fake router, masking the router's actual string return; that
verification was invalid. This retry changed both production helpers to strip
the returned text and corrected the fake contract, then added the real-router /
fake-SDK integration case above. No frozen prompt or asset golden was changed.

## Inventory Boundary

The fresh inventory now explicitly recognizes `llm.call` and asserts exactly
one such call, task `dm_main`, `json_output=False`, no raw SDK request, and no
nested recovery helper for the two migrated operations. The other 13 semantic
operations remain strict legacy assertions; their current transport variant
counts remain unchanged:

- `validate_ai_response`: 1; `generate_module_summary`: 2;
  `get_ai_response`: 4 recovery-helper variants.
- Bootstrap resume: 2 helper variants; initial scene: 1.
- Combat turn retry: 3; combat validation: 1; dialogue summary: 1;
  round summary: 1; initiative tracker: 1 direct SDK constructor/request.
- Starting-location analysis: 2; `process_action`: 2; NPC movement: 2.

No other owner was migrated. Router facade source checks now allow the
necessary facade import while continuing to prohibit production calls to the
gated `llm.decide()` API.

## Verification

Provider-free commands ran in separate processes with
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1` (Python cache prefix under
`tmp/pycache-task-2-1`):

| Suite | Result |
|---|---:|
| `scripts.test_core_chat_inventory_contract` | 12 passed |
| `scripts.test_core_chat_request_contracts` | 12 passed |
| `scripts.test_llm_runtime_receipt_adapter` | 15 passed |
| `scripts.test_llm_runtime_launch_reset` | 3 passed |
| `scripts.test_llm_router.py` | 88 passed |
| `scripts.test_benchmark_model_profiles` | 6 passed |
| `scripts.test_gpt54_chat_params_contract` | 10 passed |
| `scripts.test_gpt54_mini_chat_params_shim` | 6 passed |
| `scripts.test_gpt56_luna_direct_openai_contract` | 41 passed |
| `scripts.test_provider_empty_response_retry` | 37 passed |

Total for this retry: 230 passing test executions across ten processes. The
prior invocation's 228 passing executions did not establish correct facade
return-shape handling; this report supersedes that evidence. An earlier
unprefixed compile may have written bytecode under root `__pycache__`; it was
not inspected or cleaned. Retry verification uses `PYTHONDONTWRITEBYTECODE=1`
and a `PYTHONPYCACHEPREFIX` under `tmp/`.

Primary review confirmed the corrected facade string consumption in both
helpers and the evidence above. Primary software verification: PASS (230 test
executions across ten separate processes). Task 2.1 is checked; the other 18
remaining tasks are unchecked. Exactly two of the 15 semantic operations are
migrated; the other 13 remain legacy. No real provider calls, server
preparation, runtime capture, campaign work, or live verification were
performed; this is not a G4 or full-goal completion claim.
