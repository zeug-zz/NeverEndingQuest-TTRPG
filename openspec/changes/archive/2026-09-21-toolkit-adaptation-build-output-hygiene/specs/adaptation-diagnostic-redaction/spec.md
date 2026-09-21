## Purpose

Define the safe bounded projection used for adaptation failure diagnostics, stdout/stderr tails, progress messages, and persisted attempt reports.

## ADDED Requirements

### Requirement: Diagnostic tails are redacted and bounded

Any persisted adaptation `stdout_tail`, `stderr_tail`, exception diagnostic, or provider diagnostic MUST be a bounded redacted projection containing only safe stage/code/context fields and MUST not be a raw tail.

#### Scenario: Raw tail contains sensitive markers

- **WHEN** a tail contains source text, a full prompt, a provider response, an authorization header, a credential/token, a request body, or an absolute path
- **THEN** the persisted projection MUST omit or replace each sensitive value
- **AND** its size MUST remain within the adaptation diagnostic bound

### Requirement: Provider payload exposure remains false

Adaptation report and job payload fields MUST continue to report `raw_provider_payload_exposed=false` after redaction, including on malformed, timeout, refusal, and subprocess failure paths.

#### Scenario: Provider failure

- **WHEN** the provider or generator fails with a payload-bearing exception
- **THEN** the report MUST contain a bounded provider failure code
- **AND** it MUST not contain request/response bodies, headers, credentials, or raw exception payloads

### Requirement: Redaction is deterministic and ASCII-safe

Equivalent diagnostic inputs MUST produce deterministic bounded projections, and all new user-facing adaptation diagnostic text MUST be ASCII-compatible.

#### Scenario: Repeated failure projection

- **WHEN** the same failure is projected twice
- **THEN** the safe fields and redaction markers MUST be stable
- **AND** no Unicode or unbounded source text may be introduced
