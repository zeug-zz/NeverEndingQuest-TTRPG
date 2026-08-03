## ADDED Requirements

### Requirement: Reconciled module JSON SHALL pass deterministic validation before publication

After final reconciliation patches are applied, the pipeline SHALL rerun deterministic validation and publication gates before marking the module playable.

#### Scenario: Post-reconciliation validation passes

- **GIVEN** final reconciliation patches are applied successfully
- **WHEN** schema validation, readiness, publishability, and report agreement all pass
- **THEN** the module MAY proceed as a playable publication candidate
- **AND** final reports SHALL record accepted reconciliation and validation outcomes.

#### Scenario: Post-reconciliation validation fails with one repairable issue set

- **GIVEN** final reconciliation patches are applied
- **AND** validation fails with repairable diagnostics
- **WHEN** retry budget has not been used
- **THEN** the system SHALL allow at most one retry to the LLM Builder final editor with validation diagnostics
- **AND** the retry result SHALL still pass all patch validation before writes.

#### Scenario: Retry budget exhausted

- **GIVEN** validation fails after the bounded retry or fails with unrecoverable diagnostics
- **WHEN** final reconciliation completes
- **THEN** the build SHALL remain blocked
- **AND** final reconciliation reporting SHALL include failed validation diagnostics.
