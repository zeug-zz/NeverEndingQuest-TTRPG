# Task 4.1 - Starting-Location Router Migration

Status: primary software verification PASS. Primary review accepted the facade
contract and focused fake-SDK evidence below. This is not a live G4 or full-goal
completion claim.

## Implementation

- `_ai_analyze_starting_location` makes one real facade
  `llm.call(task="dm_validation", json_output=False, temperature=0.1,
  observer=...)` request. The explicit
  temperature is the actual legacy source value; the former preferred/fallback
  model overrides and SDK clients are no longer caller-owned.
- The existing system/user prompt statements and request-message AST remain
  byte-identical. Router text is stripped at the former content boundary, then
  the original fenced-JSON extraction, JSON decode, required-field check, tuple,
  and nonterminal fallback behavior continue unchanged.
- The shared receipt adapter is attached once per facade call, gated by the
  existing `USAGE_TRACKING_AVAILABLE` flag, and uses opt-in trace site
  `starting_location_analysis`. No API logger is wired because this operation
  had no existing API-log consumer. The fake consumer order is trace then
  tracker, usage remains gated by the existing flag, and there is no manual
  duplicate tracker path.
- `GameLLMTerminalError` is re-raised before both the analysis function's
  generic fallback and `get_module_starting_location`'s outer generic fallback,
  preventing terminal outcomes from becoming a location tuple or reaching the
  caller's persistence block.
- Current semantic inventory: 13 of 15 operations are routed; location
  transition narration and NPC movement remain the two legacy operations.
  Prompt-assembly and prompt-asset goldens were not rehashed or changed.

## Verification

All commands used `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`; no provider/network
access, full `process_action`, main/game loop, or `sys.settrace` was used.
Each listed suite ran in a separate process.

| Suite | Result |
|---|---:|
| `scripts.test_starting_location_router_migration` | 7 passed |
| `scripts.test_core_chat_inventory_contract` | 13 passed |
| `scripts.test_core_chat_request_contracts` | 17 passed |
| `scripts.test_llm_runtime_receipt_adapter` | 15 passed |
| `scripts.test_llm_runtime_launch_reset` | 3 passed |
| `scripts.test_llm_router` | 88 passed |
| `scripts.test_benchmark_model_profiles` | 6 passed |
| `scripts.test_gpt54_chat_params_contract` | 10 passed |
| `scripts.test_gpt54_mini_chat_params_shim` | 6 passed |
| `scripts.test_gpt56_luna_direct_openai_contract` | 41 passed |
| **Total** | **206 passed across 10 separate processes** |

Primary review confirmed the production facade path (including
`temperature=0.1`), tuple return, and JSON/code-block parser behavior. The
focused vertical tests execute the selected complete function with the real
facade/router and real receipt adapter over fake SDK transports and fake
tracker/trace consumers; no live SDK/provider gate was used. They cover normal
and fenced JSON, malformed JSON/nonterminal tuple fallback, a transient
preferred failure followed by one router fallback, receipt and usage-flag
behavior, actual facade string output and request arguments, and
quota/refusal/content-filter terminal exits with one SDK attempt and no accepted
location. A focused source contract proves the outer caller re-raises terminal
errors before its generic exception handler.

Additional checks:

- Scoped `py_compile` passed using `PYTHONPYCACHEPREFIX=tmp/llm-router-task-4-1-pycache`.
- `python3 scripts/check_ascii_compliance.py --summary-only`: 1,144 files
  scanned, zero violations.
- Strict CORE validation: PASS.
- Scoped whitespace check and `git diff --check`: PASS.
- No-ignored-cleanup check: PASS.

Task 4.1 is checked following primary review. Core migration status is 16/25
tasks checked, with 13 of 15 semantic operations migrated and two legacy
operations remaining (transition narration and NPC movement). Other task
checkboxes, goldens, and incident records were retained. G4 remains pending;
this report makes no live or full-goal completion claim. No raw prompt literal,
prompt asset, route flag, configuration, factory, adapter, router, transition
operation, movement operation, or other unrelated runtime behavior was changed.
