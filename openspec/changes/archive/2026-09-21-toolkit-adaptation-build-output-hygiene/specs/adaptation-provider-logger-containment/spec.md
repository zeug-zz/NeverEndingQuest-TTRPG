## Purpose

Contain provider and application logger output after lazy SDK logger creation and late root/application handler installation.

## ADDED Requirements

### Requirement: Late provider loggers remain safe

After shared provider client construction, newly created `openai.*`, `httpx.*`, and `httpcore.*` logger children MUST be configured at WARNING-or-safer or sanitized before records reach adaptation handlers.

#### Scenario: Late request record

- **WHEN** a late provider logger emits a DEBUG record containing prompt/source text, JSON payload, headers, authorization, response body, or request ID
- **THEN** adaptation output and persisted diagnostics MUST contain none of those values
- **AND** the provider client request arguments and return value MUST remain unchanged

### Requirement: Late handlers cannot bypass redaction

Root/application handlers created after initial provider safety setup MUST not bypass the adaptation output boundary or provider redaction filter.

#### Scenario: Handler installed after factory call

- **WHEN** a root or application handler is installed after provider client construction and receives a provider-shaped record
- **THEN** the record MUST be suppressed or safely redacted before emission
- **AND** bounded adaptation failure/status events MUST still be available

### Requirement: Safety failure is fail-open for client behavior

An internal logging-safety setup error MUST not change provider selection, request parameters, timeout/retry/fallback behavior, or prevent the existing client path from returning its result.

#### Scenario: Safety configuration exception

- **WHEN** a logging safety call raises during adaptation setup
- **THEN** client construction and existing failure classification MUST continue
- **AND** only a bounded local safety diagnostic may be emitted
