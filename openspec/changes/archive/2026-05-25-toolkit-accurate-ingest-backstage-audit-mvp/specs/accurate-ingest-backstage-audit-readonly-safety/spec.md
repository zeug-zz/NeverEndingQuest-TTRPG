## ADDED Requirements

### Requirement: Auditor SHALL be read-only for module and source artifacts

The accurate-ingest backstage auditor SHALL NOT mutate module artifacts, source artifacts, benchmark fixtures, waivers, or gate scripts.

#### Scenario: Module files are unchanged after audit

- **GIVEN** a module directory with files before an audit run
- **WHEN** the auditor runs
- **THEN** the content hashes of module files SHALL remain unchanged
- **AND** no module report file SHALL be refreshed in place by the auditor.

#### Scenario: Auditor does not create waivers

- **GIVEN** source-fidelity or publishability blockers exist
- **WHEN** the auditor runs
- **THEN** it SHALL NOT create, modify, or apply waiver files
- **AND** it SHALL only recommend waiver review as a human decision when appropriate.

#### Scenario: Auditor does not enter generation loop

- **GIVEN** an accurate-ingest module audit
- **WHEN** the auditor runs
- **THEN** it SHALL NOT call ModuleBuilder
- **AND** it SHALL NOT call seed writer
- **AND** it SHALL NOT run media generation, module finishing, or publication mutation flows.

### Requirement: Runtime audit outputs SHALL be isolated

The auditor MAY write its own run artifacts, but those artifacts SHALL be isolated from module source/publishability artifacts.

#### Scenario: Audit artifacts use runtime output directory

- **GIVEN** an audit run with output enabled
- **WHEN** run artifacts are written
- **THEN** they SHALL be written outside the module directory by default
- **AND** generated runtime audit artifacts SHALL be ignored by git unless explicitly promoted as fixtures or docs.
