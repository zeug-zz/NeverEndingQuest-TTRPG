# provider-lazy-log-safety Specification

## Purpose
Protect provider transport diagnostics when SDK child loggers are created after initial application logging setup.

## Requirements

### Requirement: Shared Factory Reapplies Provider Safety

The shared chat-client factory MUST apply the provider-log safety policy before construction and again after the provider client constructor returns. Primary and fallback client creation MUST use the same boundary.

#### Scenario: Primary client creates lazy transport loggers

- **WHEN** a shared factory call constructs a primary OpenAI or OpenRouter client
- **AND** the SDK creates provider child loggers during construction
- **THEN** the returned client MUST have completed post-construction provider-log safety configuration
- **AND** provider child loggers MUST NOT emit DEBUG payload records by default.

### Requirement: Late Provider Records Are Safe

Provider-shaped records from `openai.*`, `httpx.*`, and `httpcore.*` MUST be suppressed at DEBUG or sanitized before application-owned handlers format them.

#### Scenario: Late request record contains source and credentials

- **WHEN** a late provider child logger emits a request-shaped record containing messages, JSON data, headers, authorization, or response fields
- **THEN** captured output MUST contain neither the sentinel source text nor credential or payload values
- **AND** bounded safe diagnostics remain available where explicitly emitted.

### Requirement: Provider Behavior Is Unchanged

The safety boundary MUST NOT alter provider request arguments, models, timeout values, retry behavior, fallback routing, or client return values.

#### Scenario: Existing factory contract executes

- **WHEN** existing factory and GPT-5 parameter contract tests run with fake clients
- **THEN** all prior provider-selection and request-shape assertions MUST remain valid.

### Requirement: Safety Failure Is Fail-Open

An internal logging-policy exception MUST NOT prevent provider client creation or change the existing fallback/error classification.

#### Scenario: Safety setup raises

- **WHEN** a safety configuration call raises an internal exception
- **THEN** the factory MUST continue through the existing client path
- **AND** only a bounded local diagnostic may be emitted.
