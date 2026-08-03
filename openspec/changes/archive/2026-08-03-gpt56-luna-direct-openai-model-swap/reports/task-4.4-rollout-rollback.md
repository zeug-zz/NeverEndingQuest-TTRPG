# Task 4.4 Rollout Rollback Instructions for gpt-5.6-luna Direct-OpenAI Model Swap

Timestamp (UTC): 2026-08-03T08:20:00Z
Change: gpt56-luna-direct-openai-model-swap
Task: 4.4 Record rollback instructions and any observed latency or provider limitations; if Luna is unavailable or rejects the request contract, restore the prior model assignments and rerun the targeted regression suite.

## 1. Rollout decision

Luna is AVAILABLE and ACCEPTS the request contract. No rollback was executed.

- Task 4.1 narrator smoke: PASS (one bounded direct-OpenAI narrator request).
- Task 4.2 combat smoke: PASS (one bounded direct-OpenAI combat request).
- Task 4.3 mode smoke: PASS (single-player and TABLETOP MODE fresh-process smokes plus 128 provider-free regression tests).
- Provider rejection of `gpt-5.6-luna`: none observed.
- Unavailability of `gpt-5.6-luna`: none observed.
- Silent fallback to `gpt-5.4-mini-2026-03-17`: none observed (API echoed `gpt-5.6-luna` in both live requests).

Because the model and its request contract passed, the conditional branch of this task (restore prior assignments and rerun the regression suite) is NOT executed. This report records the rollback procedure for future operators.

## 2. Direct-OpenAI model/parameter acceptance (from tasks 4.1 and 4.2)

Both bounded live requests were sent to direct OpenAI with the exact model ID `gpt-5.6-luna` and parameters emitted by the existing GPT-5-family shim:

- Model: `gpt-5.6-luna` (no provider-prefixed ID; direct OpenAI client received the string unchanged)
- `reasoning_effort`: `medium` (narrator `dm_main` profile in 4.1; combat `combat_main` profile in 4.2)
- `verbosity`: `medium` in both profiles
- Legacy `temperature` / `top_p`: omitted (default GPT-5 shim behavior)
- Provider response: accepted; no rejection of the model ID or any shim parameter
- Response validity: `finish_reason=stop` in both; narrator produced non-empty text; combat produced exactly one parseable JSON object with `narration` (string) and `actions` (array of `{action, note}` objects)
- No GPT-5.4 fallback: the API echoed `gpt-5.6-luna` as the response model in both requests

## 3. Observed latency and token telemetry (sanitized, from tasks 4.1 and 4.2)

| Request | Elapsed (ms) | prompt_tokens | completion_tokens | total_tokens |
|---------|--------------|---------------|-------------------|--------------|
| 4.1 narrator (single call) | 7402 | 44 | 50 | 94 |
| 4.2 combat (single call) | 2947 | 96 | 65 | 161 |

Derived end-to-end rates for reference only:

- 4.1 narrator: ~12.7 total tokens/s
- 4.2 combat: ~54.6 total tokens/s

These derived rates are incidental arithmetic over two tiny samples, not a repository contract. No provider errors were observed in either request, so no credential sanitization was required.

## 4. Performance-guarantee caveat (explicit)

These two tiny samples DO NOT establish a >100 token/s performance guarantee for `gpt-5.6-luna`. The observations are bounded single calls with minimal synthetic prompts, and measured latency/throughput is affected by at least:

- reasoning overhead (medium `reasoning_effort` on the narrator/combat profiles), which can add hidden reasoning tokens and wall-clock time not reflected in visible `completion_tokens`;
- output length (longer narration/combat outputs take longer and can run at different rates than the short probe outputs);
- provider load and endpoint variance at request time;
- per-request timeout configuration and transport conditions.

Per the change proposal and design, observed tokens per second remain provider/runtime measurements and are explicitly NOT a performance guarantee in this change. Any future throughput claim requires a dedicated, larger measurement campaign with representative prompts and a defined measurement contract.

## 5. Rollback procedure (documented; NOT executed)

Rollback is a configuration-only revert plus a clean restart. No data migration and no code migration are involved.

1. Restore the active direct-OpenAI GPT-5 model assignments in `model_config.py` from `gpt-5.6-luna` back to `gpt-5.4-mini-2026-03-17`. This includes every active runtime assignment replaced in task 1.2, notably `GPT5_MINI_MODEL` and `GPT5_FULL_MODEL`, plus any other active `gpt-5.6-luna` role constants. `config.py` imports these values at process startup, so no `config.py` edit is needed.
2. Restart the process with a clean server restart (full stop/start, not a reload) so the restored assignments are loaded; verify the selected model appears as `gpt-5.4-mini-2026-03-17` in model-selection logging/display after restart.
3. Rerun the targeted provider-free contract and regression suites with `.venv/bin/python`. The suites exercised in task 3.3/4.3 are the reference set:
   - `scripts.test_gpt56_luna_direct_openai_contract` (Luna selection/parameter/display/OpenRouter-isolation contract; its fixtures follow whichever active model is configured, so after rollback its assertions must track `gpt-5.4-mini-2026-03-17`)
   - `scripts.test_gpt54_chat_params_contract`
   - `scripts.test_gpt54_mini_chat_params_shim`
   - `scripts.test_multi_pc_combat` (TABLETOP MODE runtime)
   Compile all modified Python files first (`py_compile`), as done in task 3.3.
4. Rerun a bounded smoke if needed: one bounded direct-OpenAI narrator request and one bounded combat request against `gpt-5.4-mini-2026-03-17` (same probe shape as tasks 4.1/4.2) to confirm parameter acceptance and model echo, then a short single-player and TABLETOP MODE process smoke (same shape as task 4.3) after the restart.
5. Retain the GPT-5-family compatibility and test changes that remain valid for the GPT-5 family (the shim is generic; the same helper serves both model IDs). Do not revert shim/test work as part of rollback unless a specific test proves incompatible.

The GPT-5-family failure-safety requirement (spec: Failure and rollback safety) is satisfied by this procedure: an unavailable/rejected Luna surfaces through the existing error/retry path and NEVER silently substitutes `gpt-5.4-mini-2026-03-17`; rollback is an explicit operator action, not an automatic fallback.

## 6. OpenRouter scope note

No OpenRouter change is part of this rollout or of the rollback procedure. Rollback touches only the direct-OpenAI model assignments in `model_config.py`. `OPENROUTER_CHAT_MODEL` remains `moonshotai/kimi-k2.5`, and OpenRouter-specific `thinking` request behavior remains unchanged (verified by the source-contract coverage from task 2.5 and the 4.3 probes). Do not edit OpenRouter model settings or request fields when rolling back.

## 7. Credential and scope compliance

- No credentials were read, printed, or recorded in this task or in the referenced smoke reports; all provider checks were boolean/presence-only and sanitized.
- No new live calls were made for this report; it synthesizes tasks 4.1-4.3 evidence only.
- No runtime/config/test source files were edited; this report is documentation-only.
- No OpenRouter calls or changes were made.

## 8. Conclusion

The `gpt-5.6-luna` direct-OpenAI rollout passed its live-smoke gates (tasks 4.1-4.3): the model accepted the GPT-5-family shim contract, produced valid narrator and combat outputs with no GPT-5.4 fallback, and both single-player and TABLETOP MODE select Luna after a clean restart. Latency and token telemetry were recorded for the two bounded requests; these two tiny samples do not establish a >100 token/s guarantee. Rollback instructions are documented above (restore `gpt-5.4-mini-2026-03-17` assignments, restart, rerun the targeted provider-free suites, bounded smoke if needed) and were NOT executed because Luna passed. No OpenRouter change is part of rollback. Task 4.4 is complete.
