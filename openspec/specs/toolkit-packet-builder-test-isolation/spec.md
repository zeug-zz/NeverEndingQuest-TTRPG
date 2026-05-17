## Purpose

Isolate packet builder handoff tests from real `ModuleBuilder` and provider execution so regression runs never trigger OpenAI/OpenRouter calls or image generation.

## Requirements

### Requirement: Packet builder tests SHALL not invoke real builder execution

Unit and contract tests for packet-builder handoff SHALL isolate executor behavior so they cannot invoke real `ModuleBuilder.build_module(...)` or provider-backed generation.

#### Scenario: Success tests use injected executor

- **GIVEN** a packet-builder test expects successful execution
- **WHEN** it calls `run_toolkit_homebrew_packet_build(...)`
- **THEN** it SHALL pass an injected mock executor
- **AND** the mock executor SHALL capture or validate `builder_input.json` without calling real builder code.

#### Scenario: Fail-closed tests prove executor is not called

- **GIVEN** a packet-builder test covers blocked or missing required blueprint handoff
- **WHEN** it calls `run_toolkit_homebrew_packet_build(...)`
- **THEN** the test SHALL assert no executor invocation occurs
- **AND** a raising/no-call executor MAY be used as a guard.

#### Scenario: Test suite prevents accidental provider traffic

- **GIVEN** packet-builder handoff tests run as part of regression verification
- **WHEN** the tests complete
- **THEN** no real `ModuleBuilder` execution, OpenAI call, OpenRouter call, image generation, or provider-backed content generation SHALL be triggered.
