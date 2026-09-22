# combat-latency-smoke-fixtures Specification

## Purpose
Define fixed, repeatable smoke fixtures for the Phase 0 combat latency baseline.
The fixtures exercise both the multi-PC product path and the 1-PC party path
without changing production combat rules or provider behavior.

## Requirements

### Requirement: The MP fixture SHALL be fixed at four PCs, three rounds, and one enemy batch

The multi-PC latency fixture SHALL use four player characters, execute three
combat rounds, and include one enemy batch. Its actor roster, round count,
phase sequence, and command sequence SHALL be fixed and documented in the
fixture contract.

#### Scenario: MP baseline fixture runs

- **WHEN** the MP fixture is executed with tracing enabled
- **THEN** it SHALL exercise four PC action windows across three rounds
- **AND** it SHALL exercise one enemy-batch window
- **AND** it SHALL emit trace data sufficient to report stages, provider sites,
  compression, file operations, fast-path outcomes, and decisions

### Requirement: The MP fixture SHALL exercise TABLETOP MODE compliance boundaries

The MP fixture SHALL cover the existing initiative/phase gate, roster
integrity, legal PC actor handling, enemy-batch processing, and turn/round
boundaries relevant to latency measurement. The fixture SHALL not introduce
new mechanics or bypass existing combat guards.

#### Scenario: MP compliance remains intact

- **WHEN** the MP fixture completes
- **THEN** initiative and phase markers SHALL remain coherent
- **AND** all four PCs SHALL remain represented without duplicate roster entries
- **AND** the enemy batch SHALL use the existing combat path

### Requirement: The 1-PC party fixture SHALL be fixed at one combat round

The 1-PC party latency fixture SHALL execute one combat round through the
minimum-party tabletop path (ADR-0032). It SHALL be independent of the MP-only
roster setup and SHALL exercise the same observational trace gate.

#### Scenario: 1-PC party baseline fixture runs

- **WHEN** the 1-PC party fixture is executed with tracing enabled
- **THEN** it SHALL complete one combat round
- **AND** it SHALL emit reportable stage and provider-site trace data
- **AND** it SHALL preserve 1-PC party behavior and state authority

### Requirement: Fixtures SHALL support disabled-path verification

Each fixture SHALL be runnable with tracing disabled. The disabled run SHALL
perform zero trace writes and SHALL use the same combat actions and prompts as
the enabled run.

#### Scenario: Disabled fixture run

- **WHEN** either fixed fixture runs with the default trace gate OFF
- **THEN** no trace file SHALL be created or appended
- **AND** the combat result and provider-call behavior SHALL remain unchanged

### Requirement: Fixture failures SHALL identify the failed boundary

Fixture tests SHALL fail with bounded diagnostics that identify the fixture,
round or stage, and violated invariant. Fixture failure handling SHALL NOT add
provider calls or mutate production game state for reporting purposes.

#### Scenario: Fixture invariant fails

- **WHEN** a fixed fixture does not reach its required round, batch, or mode
- **THEN** the verification output SHALL identify the failed fixture contract
- **AND** the report path SHALL remain provider-free

### Requirement: Reusable Scripted Capture Ensemble

The change SHALL provide a reusable scripted capture ensemble for the live
baseline: a lean sandbox copy under `tmp/`, a dedicated `Capture_Arena` capture
module, and scripted capture scenarios (socket-driven driver primary;
`playwright-cli` documented as the browser alternative) that capture 4-PC and
1-PC traces and tear down cleanly. The ensemble SHALL be test tooling and SHALL
NOT change product runtime behavior.

#### Scenario: Sandbox isolation

- **WHEN** the ensemble prepares or runs a capture
- **THEN** the installed tree SHALL remain unchanged
- **AND** all sandbox runtime state SHALL live under `tmp/`

#### Scenario: Capture module role

- **WHEN** a capture scenario needs an arena with walkable locations, combat
  hostiles, and NPC or feature objects
- **THEN** it SHALL use the dedicated `Capture_Arena` module
- **AND** no gameplay state from another installed module SHALL be required

#### Scenario: Scripted 4-PC and 1-PC captures

- **WHEN** the 4-PC and 1-PC scenarios are executed through scripted capture
  scenarios (socket-driven driver primary; `playwright-cli` documented as the
  browser alternative)
- **THEN** each scenario SHALL produce a trace usable by
  `scripts/combat_latency_report.py`

#### Scenario: Trace capture and teardown

- **WHEN** a capture completes or fails
- **THEN** the trace SHALL be preserved to a local path under `tmp/`
- **AND** the ensemble SHALL stop the sandbox server and restore sandbox state

#### Scenario: Documented reuse

- **WHEN** a future narration or other gameplay capture is needed
- **THEN** the documented skill and checklist SHALL provide the start/stop
  commands, selectors, and extension points to run it without new test
  infrastructure
