# provider-debug-log-redaction Specification

## Purpose
Prevent third-party provider SDK debug logging from exposing prompts, source content, credentials, request bodies, or raw responses while preserving bounded application diagnostics and provider error handling.

## Requirements

### Requirement: Provider Transport Logs Are Safe By Default

The runtime MUST configure OpenAI, httpx, and httpcore logger paths so DEBUG-level request and response payload records do not reach console, stderr, GUI capture, or application debug files by default.

#### Scenario: OpenAI request debug record is emitted

- **WHEN** a provider SDK emits a DEBUG record containing `messages`, `json_data`, request headers, or transport security metadata
- **THEN** the record MUST be suppressed or sanitized before an application-owned handler formats it
- **AND** sentinel prompt/source text MUST NOT appear in the resulting output

#### Scenario: Debug categories are enabled

- **WHEN** application debug categories or verbose tabletop debugging are enabled
- **THEN** provider payload safety MUST remain enforced
- **AND** application-owned bounded diagnostics MAY remain visible

### Requirement: Sensitive Fields Are Redacted In Defense Depth

If a provider-shaped record reaches a configured application handler, the logging policy MUST remove or redact authorization values, API keys, bearer data, request bodies, prompt-bearing fields, and raw response bodies. Redaction MUST be applied without mutating the provider request object sent to the SDK.

#### Scenario: Request-shaped record reaches a child logger handler

- **WHEN** a child logger record contains a serialized request with `messages`, `json_data`, `api_key`, or authorization fields
- **THEN** the handler output MUST contain no sentinel prompt, source excerpt, credential, or raw request body
- **AND** the record MAY retain a bounded event marker and safe stage/provider metadata

### Requirement: Shared Client Creation Applies The Policy

The shared AI client factory MUST apply the provider logging safety policy before creating primary or fallback clients. Repeated client creation MUST NOT install duplicate filters or handlers.

#### Scenario: Primary provider falls back

- **WHEN** the factory creates a fallback client after a provider error
- **THEN** the same logging safety policy MUST remain active
- **AND** existing fallback routing and user-visible provider error behavior MUST remain unchanged

### Requirement: Safe Diagnostics Preserve Operational Visibility

The system MAY log provider, model, logical stage, status, elapsed time, retry/fallback decision, and safe request identifiers. It MUST NOT log full prompts, source packets, serialized request JSON, response bodies, credentials, or arbitrary exception payloads containing those values.

#### Scenario: Provider request succeeds

- **WHEN** a toolkit or adaptation provider call succeeds
- **THEN** any emitted diagnostic MUST be bounded operational metadata only
- **AND** the raw provider payload exposure flag in adaptation reporting MUST remain false

### Requirement: Provider Calls Continue If Logging Safety Degrades

A failure inside logging-policy initialization MUST NOT change provider request behavior or block gameplay/toolkit execution. The failure MAY produce a bounded internal warning that contains no provider payload.

#### Scenario: Logging configuration raises an internal exception

- **WHEN** the safety helper cannot configure a logger or handler
- **THEN** client creation and existing provider fallback behavior MUST continue
- **AND** no raw provider payload MAY be emitted as a recovery diagnostic

### Requirement: Non-Provider And Legacy Logging Remains Compatible

The provider logging policy MUST NOT change application logger category semantics or non-adaptation provider request contracts beyond suppressing unsafe third-party payload records.

#### Scenario: Legacy factory caller executes

- **WHEN** a legacy or single-player caller creates a provider client through the shared factory
- **THEN** the client and request configuration MUST remain compatible
- **AND** only unsafe third-party payload logging behavior changes
