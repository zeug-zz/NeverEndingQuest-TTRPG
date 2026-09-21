## Why

The Amphail replay correctly reported `raw_provider_payload_exposed: false` in its persisted job envelope, but stdout still contained OpenAI and httpcore debug records with complete prompts, source-derived module context, request JSON, transport details, and security metadata. The records were emitted because repository logging config enables the root logger at DEBUG; the existing enhanced-logger message filters do not govern third-party logger propagation.

This is a separate security and observability defect. Provider calls succeeded, but debug logging can expose user-authored source material and request metadata in console captures or debug logs. It must be fixed without changing provider requests, fallback behavior, or the adaptation failure contract.

## What Changes

- Add an idempotent provider-log safety policy for OpenAI, httpx, and httpcore loggers.
- Suppress third-party request/response payload logging by default, including when application debug categories are enabled.
- Redact sensitive request fields and prompt-bearing fields if a provider record reaches an application handler.
- Preserve bounded application diagnostics such as provider, model, stage, status, duration, and safe request identifiers.
- Integrate the policy at the shared client-factory boundary used by adaptation and toolkit generation.
- Add provider-free tests proving prompts, source context, headers, credentials, and request JSON do not reach console/debug output.

## Non-Goals

- Do not change provider request payloads, models, timeouts, retry policy, or fallback routing.
- Do not expose or persist raw provider responses as a debugging feature.
- Do not remove useful application-level adaptation failure diagnostics.
- Do not rotate credentials or modify local configuration secrets in this slice.
- Do not redesign the logging system or change legacy gameplay semantics beyond third-party provider transport logging.

## Impact And Compatibility

The change affects process-global logging configuration and the shared client factory, so it applies consistently to toolkit/adaptation provider calls while preserving normal application logs and provider error handling. Legacy callers using the factory remain compatible; direct non-factory provider integrations are outside this slice unless they use the shared safety initializer.

## Risks And Rollback

The main risk is suppressing provider diagnostics needed to diagnose outages. Mitigation: retain warning/error records and emit bounded safe metadata through the application logger. The policy is idempotent and can be disabled or reverted without changing provider behavior.
