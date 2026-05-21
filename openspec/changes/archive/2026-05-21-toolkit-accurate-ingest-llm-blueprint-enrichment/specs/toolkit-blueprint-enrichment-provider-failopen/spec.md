## ADDED Requirements

### Requirement: Provider failures SHALL fail open without corrupting artifacts

Blueprint enrichment SHALL treat provider timeouts, quota errors, API errors, invalid responses, and parser exceptions as degraded or failed enrichment outcomes, not as reasons to corrupt or partially overwrite unrelated artifacts.

#### Scenario: Provider timeout degrades safely

- **GIVEN** blueprint enrichment is enabled
- **AND** a provider call times out
- **WHEN** the enrichment pass returns
- **THEN** the pipeline SHALL report degraded or failed status with diagnostics
- **AND** previously valid blueprint/module artifacts SHALL remain uncorrupted.

#### Scenario: Provider quota or API error degrades safely

- **GIVEN** the provider returns quota, authentication, rate-limit, or server error
- **WHEN** the enrichment pass catches the error
- **THEN** the pipeline SHALL report degraded or failed status with provider diagnostics safe for logs
- **AND** no invalid patches SHALL be applied.

#### Scenario: Tests do not require live provider calls by default

- **WHEN** targeted enrichment tests run in default local or CI mode
- **THEN** tests SHALL use mocks, fixtures, or cached response payloads
- **AND** live provider calls SHALL only run when explicitly enabled by test configuration.

### Requirement: Provider smoke SHALL be optional and isolated

Provider-backed smoke verification MAY exist, but it SHALL be opt-in and SHALL NOT be required for normal regression gates.

#### Scenario: Provider smoke is disabled by default

- **GIVEN** no explicit provider smoke flag or environment configuration is present
- **WHEN** test suites run
- **THEN** provider smoke tests SHALL skip or remain inactive
- **AND** deterministic fixture tests SHALL still verify parser, validation, and fail-open behavior.
