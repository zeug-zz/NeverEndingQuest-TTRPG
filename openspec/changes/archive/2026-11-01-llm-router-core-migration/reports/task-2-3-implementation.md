# Task 2.3 Implementation Report

`main.py::get_ai_response()` makes one `llm.call(task="dm_main", json_output=False)` request, supplying the existing action prediction as a validated `model_tier` simple/complex hint and enabling the facade's bounded `empty_retry_limit=2`. This intentionally honors the approved RP tier/profile model policy rather than preserving the old GPT-5 branch's competing raw `model=` override. The old model names are explicitly labeled legacy hints; actual requested/resolved model and cost/provenance in the quality result come only from that call's local receipt state. No global last-response state is used. The GPT-5 and GPT-4.1 branches retain their existing parameter difference: GPT-5 omits temperature, GPT-4.1 supplies `TEMPERATURE`; prediction and forced-full route conditions remain intact.

### Legacy raw-model choice versus approved profile routing

| Existing request condition | Old pre-family model hint | Old GPT-5 raw request model | New approved `model_tier` (both families) |
|---|---|---|---|
| Initial ordinary input, prediction says no actions | `DM_MINI_MODEL` | `GPT5_MINI_MODEL` (branch override) | `simple` |
| Initial ordinary input, prediction says actions | `DM_FULL_MODEL` | `GPT5_MINI_MODEL` (branch override) | `complex` |
| Validation retry 1-3 | `DM_FULL_MODEL` | `GPT5_MINI_MODEL` (branch override) | `complex` |
| Validation retry 4+ | `DM_FULL_MODEL` | `GPT5_FULL_MODEL` | `complex` |
| Module-creation prompt, retry 0-3 | `DM_FULL_MODEL` | `GPT5_MINI_MODEL` (branch override) | `complex` |
| Module-creation prompt, retry 4+ | `DM_FULL_MODEL` | `GPT5_FULL_MODEL` | `complex` |
| Intelligent routing disabled, retry 0 | `DM_FULL_MODEL` | `GPT5_MINI_MODEL` (branch override) | `complex` |

For the old GPT-4.1/OpenRouter branch, the preferred raw model was `provider_model` when it differed from the pre-family hint, otherwise that hint; the fallback used the pre-family hint. The new router does not forward either raw model choice: configured profiles/fallback and explicit task overrides remain authoritative. This is an intentional removal of a competing model override for normal profile migration, not literal legacy SDK model-choice parity. Retry thresholds, route booleans, temperature branch conditions, prediction booleans, and generation prompt assembly remain unchanged.

Typed quota/refusal/content-filter errors are re-raised from the narrator before fallback or parsing. `main_game_loop()` catches these only at the narrator/validator call boundary, marks the interaction ready, exits the current bounded turn loop, and continues to the next outer user-input iteration before rejected-response handling or action application. Bounded fake vertical tests execute the current generation try, validation try, terminal flag, ready/continue path, and retry-exhaustion admission guard in a two-input harness; generation terminal cases make one first-attempt facade request, validation terminal cases make one generation and one validation request before proceeding to the next input, with no failed-response processing/persistence. Removing the terminal guard reaches a forbidden rejected-turn persistence spy. A finite empty-exhaustion case confirms the six-attempt error escapes one facade call without a caller fallback/retry. The router suite separately proves the actual preferred/fallback six-SDK ceiling and once-only receipts. Existing nonterminal validation retry bound remains five in `main_game_loop()` and validator retries remain three. The inventory now reports four migrated semantic operations and eleven strictly legacy operations. Prompt assembly AST/asset baselines from task 1.1 passed unchanged; no prompt asset or raw golden was rewritten.

Main narrator SDK receipts use `trace_site="main_dm"`; the migrated validator now supplies only `trace_site="main_validation"` as an additional observer metadata argument so failed validation SDK attempts are traceable. Its API logger, usage gate, callback order, call parameters, and validation behavior are otherwise unchanged.

## Focused Verification

- `scripts.test_core_chat_request_contracts`: 16 tests passed; finite selected requests use fake routing, bounded main generation/validation terminal verticals cover quota/refusal/filter and next-input behavior, empty exhaustion has no caller retry, the approved tier table and branch parameters are asserted, and all-15 owner prompt AST/asset baselines remain unchanged.
- `scripts.test_core_chat_inventory_contract`: 13 tests passed; current inventory and terminal caller control-flow checks pass (4 migrated, 11 legacy).
- `scripts.test_llm_runtime_receipt_adapter`: 15 tests passed.
- `scripts.test_llm_runtime_launch_reset`: 3 tests passed.
- `scripts.test_llm_router.py`: 88 tests passed, including empty response preferred/fallback budgets, terminal outcomes, observer receipts, tier parity, and model override precedence.
- `scripts.test_benchmark_model_profiles`: 6 tests passed.
- `scripts.test_gpt54_chat_params_contract`: 10 tests passed after updating its main narrator source assertion to the facade boundary.
- `scripts.test_gpt54_mini_chat_params_shim`: 6 tests passed.
- `scripts.test_gpt56_luna_direct_openai_contract`: 41 tests passed.
- `scripts.test_provider_empty_response_retry`: 37 tests passed after repointing its main narrator source contract to the facade.
- Python compilation passed with `PYTHONPYCACHEPREFIX=tmp/task-2-3-pycache`.
- ASCII compliance: 1141 files scanned, zero violations; `git diff --check` passed; `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` passed.
- No-ignored-cleanup check passed. With task 2.3 checked, the core migration ledger is 9/25 tasks complete; 4/15 semantic operations are migrated and 11 remain legacy. The separate facade ledger remains 21/21 with its historical 131-test evidence unchanged. No G4, live, or full-goal completion is claimed.

All listed tests ran provider-free in separate processes with telemetry disabled. No live provider, server, full owner loop, or capture campaign was run. This report covers software work for task 2.3 only; planner verification remains pending, and subsequent tasks/G4 primary verification are not claimed complete.

### Ledger-path correction

The preceding builder response edited the facade ledger in error. All passages inserted by that patch were removed using their exact recorded text; no pre-existing facade working-tree edits were reset or otherwise changed. This report and the task checkbox above are the intended core-ledger update. No pre-reversal hashes were captured, so this report does not claim hash-based proof of restoration.
