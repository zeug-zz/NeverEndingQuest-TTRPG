# Task 4.2 Combat Live Smoke for gpt-5.6-luna Direct-OpenAI Model Swap

Timestamp (UTC): 2026-08-03T02:57:59Z
Change: gpt56-luna-direct-openai-model-swap
Task: 4.2 Run one bounded direct-OpenAI combat request and verify valid JSON/action output, existing timeout protection, and no GPT-5.4 fallback.

## 1. Method

- Provider preflight (no network): confirmed the active provider is direct OpenAI and the credentials are present, without printing any secret.
  - `model_config.LLM_PROVIDER` = `openai`
  - `config.LLM_PROVIDER` = `openai`
  - `_get_actual_provider()` resolved to `("openai", False)` (not OpenRouter)
  - `config.OPENAI_API_KEY` present (boolean check only; value never printed)
- Timeout protection preflight: `model_config.COMBAT_API_TIMEOUT_SECONDS` = `120` (unchanged existing combat timeout constant).
- Used the repository path exactly as specified: `create_chat_client()` for the client and `get_chat_completion_params('combat_main', 'gpt-5.6-luna')` for the request parameters, so the real combat shim parameters were exercised.
- Minimal synthetic combat prompt with no campaign data, credentials, filesystem state, or user content: a system line describing the test harness and a user line requiring exactly one JSON object with `narration` (short string) and `actions` (array of minimal placeholder action objects).
- Exactly one Chat Completions request. No retry, no streaming, no application/server startup.
- Per-request SDK timeout set to 30 seconds (task cap; the repository combat constant remains 120).
- Inline `.venv/bin/python -c` probe; no scratch scripts or files created.
- Credentials were never printed; any error text was sanitized against the API key value.

## 2. Provider (sanitized)

- Configured provider: direct OpenAI (both `model_config.LLM_PROVIDER` and `config.LLM_PROVIDER` = `openai`)
- OpenRouter in use: No
- API key present: Yes (value not disclosed)

## 3. Request parameters (as emitted by the GPT-5-family combat shim)

- Exact model ID: `gpt-5.6-luna`
- `reasoning_effort`: `medium` (combat `combat_main` profile)
- `verbosity`: `medium`
- Legacy `temperature` / `top_p`: omitted (default GPT-5 shim behavior)
- Timeout: 30 seconds (transport-level probe cap; repository constant `COMBAT_API_TIMEOUT_SECONDS = 120` confirmed intact)

## 4. Result

- Pass/Fail: PASS
- Response model ID (selected model as returned by API): `gpt-5.6-luna`
- GPT-5.4 fallback detected: No (returned model ID is `gpt-5.6-luna`; no `gpt-5.4`-prefixed model observed)
- Parameter acceptance: accepted (no provider rejection of model or parameters)
- Response validity: `finish_reason=stop`; content parsed locally as exactly one JSON object with valid action shape:
  - `narration`: string, 26 chars (harmless deterministic test output)
  - `actions`: array with 1 item; every item is an object with `action` and `note` keys

## 5. Latency

- Elapsed: 2947 ms (single call)

## 6. Token telemetry

- prompt_tokens: 96
- completion_tokens: 65
- total_tokens: 161

## 7. Provider errors

- None. No sanitization was required.

## 8. Conclusion

The single bounded direct-OpenAI combat request succeeded: `gpt-5.6-luna` accepted the GPT-5-family combat shim parameters (`reasoning_effort="medium"`, `verbosity="medium"`, no legacy sampling params), returned a single parseable JSON object with a short `narration` string and a valid `actions` array, and reported the selected model as `gpt-5.6-luna` with no GPT-5.4 fallback. The existing combat timeout constant `COMBAT_API_TIMEOUT_SECONDS = 120` was confirmed unchanged. Latency and token telemetry were recorded. No credentials were exposed at any point. Task 4.2 is complete.
