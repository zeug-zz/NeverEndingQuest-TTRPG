## 1. Adaptation Output Boundary

- [x] 1.1 Add a project-relative adaptation-scoped output safety utility/context that sanitizes stdout/stderr, logger records, progress callbacks, GUI payloads, and persisted diagnostics into bounded ASCII phase/status/count/code events.
- [x] 1.2 Wire the output boundary into adaptation upload/text workers, revision/finalization progress, WebOutputCapture, and job-reporting surfaces without changing legacy route behavior; prove sentinel source/prompt/provider values never reach adaptation output.

## 2. Generator And File-Operation Hygiene

- [x] 2.1 Replace or guard `utils/file_operations.py` root DEBUG setup and direct lock-path `print()` diagnostics so adaptation writes expose no lock paths while legacy safe diagnostics remain available.
- [x] 2.2 Remove or route full initial-concept, prompt, source-context, and response logging from ModuleBuilder, ModuleGenerator, AreaGenerator, location/plot generators, and related adaptation generator paths; preserve bounded stage/count telemetry.
- [x] 2.3 Make monster-builder subprocess and adaptation materialization output safe: no raw AI response or process stdout/stderr is emitted/persisted, while timeout, exit, JSON, schema, and identity failure codes remain visible.

## 3. Diagnostic Redaction And Persistence

- [x] 3.1 Add deterministic bounded redaction for adaptation diagnostic messages, `stdout_tail`, `stderr_tail`, exceptions, provider failures, and failure packets; remove credentials, authorization headers, request/response bodies, raw source/prompts/responses, absolute paths, and lock paths before persistence.
- [x] 3.2 Preserve `raw_provider_payload_exposed=false`, meaningful stage/failure codes, attempt/revision identity, and bounded report/job payload shapes across malformed, refusal, timeout, and early failure paths.

## 4. Provider Logger And Handler Containment

- [x] 4.1 Harden adaptation/provider logger containment for late `openai.*`, `httpx.*`, and `httpcore.*` children and root/application handlers created after client construction; provider-shaped DEBUG records must be suppressed or redacted before output.
- [x] 4.2 Preserve the existing provider-lazy-log-safety factory ordering, request immutability, provider selection, model/timeout/retry/fallback behavior, and fail-open safety setup behavior.

## 5. Regression And Compatibility

- [x] 5.1 Add sentinel regression coverage for stdout/stderr, GUI/progress payloads, persisted tails, lock paths, raw provider payload markers, credentials/tokens, late loggers, and bounded progress/failure visibility.
- [x] 5.2 Run existing provider-log safety, AI-client factory, GPT-5 parameter, adaptation provider-safety, adaptation job-reporting, adaptation failure-diagnostic, and legacy diagnostic suites; verify no non-adaptation diagnostics are accidentally removed.
- [x] 5.3 Run syntax checks, ASCII checks, `git diff --check`, strict OpenSpec validation for this change, and inspect final scope without archiving or committing.
