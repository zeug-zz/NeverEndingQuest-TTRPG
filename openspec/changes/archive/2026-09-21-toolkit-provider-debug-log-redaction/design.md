## Context

`utils/file_operations.py` configures the root Python logger at DEBUG. OpenAI, httpx, and httpcore records then propagate outside the repository's `NeverEndingQuest` logger and bypass `debug_config.FILTER_PATTERNS`. OpenAI request debug records can include `messages`, `json_data`, headers, and security metadata. The adaptation job reporting layer correctly omits raw provider payloads, but that guarantee does not cover console or root-handler output.

## Goals / Non-Goals

**Goals:**

- Make third-party provider transport logging safe by default.
- Keep application diagnostics and provider warning/error visibility.
- Centralize the policy so all shared-factory clients receive it once.
- Make the policy safe under repeated imports and concurrent client creation.
- Verify behavior without network calls or real credentials.

**Non-Goals:**

- No provider SDK replacement.
- No request/response transformation.
- No broad rewrite of every direct OpenAI call site.
- No logging of full prompts, source packets, or raw response bodies under any debug mode.

## Decisions

### 1. Shared provider-log safety helper

Create a small provider-free helper, such as `utils/provider_log_safety.py`, with an idempotent `configure_provider_log_safety()` entry point. It SHALL configure the known transport logger names (`openai`, `httpx`, `httpcore`, including child loggers) to avoid DEBUG payload emission and SHALL be safe when called repeatedly.

### 2. Defense in depth

Logger levels alone are insufficient because handlers or test harnesses may attach directly to child loggers. The helper SHOULD also provide a redaction filter/formatter for records that contain request-shaped fields. It MUST remove or replace prompt-bearing fields (`messages`, `json_data`, request bodies), credentials, authorization data, and raw response bodies before those records are formatted by application-owned handlers.

### 3. Safe diagnostics

Application code MAY emit bounded provider diagnostics containing provider name, model name, logical stage, status, elapsed time, retry/fallback decision, and a provider request ID when available. It MUST NOT include prompt text, source excerpts, serialized request JSON, response bodies, authorization values, API keys, or arbitrary exception payloads that contain those fields.

### 4. Integration boundary

Call the helper before shared `create_chat_client()` returns a provider client. Preserve existing client construction, model routing, timeout, retry, and fallback behavior. If safety initialization encounters an internal logging error, provider execution MUST continue while the helper reports only a bounded local diagnostic.

The implementation MAY remove or narrow global root DEBUG setup where necessary, but MUST preserve application logger behavior and avoid changing legacy provider request semantics.

### 5. Test isolation

Tests MUST use sentinel prompt text and fake logging records/handlers only. They MUST not require network access, real credentials, or provider SDK calls. Tests MUST prove that enabling application debug mode does not reintroduce raw provider payload output.

## Verification And Rollback

Run the focused provider-log safety suite, existing AI-client factory contracts, adaptation provider-safety/reporting suites, syntax checks, and strict OpenSpec validation. Capture a fake provider request through a test handler and assert that only bounded safe metadata is observable. Rollback removes the integration call and helper without changing provider code paths.
