## 1. Factory Boundary

- [x] 1.1 Reapply `configure_provider_log_safety()` after shared OpenAI/OpenRouter client construction while retaining the existing pre-construction fail-open call; preserve provider selection, constructor arguments, model routing, timeout, retry, fallback, and error behavior.
- [x] 1.2 Verify both primary and fallback factory paths receive post-construction protection without network calls or real credentials.

## 2. Late Logger Regression Coverage

- [x] 2.1 Add provider-free tests that create or simulate late `openai.*`, `httpx.*`, and `httpcore.*` child loggers after the first safety call and verify DEBUG payload records are suppressed or redacted.
- [x] 2.2 Add ordering and request-immutability assertions proving the safety policy changes logging state only and never mutates provider request objects or payload arguments.

## 3. Verification

- [x] 3.1 Run provider-log safety, AI-client factory, GPT-5 chat-parameter, adaptation provider-safety, syntax, diff, and strict OpenSpec validation suites.
- [x] 3.2 Run a fresh provider-free shared-factory smoke that captures stdout/handler output and confirms no prompt, source, request JSON, response body, header, or credential sentinel is exposed.
