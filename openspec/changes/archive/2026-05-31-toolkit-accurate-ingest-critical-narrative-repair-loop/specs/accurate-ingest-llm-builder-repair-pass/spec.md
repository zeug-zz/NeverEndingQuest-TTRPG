## ADDED Requirements

### Requirement: Builder Repair Pass Consumes Repair Brief

The repair pass SHALL provide the repair brief and source excerpts to the LLM Builder or ModuleBuilder repair entrypoint.

#### Scenario: Repair pass runs for Numillian
- **GIVEN** a repair brief identifies Kobe and `skull_riddle`
- **WHEN** the LLM Builder repair pass runs
- **THEN** it SHALL use the brief as source-lock context
- **AND** it SHALL update module artifacts through source-faithful narrative synthesis.

### Requirement: Provider Failure Fails Closed

The Builder repair pass SHALL fail closed if provider calls fail or are unavailable.

#### Scenario: Provider unavailable
- **GIVEN** the repair pass requires an LLM Builder call
- **WHEN** the provider call fails due to quota, auth, timeout, or transport error
- **THEN** the repair pass SHALL not mutate module artifacts as if repair succeeded
- **AND** it SHALL report actionable provider diagnostics.

### Requirement: Invalid Repair Output Fails Closed

The Builder repair pass SHALL not accept invalid or regressive output.

#### Scenario: Builder output is invalid
- **GIVEN** Builder repair returns malformed JSON or removes passing source-fidelity content
- **WHEN** repair validation runs
- **THEN** the repair SHALL fail
- **AND** final reports SHALL preserve the blocker status.

## SHOULD Guidance

Prefer reusing existing ModuleBuilder source-lock and builder_input paths rather than adding a separate one-off LLM pathway.
