## ADDED Requirements

### Requirement: Numillian Release Proof Requires All Final Gates

`The_Hidden_City_of_Numillian` SHALL be considered release-proof only when validation, source-fidelity benchmark, and publishability gates agree that the module is pass/publishable.

#### Scenario: All gates pass
- **GIVEN** Numillian validation passes
- **AND** the accurate-ingest benchmark reports `source_fidelity_status=pass`
- **AND** publishability audit reports publishable/pass
- **WHEN** release proof is evaluated
- **THEN** the module MAY be treated as release-ready.

#### Scenario: Publishability remains blocked
- **GIVEN** validation and source fidelity pass
- **AND** publishability reports blocked or fail
- **WHEN** release proof is evaluated
- **THEN** the module SHALL NOT be treated as release-ready
- **AND** the blocker class SHALL be reported explicitly.

### Requirement: Source-Fidelity Pass State Is Preserved

Finalization SHALL preserve passing source-fidelity categories unless a regression is explicitly reported.

#### Scenario: Finalization changes module artifacts
- **GIVEN** a finalization patch changes Numillian module artifacts
- **WHEN** the benchmark is rerun
- **THEN** NPC, location, puzzle, lore, and tone categories SHALL remain pass or the change SHALL fail release proof.

## SHOULD Guidance

Prefer diagnostic-first release proof so patches target exact blocker classes instead of broad module rewrites.
