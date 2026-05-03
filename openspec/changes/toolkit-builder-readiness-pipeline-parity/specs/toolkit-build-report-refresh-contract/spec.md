## ADDED Requirements

### Requirement: Legacy builder reports SHALL declare readiness freshness
Toolkit reports created or refreshed by legacy builder workflows SHALL include freshness metadata that distinguishes raw-generation, readiness, finishing, and final publishability phases.

#### Scenario: Readiness starts after raw generation
- **WHEN** raw legacy builder generation succeeds and readiness begins
- **THEN** any persisted report marker SHALL indicate that final publishability is not yet current
- **AND** sidebar consumers SHALL not treat a previous final report as authoritative for the newly generated module state.

#### Scenario: Readiness failure writes non-current or failed report state
- **WHEN** readiness convergence fails for a legacy builder run
- **THEN** the persisted report or readiness artifact SHALL identify readiness failure
- **AND** it SHALL not leave a stale previous `publishable_status: "pass"` report looking current.

#### Scenario: Final finishing refreshes report through shared contract
- **WHEN** readiness passes and final finishing completes for a legacy builder run
- **THEN** `modules/<slug>/toolkit_build_report.json` SHALL be rewritten through the shared refresh/report contract
- **AND** the report SHALL include current readiness and publishability outcomes.

### Requirement: Report refresh SHALL remain explicit and non-rendering
Legacy builder integration SHALL preserve the rule that report freshness changes happen in build/remediation workflows, not during sidebar rendering.

#### Scenario: Sidebar remains read-only
- **WHEN** the Module Builder sidebar renders the module list
- **THEN** it SHALL read persisted report state only
- **AND** it SHALL NOT invoke readiness, publishability, semantic, gameplay, or repair audits during rendering.

#### Scenario: Builder workflow refreshes before sidebar truth changes
- **WHEN** a legacy builder run changes module files
- **THEN** the build workflow SHALL explicitly refresh or invalidate report freshness before the sidebar can present the new state as authoritative.
