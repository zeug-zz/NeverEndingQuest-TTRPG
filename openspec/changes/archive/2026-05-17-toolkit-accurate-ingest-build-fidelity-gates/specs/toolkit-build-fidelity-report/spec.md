## ADDED Requirements

### Requirement: Build fidelity report SHALL summarize generated-module source preservation

The toolkit SHALL generate a compact `build_fidelity_report.json` for accurate-ingest builds after packet builder execution and before post-build finishing.

#### Scenario: Passing build fidelity report is persisted

- **GIVEN** an accurate-ingest workspace has source graph, blueprint, and clean/repaired pre-build fidelity artifacts
- **AND** the generated module preserves required source NPCs, locations, plot beats, puzzle rules, clue chains, and source-locked names
- **WHEN** the packet build completes
- **THEN** `build_fidelity_report.json` SHALL be persisted
- **AND** it SHALL include status `pass` or equivalent non-blocking status
- **AND** it SHALL include coverage counts and artifact paths.

#### Scenario: Degraded warning-only report remains non-blocking

- **GIVEN** generated output preserves all critical source atoms
- **AND** only advisory tone/profile divergence is detected
- **WHEN** build fidelity report generation runs
- **THEN** the report SHALL include warnings
- **AND** it SHALL allow the existing finishing flow to continue.

#### Scenario: Malformed accurate-ingest artifact fails closed

- **GIVEN** accurate-ingest evidence exists
- **AND** a required source/blueprint/fidelity artifact is malformed
- **WHEN** build fidelity report generation runs
- **THEN** the report SHALL use status `failed` or `blocked`
- **AND** it SHALL identify the malformed artifact path
- **AND** it SHALL prevent post-build finishing.

### Requirement: Legacy workspaces SHALL not require build fidelity reports

The toolkit SHALL preserve current behavior for legacy workspaces that do not carry accurate-ingest source/blueprint artifacts.

#### Scenario: Legacy build skips source fidelity gate

- **GIVEN** a workspace lacks accurate-ingest source and blueprint artifacts
- **WHEN** packet build completes
- **THEN** build fidelity gates SHALL NOT block finishing
- **AND** existing legacy behavior SHALL remain available.
