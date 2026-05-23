## ADDED Requirements

### Requirement: Numillian production rebuild SHALL follow pipeline fixes

After all pipeline-level fixes are applied, the production Numillian rebuild SHALL be run and its output MUST be verified before publication.

#### Scenario: Rebuild from source succeeds

- **GIVEN** pipeline fixes are applied
- **WHEN** `scripts/rebuild_numillian_accurate_ingest.py --json` runs
- **THEN** the result SHALL include `"status": "success"` or `"status": "degraded"`
- **AND** SHALL NOT return `"status": "failed"`.

#### Scenario: Benchmark passes

- **GIVEN** the rebuild has completed
- **WHEN** `scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json` runs
- **THEN** the report SHALL show `"passed": true`
- **AND** `"source_fidelity_status"` SHALL be `"pass"` or `"degraded"` with explicit reason
- **AND** SHALL NOT be `"blocked"`.

### Requirement: Validation and publishability SHALL pass

The rebuilt module SHALL pass schema validation and publishability gates.

#### Scenario: Schema validation passes

- **GIVEN** the rebuilt module exists
- **WHEN** `core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian` runs
- **THEN** the exit code SHALL be 0
- **AND** 100% of module files SHALL pass validation.

#### Scenario: Publishability audit passes or reports explicit blockers

- **GIVEN** the rebuilt module exists
- **WHEN** `scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json` runs
- **THEN** `ready_status` SHALL be `"pass"`
- **AND** `publishable_status` SHALL be `"pass"` or explicitly state the remaining blocker reason.

### Requirement: Publication readiness SHALL be reassessed before commit

The dirty file list SHALL be reviewed after the rebuild to determine whether source-fidelity is no longer blocked and which files can be committed.

#### Scenario: Dirty file count is reported

- **GIVEN** the rebuild has completed
- **WHEN** `git status -- modules/The_Hidden_City_of_Numillian/` is checked
- **THEN** the dirty/untracked file count SHALL be reported
- **AND** no runtime files (`module_plot.json`, `party_tracker.json`, `encounters/`, `areas/*.json` except BU) SHALL be among the canonical artifacts.

#### Scenario: Commit is not automatic

- **GIVEN** the rebuild and reassessment are complete
- **WHEN** source_fidelity_status is no longer blocked
- **THEN** no commit, push, or PR SHALL be created without explicit user request.
