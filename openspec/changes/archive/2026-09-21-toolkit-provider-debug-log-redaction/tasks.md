## 1. Safe Provider Logging Foundation

- [x] 1.1 Add an idempotent provider-log safety helper that configures OpenAI/httpx/httpcore transport loggers and redacts prompt, request-body, authorization, credential, and raw-response fields. Verify with provider-free logging unit tests.
- [x] 1.2 Ensure root/application logging setup cannot re-enable third-party DEBUG payload output while preserving existing NeverEndingQuest logger categories and error visibility. Verify with a captured console/debug-handler test.

## 2. Shared Factory Integration

- [x] 2.1 Invoke the safety policy before shared provider client creation, including fallback-client creation, without changing model, timeout, request, retry, or fallback behavior. Verify existing AI-client factory contracts.
- [x] 2.2 Add bounded safe provider diagnostics for stage/provider/model/status where required; ensure no prompt, source excerpt, serialized request, response body, or credential reaches logs. Verify adaptation reporting still keeps `raw_provider_payload_exposed` false.

## 3. Regression And Verification

- [x] 3.1 Add regression coverage for sentinel prompt/source text, request-shaped log records, authorization fields, child logger propagation, repeated configuration, and debug-mode enablement.
- [x] 3.2 Run focused security/logging, AI-client factory, adaptation provider-safety, adaptation reporting, syntax, and strict OpenSpec validation suites.
- [x] 3.3 Run a provider-free adaptation logging smoke that exercises the toolkit client boundary and confirms console/debug output contains only bounded safe diagnostics.
