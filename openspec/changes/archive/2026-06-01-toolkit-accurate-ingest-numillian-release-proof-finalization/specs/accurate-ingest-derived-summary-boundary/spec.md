## ADDED Requirements

### Requirement: Module Summary Remains Derived-Only

`MODULE_SUMMARY.md` SHALL be generated from final audited module JSON and SHALL NOT be used as source-fidelity repair input.

#### Scenario: Summary generation succeeds
- **GIVEN** Numillian module JSON has been finalized
- **WHEN** `MODULE_SUMMARY.md` is generated or refreshed
- **THEN** it SHALL reflect final module artifacts
- **AND** it SHALL NOT mutate module JSON.

#### Scenario: Source-fidelity blocker exists
- **GIVEN** a source-fidelity or publishability blocker remains in module JSON or reports
- **WHEN** `MODULE_SUMMARY.md` contains source-faithful prose
- **THEN** the summary SHALL NOT be treated as repairing the blocker.

#### Scenario: Summary generation fails
- **GIVEN** summary generation fails
- **WHEN** release proof is evaluated
- **THEN** the failure SHALL be reported without corrupting module artifacts.

## SHOULD Guidance

Keep disk-first download behavior and existing Homebrewery summary generation semantics.
