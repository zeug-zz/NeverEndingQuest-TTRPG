# toolkit-build-activity-feedback Specification

## Purpose
Provide bounded, phase-aware activity feedback for long-running Module Toolkit builds without changing authoritative job state or exposing raw provider and source output.
## Requirements
### Requirement: In-progress toolkit phases SHALL expose cosmetic activity feedback

When a Module Toolkit job is in a known long-running, non-terminal phase, the GUI SHALL render the authoritative status message together with a bounded activity line appropriate to that phase or phase group.

#### Scenario: Adaptation module build is still running

- **WHEN** an adaptation job reports an in-progress module-build phase
- **THEN** the GUI SHALL keep the authoritative adaptation status visible
- **AND** the GUI SHALL show an activity line describing bounded work such as dossier reading, area generation, reference reconciliation, or module validation
- **AND** the activity line SHALL NOT claim that the module build has completed

#### Scenario: Legacy packet build is still running

- **WHEN** a legacy Homebrew job reports packet building, rebuild preparation, readiness repair, finishing, or publishability work
- **THEN** the GUI SHALL show an activity line for the reported work group
- **AND** the existing status and diagnostics details SHALL remain available

#### Scenario: Direct builder progress is still running

- **WHEN** the direct ModuleBuilder progress channel reports a non-terminal build or publication stage
- **THEN** the GUI SHALL show the same bounded activity-feedback behavior
- **AND** the direct builder SHALL retain its existing progress percentage and stage display

### Requirement: Activity messages SHALL rotate at a bounded cadence

The GUI SHALL display the first activity message immediately when an activity group becomes active and SHALL NOT advance the active group more frequently than once every five seconds.

#### Scenario: Long provider call produces repeated polls

- **WHEN** the same in-progress phase is returned across repeated status polls
- **THEN** the activity line SHALL remain stable for at least five seconds before advancing
- **AND** the status poll SHALL continue to use the existing job-status cadence

#### Scenario: Activity group changes

- **WHEN** the authoritative phase changes to a different activity group
- **THEN** the activity sequence SHALL reset for the new group
- **AND** the first message for the new group SHALL be eligible for immediate display

### Requirement: Terminal and unknown states SHALL fail safely

Activity feedback SHALL be cleared when a job becomes completed, failed, blocked, quarantined, rejected, stopped, or otherwise terminal. Unknown or unmapped in-progress states SHALL use a bounded generic activity message rather than exposing raw status payload content.

#### Scenario: Job reaches a terminal state

- **WHEN** the GUI receives a terminal job outcome
- **THEN** the activity line SHALL be hidden or cleared
- **AND** the terminal status and existing diagnostics SHALL remain visible

#### Scenario: New phase is not yet mapped

- **WHEN** an in-progress job reports an unrecognized phase
- **THEN** the GUI SHALL show a generic bounded activity message
- **AND** it SHALL NOT display raw provider, HTTP, JSON, credential, or source text as a substitute

### Requirement: Activity feedback SHALL preserve status authority and payload privacy

The authoritative backend status, canonical phase, progress fields, terminal state, and bounded diagnostics SHALL remain the sole source of truth for build state. Cosmetic activity messages SHALL NOT alter job state, invoke providers, or expose unbounded payloads.

#### Scenario: Provider response contains descriptive text

- **WHEN** a provider response or debug log contains source-derived descriptive text
- **THEN** the GUI SHALL continue to render only the bounded activity message and existing safe diagnostics
- **AND** the raw provider response SHALL NOT be copied into the activity line

#### Scenario: Activity rendering is unavailable

- **WHEN** the activity element or activity mapping cannot be used
- **THEN** the GUI SHALL continue rendering the existing authoritative status message
- **AND** the job polling and build lifecycle SHALL continue without an activity-rendering error

### Requirement: Activity feedback SHALL remain ASCII-compatible and backward compatible

User-facing activity text and the active status cursor SHALL use ASCII characters only. The status cursor SHALL render as `|`. Existing upload, adaptation, legacy, direct-builder, single-player, and multiplayer behavior SHALL remain compatible.

#### Scenario: Working status is rendered

- **WHEN** a working status message displays its cursor
- **THEN** the cursor SHALL be rendered as `|`
- **AND** the cursor and activity text SHALL contain no non-ASCII characters

#### Scenario: Existing status consumer receives a job payload

- **WHEN** an existing GUI or API consumer receives a toolkit job payload
- **THEN** the existing status, phase, progress, terminal, and diagnostics fields SHALL retain their current meanings
- **AND** activity feedback SHALL remain presentation-only
