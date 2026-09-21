## Why

The Amphail adaptation failure exposed a second boundary defect: adaptation output can contain raw source context, full prompts, provider responses, credentials, authorization headers, lock paths, and unbounded DEBUG records even when the persisted adaptation report says `raw_provider_payload_exposed=false`. Direct lock prints, verbose generators, root DEBUG handlers, diagnostic tails, and provider child loggers created after client construction bypass the intended provider safety policy.

This linked change creates an adaptation-scoped output safety boundary so adaptation stdout, stderr, GUI chat/progress, and persisted diagnostics expose only bounded phase/status/count information and safe failure codes. It must work with `toolkit-adaptation-llm-finalization-ownership` without changing legacy CLI diagnostics outside adaptation.

## What Changes

- Add an adaptation-scoped output guard for stdout, stderr, application/root handlers, GUI progress, and persisted diagnostic tails.
- Allow only bounded ASCII phase/status/count/failure-code progress events during adaptation.
- Suppress or safely redirect verbose ModuleBuilder, ModuleGenerator, AreaGenerator, and provider output; remove full prompt/source/response logging.
- Replace direct file-operation lock `print()` diagnostics with safe categorized logging or bounded adaptation events without exposing lock paths.
- Prevent root/application handlers and late `openai`, `httpx`, and `httpcore` loggers from bypassing provider redaction after lazy client construction or handler creation.
- Redact credentials, authorization markers, request/response payloads, raw source/prompt/provider sentinels, filesystem lock paths, and unbounded exception text before persistence or emission.
- Preserve meaningful bounded failure codes and stage names, deterministic ASCII output, and legacy non-adaptation CLI diagnostics.
- Add sentinel-based regression coverage for stdout/stderr, GUI/progress payloads, persisted tails, root handlers, late provider loggers, and legacy behavior.

## Capabilities

### New Capabilities

- `adaptation-output-safety-boundary`: Defines adaptation-scoped stdout/stderr, GUI, progress, and logger emission rules.
- `adaptation-generator-logging-hygiene`: Defines safe behavior for file operations and verbose builders/generators during adaptation.
- `adaptation-diagnostic-redaction`: Defines bounded redaction and persistence rules for failure packets, tails, and progress diagnostics.
- `adaptation-provider-logger-containment`: Defines late provider logger and handler safety after lazy client construction.
- `adaptation-output-compatibility`: Defines ASCII determinism, meaningful bounded failures, and preservation of legacy non-adaptation diagnostics.

### Modified Capabilities

- None. `toolkit-provider-lazy-log-safety` remains historical source material; this change adds the adaptation output boundary and verifies the existing provider safety behavior under late handler/logger creation.

## Impact

- Likely implementation surfaces include a new adaptation output-safety utility, `web/web_interface.py` output capture/progress handling, `web/extensions/toolkit_adaptation_job_reporting.py`, `utils/file_operations.py`, `core/generators/module_builder.py`, `module_generator.py`, `area_generator.py`, `monster_builder.py`, `utils/provider_log_safety.py`, and `utils/ai_client_factory.py`.
- Adaptation output may be captured or redirected only for the active adaptation scope; ordinary CLI diagnostics outside that scope remain available.
- Persisted diagnostics are bounded and redacted; raw provider payloads remain prohibited even when a provider or application logger is configured after startup.
- No provider request arguments, model routing, timeout, retry, fallback, publication, or gameplay semantics change.
- No new dependency is required. All tests use project-local scratch paths and `.venv/bin/python` where dependencies are involved.
