## ADDED Requirements

### Requirement: Blueprint enrichment SHALL report truthful execution status

The blueprint enrichment pipeline SHALL report whether enrichment was skipped, unavailable, degraded, failed, or complete without overstating no-op behavior as successful enrichment.

#### Scenario: Disabled enrichment is skipped

- **GIVEN** `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT` is false
- **WHEN** blueprint enrichment runs
- **THEN** the pipeline result SHALL have status `skipped`
- **AND** the reason SHALL explain that the feature flag is disabled
- **AND** no patches SHALL be applied.

#### Scenario: Enabled no-provider enrichment is not implemented

- **GIVEN** `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT` is true
- **AND** provider-backed pass orchestration is unavailable or placeholder-only
- **WHEN** blueprint enrichment runs and applies no real patches
- **THEN** the pipeline result SHALL NOT have status `complete`
- **AND** the result SHALL have status `not_implemented` or an equivalent degraded unavailable status
- **AND** the reason or warnings SHALL identify provider orchestration as unavailable.

#### Scenario: Pass exception degrades status

- **GIVEN** blueprint enrichment is enabled
- **AND** one or more enrichment passes raise an exception
- **WHEN** the pipeline returns
- **THEN** the result SHALL have status `degraded` or `failed`
- **AND** the result SHALL include pass-level warning or error diagnostics
- **AND** previously valid blueprint/module artifacts SHALL NOT be corrupted.

#### Scenario: Pass errors degrade status

- **GIVEN** blueprint enrichment is enabled
- **AND** one or more pass results include errors
- **WHEN** the pipeline returns
- **THEN** the result SHALL have status `degraded` or `failed`
- **AND** the result SHALL expose the errors in reportable form.

#### Scenario: Complete requires applied patch and no failures

- **GIVEN** blueprint enrichment is enabled
- **AND** at least one validated patch is applied
- **AND** no patches are rejected
- **AND** no pass errors or exceptions occur
- **WHEN** the pipeline returns
- **THEN** the result MAY have status `complete`.

### Requirement: Blueprint enrichment SHALL reject structural mutation patches

Blueprint enrichment SHALL only mutate approved text/prose fields and SHALL reject patches that attempt structural changes.

#### Scenario: Structural mutation patch is rejected

- **GIVEN** an enrichment patch attempts to modify names, IDs, coordinates, connectivity, dependencies, puzzle rules, solutions, or failure consequences
- **WHEN** patch validation runs
- **THEN** the patch SHALL be rejected
- **AND** rejection SHALL include a diagnostic reason
- **AND** the target file SHALL NOT be mutated by that rejected patch.

#### Scenario: Allowed prose patch is accepted

- **GIVEN** an enrichment patch targets an approved prose field such as description, role, faction, `dmInstructions`, `adventureSummary`, or `plotHooks`
- **AND** the target file and JSON path are valid
- **WHEN** patch validation and application run
- **THEN** the patch SHALL be applied deterministically
- **AND** the applied patch SHALL be represented in the enrichment result.

### Requirement: Blueprint enrichment reports SHALL surface actionable diagnostics

Blueprint enrichment report generation SHALL preserve status, reason, counts, and diagnostic arrays so GUI/toolkit callers can explain enrichment outcomes.

#### Scenario: Report summarizes skipped or unavailable enrichment

- **GIVEN** the enrichment pipeline returns `skipped` or `not_implemented`
- **WHEN** `build_enrichment_report(...)` runs
- **THEN** the report SHALL include status, reason, created timestamp, applied/rejected/error/warning counts, and pass count
- **AND** counts SHALL match the pipeline result arrays.

#### Scenario: Report summarizes applied and rejected patches

- **GIVEN** the enrichment pipeline returns applied patches, rejected patches, warnings, or errors
- **WHEN** `build_enrichment_report(...)` runs
- **THEN** the report SHALL preserve those arrays or equivalent diagnostics
- **AND** the report SHALL include deterministic counts for downstream tooling.
