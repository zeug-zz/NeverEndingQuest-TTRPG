## ADDED Requirements

### Requirement: Unified GUI builds SHALL run build and source fidelity gates after seed/enrichment

Accurate-ingest GUI builds that use blueprint-native seeding SHALL run build-fidelity and source-fidelity rollup checks after deterministic seeding and bounded enrichment complete.

#### Scenario: Source-fidelity rollup generated

- **GIVEN** a blueprint-native GUI build completes seeding and enrichment
- **WHEN** build-fidelity checks run
- **THEN** `build_fidelity_report.json` SHALL be generated
- **AND** `source_fidelity_report.json` SHALL be generated or updated from the build-fidelity result.

#### Scenario: Blocked fidelity stops publication path

- **GIVEN** build-fidelity detects a missing required source location, NPC, plot beat, or puzzle
- **WHEN** source-fidelity status is composed
- **THEN** the status SHALL be blocked
- **AND** the job SHALL NOT be reported as publishable.

### Requirement: Publication audit SHALL consume final source-fidelity status unchanged

The publishability audit SHALL continue to report source-fidelity as a distinct dimension and SHALL NOT replace readiness or semantic publishability semantics.

#### Scenario: Ready and semantic pass but source fidelity blocked

- **GIVEN** `ready_status` is pass
- **AND** `publishable_status` is pass before source-fidelity composition
- **AND** `source_fidelity_status` is blocked
- **WHEN** final gate composition runs
- **THEN** final publishability SHALL be blocked by source fidelity.

#### Scenario: Legacy module remains fail-open

- **GIVEN** a module has no accurate-ingest source artifacts
- **WHEN** publishability audit runs
- **THEN** source-fidelity status SHALL be unknown
- **AND** the unknown source-fidelity status SHALL NOT block legacy publication checks by itself.

### Requirement: Numillian benchmark SHALL verify the unified path

The unified path SHALL be testable against the Numillian benchmark fixture to prove source preservation end to end.

#### Scenario: Numillian source locations preserved

- **GIVEN** Numillian source is processed through the GUI-equivalent blueprint-native path
- **WHEN** the benchmark runs
- **THEN** all 13 source locations SHALL be preserved by original source name or approved mapping.

#### Scenario: Numillian core puzzle/lore preserved

- **GIVEN** Numillian source contains Trial-at-the-Door, skull riddle, flooding room, kill-the-dog mindscape, Gatepact lore, and Kobe protection objective
- **WHEN** the benchmark runs
- **THEN** those elements SHALL pass, degrade with explicit evidence, or block publication.
