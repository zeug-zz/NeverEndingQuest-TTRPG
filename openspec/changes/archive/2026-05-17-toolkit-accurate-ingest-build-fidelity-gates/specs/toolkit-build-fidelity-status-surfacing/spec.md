## ADDED Requirements

### Requirement: Toolkit status payloads SHALL expose compact build fidelity status

The toolkit SHALL expose build fidelity outcomes through existing job/review/status payloads without redesigning the upload UI.

#### Scenario: Blocked build exposes report details

- **GIVEN** build fidelity gate blocks an accurate-ingest build
- **WHEN** the toolkit UI polls job status or loads review/status payloads
- **THEN** payloads SHALL include compact build fidelity status
- **AND** payloads SHALL include report artifact paths
- **AND** payloads SHALL include blocker summary text safe for display.

#### Scenario: Passing build exposes report path

- **GIVEN** build fidelity passes
- **WHEN** packet builder returns a build result
- **THEN** the result SHALL include compact build fidelity status and report path
- **AND** it SHALL not interrupt existing successful build status rendering.

### Requirement: Status surfacing SHALL preserve legacy UI behavior

The build fidelity status addition SHALL be additive and SHALL NOT break legacy upload or module builder UI behavior.

#### Scenario: Legacy status omits build fidelity section

- **GIVEN** a legacy workspace has no build fidelity payload
- **WHEN** the toolkit UI renders upload status
- **THEN** existing status rendering SHALL continue without requiring build fidelity fields.
