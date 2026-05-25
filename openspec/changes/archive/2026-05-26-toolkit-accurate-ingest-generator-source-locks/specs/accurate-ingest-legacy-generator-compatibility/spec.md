## ADDED Requirements

### Requirement: Legacy Generator Compatibility

Generator source-lock changes SHALL preserve existing ModuleBuilder behavior for non-source concept builds and explicit seed writer support modes.

#### Scenario: Concept build remains functional

- **GIVEN** a Describe-your-Adventure or non-source concept build
- **WHEN** ModuleBuilder and sub-generators run
- **THEN** they SHALL not require `source_npc_names`, `source_location_names`, `source_monster_refs`, `source_encounter_seeds`, or other source-specific fields.

#### Scenario: Explicit seed writer support mode remains explicit

- **GIVEN** an accurate-ingest packet build with explicit `seed_writer_mode`
- **WHEN** the packet builder routes the request
- **THEN** seed writer routing SHALL remain explicit
- **AND** generator source-lock changes SHALL NOT silently route explicit seed writer support requests into ModuleBuilder.

### Requirement: Provider-Free Regression Coverage

Source-lock contract tests SHALL be deterministic and provider-free.

#### Scenario: Tests do not call LLM providers

- **GIVEN** source-lock regression tests
- **WHEN** the test suite runs
- **THEN** tests SHALL patch or inspect prompt/context assembly
- **AND** tests SHALL NOT require OpenAI, OpenRouter, or other live provider calls.
