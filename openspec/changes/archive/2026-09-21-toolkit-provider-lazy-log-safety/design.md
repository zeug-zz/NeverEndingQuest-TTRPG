# Design: Provider Lazy-Logger Safety

## Context

`utils/file_operations.py` intentionally enables root DEBUG diagnostics. The existing provider safety policy protects logger objects known at configuration time, but OpenAI/httpx/httpcore create child loggers lazily during client construction or transport initialization. A late child can inherit or receive DEBUG behavior after the first safety call.

## Decisions

### 1. Keep both safety boundaries

The shared factory SHALL retain the current fail-open safety call before provider selection and client construction. It SHALL invoke the same idempotent policy again after the client constructor returns, before the client is returned to callers. The second call covers SDK-created child loggers without changing the client object or request configuration.

Fallback clients use the same factory boundary and therefore receive the same protection. Provider selection, constructor arguments, model routing, timeout, retries, and fallback state remain unchanged.

### 2. Preserve defense in depth

The existing provider-free helper remains responsible for warning-level logger configuration and record redaction. Late-created child loggers must be covered by the post-construction call, while root and directly attached handlers continue to sanitize provider-shaped records.

The policy MUST NOT emit prompts, source excerpts, serialized request data, response bodies, credentials, authorization values, or arbitrary exception text.

### 3. Provider-free verification

Tests SHALL patch the OpenAI constructor and use fake logging records/handlers. They SHALL verify:

- safety runs before and after construction;
- late child loggers are configured at WARNING or safer after the factory boundary;
- request-shaped records are redacted;
- provider request semantics are not altered;
- existing GPT-5 parameter and fallback contracts remain green.

## Rollback

Remove the post-construction invocation and its regressions. The original provider request and fallback paths remain intact.
