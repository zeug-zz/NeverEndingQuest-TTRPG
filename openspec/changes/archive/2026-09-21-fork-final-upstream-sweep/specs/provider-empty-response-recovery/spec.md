# Provider Empty Response Recovery

## Purpose

Classify chat completions that contain no usable text as non-success results,
retry them only within a bounded limit, fall back through existing provider
policy, and never persist an empty narration or action artifact.

## ADDED Requirements

### Requirement: Empty completions are classified as non-success

A chat completion SHALL be classified as an empty transient result when the
response contains no choices, the selected choice has no usable message, or the
message content is blank/whitespace-only where the caller requires text.

#### Scenario: Response has no choices

- **WHEN** a provider response contains an empty `choices` collection
- **THEN** the response SHALL be classified as empty transient
- **AND** it SHALL NOT be returned as a successful completion

#### Scenario: Message content is blank

- **WHEN** the selected choice message exists but its content is `None` or
  whitespace-only
- **THEN** the response SHALL be classified as empty transient
- **AND** it SHALL NOT be treated as valid narration or action output

#### Scenario: Usable content

- **WHEN** the selected choice contains non-blank text
- **THEN** the response SHALL be classified as usable and returned unchanged

### Requirement: Empty transient completions retry within a bounded limit

The recovery helper SHALL retry an empty transient completion no more than the
configured bounded limit and SHALL forward identical resolved request
parameters, messages, and timeout on every attempt.

#### Scenario: Empty then valid

- **WHEN** the first attempt returns an empty transient completion and a later
  attempt returns usable text
- **THEN** the usable response SHALL be returned
- **AND** the number of attempts SHALL NOT exceed the bounded limit plus one

#### Scenario: Empty through the retry bound

- **WHEN** every attempt within the bounded limit returns an empty transient
  completion
- **THEN** the helper SHALL raise a fork-native `EmptyProviderResponseError`
- **AND** the exception message SHALL be ASCII-only and SHALL NOT contain raw
  provider payloads, prompts, or credentials

#### Scenario: Request parameters are preserved

- **WHEN** the helper retries an empty transient completion
- **THEN** every retry SHALL use the same model, reasoning/verbosity settings,
  messages, and timeout as the original attempt

### Requirement: Existing provider fallback behavior is reused

`EmptyProviderResponseError` SHALL be classified as retryable by the shared
provider error policy so existing call-site fallback blocks trigger exactly as
they do for retryable provider exceptions. Fallback requests issued through the
helper SHALL be subject to the same bounded recovery.

#### Scenario: Fallback after primary exhaustion

- **WHEN** the primary provider exhausts the bounded empty-response retry and
  the provider error policy permits fallback
- **THEN** the existing fallback path SHALL be used
- **AND** the fallback request SHALL use the same bounded recovery

#### Scenario: Terminal empty after fallback

- **WHEN** the fallback attempt also returns an empty transient completion
  through the bounded limit
- **THEN** the helper SHALL raise `EmptyProviderResponseError` again
- **AND** no successful completion SHALL be fabricated

### Requirement: No false success artifacts from empty completions

An empty transient completion MUST NOT produce empty narration, an empty action
envelope, or a persisted empty assistant turn.

#### Scenario: Narrator turn path

- **WHEN** the narrator response path receives a terminal empty completion
- **THEN** blank content SHALL NOT be assigned to the response content variable
- **AND** a deterministic fork-native error SHALL surface instead
- **AND** no assistant turn SHALL be appended to conversation history for the
  failed completion

### Requirement: Request shape and routing contracts are unchanged

The recovery helper SHALL NOT mutate model configuration, parameter resolution,
or provider selection, and SHALL preserve existing single-player and TABLETOP
MODE narrator routing.

#### Scenario: GPT-5.6 Luna parameters

- **WHEN** the narrator path issues a GPT-5-family request through the helper
- **THEN** reasoning effort and verbosity parameters SHALL be identical to the
  pre-change request
- **AND** legacy sampling parameters SHALL remain omitted

#### Scenario: OpenRouter request shape

- **WHEN** the active provider is OpenRouter
- **THEN** the request shape SHALL remain unchanged
- **AND** existing OpenRouter request-shape tests SHALL remain green

#### Scenario: SP and MP routing

- **WHEN** the game runs in single-player or TABLETOP MODE
- **THEN** the narrator call path and provider selection SHALL remain
  functionally unchanged
