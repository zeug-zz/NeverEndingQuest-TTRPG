# toolkit-blueprint-seed-failure-semantics Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-seed-writer-completion. Update Purpose after archive.
## Requirements
### Requirement: Seed writer SHALL not report success when required writes fail

The blueprint seed writer SHALL classify required artifact writes and SHALL NOT return `seed_status: success` when any required canonical seed artifact fails to write.

#### Scenario: Required write failure blocks seed success

- **GIVEN** a ready blueprint v2 artifact
- **AND** a required canonical artifact cannot be written
- **WHEN** the seed writer runs
- **THEN** the result SHALL NOT have `seed_status: success`
- **AND** the result SHALL include a blocker identifying the failed required artifact.

#### Scenario: Optional write failure degrades seed result

- **GIVEN** a ready blueprint v2 artifact
- **AND** an optional artifact cannot be written
- **WHEN** the seed writer runs
- **THEN** the result MAY be degraded instead of failed
- **AND** the result SHALL include a warning identifying the optional artifact.

### Requirement: Seed writer SHALL preserve refusal behavior

The blueprint seed writer SHALL continue to fail closed for blocked, failed, invalid, stale, or non-v2 blueprints, and SHALL refuse existing module directories unless overwrite is explicitly allowed by the caller.

#### Scenario: Blocked blueprint refuses writes

- **GIVEN** a blueprint has `blueprint_status: "blocked"`
- **WHEN** the seed writer runs
- **THEN** it SHALL refuse materialization
- **AND** it SHALL NOT write module files.

#### Scenario: Existing module refused without overwrite

- **GIVEN** the target module directory already exists
- **WHEN** the seed writer runs with `overwrite=False`
- **THEN** it SHALL refuse materialization
- **AND** it SHALL return a blocker for caller-level overwrite confirmation handling.

