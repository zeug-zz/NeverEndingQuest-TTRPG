# Task 4.1 Narrator Live Smoke for gpt-5.6-luna Direct-OpenAI Model Swap

Timestamp (UTC): 2026-08-03T02:55:52Z
Change: gpt56-luna-direct-openai-model-swap
Task: 4.1 Run one bounded direct-OpenAI narrator request using `gpt-5.6-luna` and verify successful parameter acceptance, valid response content, selected-model logging, latency, and token telemetry without exposing credentials.

## 1. Method

- Provider preflight (no network): confirmed the active provider is direct OpenAI and the credentials are present, without printing any secret.
  - `model_config.LLM_PROVIDER` = `openai`
  - `config.LLM_PROVIDER` = `openai`
  - `_get_actual_provider()` resolved to `("openai", False)` (not OpenRouter)
  - `config.OPENAI_API_KEY` present (boolean check only; value never printed)
- Used the repository path exactly as specified: `create_chat_client()` for the client and `get_chat_completion_params('dm_main', 'gpt-5.6-luna')` for the request parameters, so the real shim parameters were exercised.
- Minimal synthetic prompt with no campaign data, credentials, filesystem state, or user content: a system line describing the test harness and a user line asking for the single word `READY`.
- Exactly one Chat Completions request. No retry, no streaming, no application/server startup.
- Per-request SDK timeout set to 30 seconds (task cap).
- Inline `.venv/bin/python -c` probe; no scratch scripts or files created.
- Credentials were never printed; any error text was sanitized against the API key value.

## 2. Provider (sanitized)

- Configured provider: direct OpenAI (both `model_config.LLM_PROVIDER` and `config.LLM_PROVIDER` = `openai`)
- OpenRouter in use: No
- API key present: Yes (value not disclosed)

## 3. Request parameters (as emitted by the GPT-5-family shim)

- Exact model ID: `gpt-5.6-luna`
- `reasoning_effort`: `medium` (narrator `dm_main` profile)
- `verbosity`: `medium`
- Legacy `temperature` / `top_p`: omitted (default GPT-5 shim behavior)
- Timeout: 30 seconds (transport-level, not a model parameter)

## 4. Result

- Pass/Fail: PASS
- Response model ID (selected model as returned by API): `gpt-5.6-luna`
- Parameter acceptance: accepted (no provider rejection of model or parameters)
- Response validity: `finish_reason=stop`; non-empty content of length 25 chars:
  `The model is operational.` (harmless deterministic test output)

## 5. Latency

- Elapsed: 7402 ms (single call)

## 6. Token telemetry

- prompt_tokens: 44
- completion_tokens: 50
- total_tokens: 94

## 7. Provider errors

- None. No sanitization was required.

## 8. Conclusion

The single bounded direct-OpenAI narrator request succeeded: `gpt-5.6-luna` accepted the GPT-5-family shim parameters (`reasoning_effort="medium"`, `verbosity="medium"`, no legacy sampling params), returned valid content, and provided latency and usage telemetry. Selected-model logging shows `gpt-5.6-luna` both configured and echoed by the API. No credentials were exposed at any point. Task 4.1 is complete.
