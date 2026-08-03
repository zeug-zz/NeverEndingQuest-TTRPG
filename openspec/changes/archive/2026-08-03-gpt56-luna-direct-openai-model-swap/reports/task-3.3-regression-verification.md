# Task 3.3 Regression Verification for gpt-5.6-luna Direct-OpenAI Model Swap

Timestamp (UTC): 2026-08-03T07:15:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 3.3 Compile all modified Python files and run the targeted GPT-5 shim, narrator, combat, and routing regression suites with `.venv/bin/python`.

## 1. Method

- Compiled every Python file changed by this OpenSpec change with `.venv/bin/python -m py_compile`.
- Ran the focused provider-free GPT-5/Luna contract suites.
- Ran the targeted narrator, combat, and routing regression suites covering the touched hot paths.
- Ran `scripts.test_multi_pc_combat` (completed well within the normal test timeout).
- No live provider/API calls were made; all checks are provider-free.
- The worktree contains unrelated accurate-ingest/toolkit changes; those files were not modified, staged, or reverted.

## 2. Compile checks (all changed Python files)

Command:

```bash
.venv/bin/python -m py_compile model_config.py utils/ai_client_factory.py \
  updates/update_encounter.py updates/plot_update.py \
  scripts/test_gpt54_mini_chat_params_shim.py \
  scripts/test_gpt54_chat_params_contract.py \
  scripts/test_gpt56_luna_direct_openai_contract.py
```

Result: `COMPILE PASS (EXIT=0)` for all 7 files.

## 3. Focused provider-free GPT-5/Luna suites

Command:

```bash
.venv/bin/python -m unittest -q scripts.test_gpt56_luna_direct_openai_contract \
  scripts.test_gpt54_mini_chat_params_shim scripts.test_gpt54_chat_params_contract
```

Result: `Ran 55 tests in 0.005s - OK (EXIT=0)`
(39 Luna direct-OpenAI contract tests + 16 generic GPT-5 shim contract tests)

## 4. Targeted regression suites

```bash
.venv/bin/python -m unittest -q scripts.test_combat_runtime_prompt_authority
# Ran 7 tests - OK (EXIT=0)

.venv/bin/python -m unittest -q scripts.test_combat_validation_routing
# Ran 11 tests - OK (EXIT=0)

.venv/bin/python -m unittest -q scripts.test_multi_pc_combat
# Ran 73 tests in 0.081s - OK (EXIT=0)

.venv/bin/python -m unittest -q scripts.test_narrator_prompt_validation_refactor
# Ran 41 tests - FAILED (failures=2) -- see pre-existing failure section below
```

## 5. Pre-existing unrelated failure (clearly separated)

`scripts.test_narrator_prompt_validation_refactor` reports 2 failures, both in
`TestNarratorSceneContextHygieneContracts`:

1. `test_narrator_payload_hygiene_helpers_exist` - asserts the single-line string
   `def _sanitize_narrator_payload(messages_to_send, current_module_name="", current_location_id=""):`
   in `main.py`, but the function signature is wrapped across lines in `main.py` (lines 4995-4997).
2. `test_narrator_payload_filters_location_history_and_atlas` - asserts the single-line call
   `messages_to_send = _sanitize_narrator_payload(messages_to_send, current_module_name, current_location_id)`
   in `main.py`, but the call is wrapped across lines (lines 5265-5267).

**Why this is unrelated to the Luna change:**

- This change touches only `model_config.py`, `utils/ai_client_factory.py`,
  `updates/update_encounter.py`, `updates/plot_update.py`, and the three test scripts.
- `main.py` has no uncommitted diff (`git diff --stat main.py` empty) and its last commit is
  `8dd49a79` (level-up JSON fix), which predates this change. The failing assertions are
  whitespace-sensitive source-contract checks against committed baseline content.
- The remaining 39 tests in the narrator suite pass, including the functional payload-hygiene,
  plot-compaction, rejected-turn logging, and retry-hygiene contracts that are not whitespace-sensitive.

This failure reproduces on the committed baseline and cannot be affected by model configuration.
Fixing it would require either re-wrapping `main.py` or relaxing the test string (out of scope for
this change; no runtime/test source edits are permitted in this verification task).

## 6. Conclusion

- Compile: PASS (7/7 files).
- Focused GPT-5/Luna provider-free suites: PASS (55/55).
- Combat runtime authority: PASS (7/7).
- Combat validation routing: PASS (11/11).
- Multi-PC combat: PASS (73/73).
- Narrator suite: 39/41 PASS; the 2 failures are pre-existing, unrelated source-contract
  formatting mismatches in untouched `main.py` (verified above).

No live provider/API calls were made. Task 3.3 is complete for this change; the 2 pre-existing
narrator failures are recorded above for separate triage.
