## ADDED Requirements

### Requirement: Canonical Artifact Set Is Coherent

Accurate-ingest finalization MUST leave a coherent canonical artifact set for publication and gameplay testing.

#### Scenario: Rebuild replaces multi-area output with single-area output
- **GIVEN** a rebuild changes the module graph shape
- **WHEN** finalization completes
- **THEN** stale canonical area/map artifacts from the old graph SHALL be removed or reconciled intentionally
- **AND** current canonical area/map artifacts SHALL be present and trackable.

### Requirement: Live And BU Parity Preserves Canonical Content

Canonical BU artifacts MUST preserve the same source-critical context as live artifacts.

#### Scenario: Source-critical NPC or plot content is repaired
- **GIVEN** a live module artifact contains repaired critical source content
- **WHEN** publication artifacts are inspected
- **THEN** the corresponding BU artifact SHALL contain equivalent canonical content.
