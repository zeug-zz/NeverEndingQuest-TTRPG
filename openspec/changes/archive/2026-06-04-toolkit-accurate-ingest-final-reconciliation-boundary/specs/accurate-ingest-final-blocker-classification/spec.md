## ADDED Requirements

### Requirement: Final blocker classifier SHALL separate fatal and editorial blockers

After ModuleBuilder output and build-fidelity reporting, the accurate-ingest pipeline SHALL classify final blockers into fatal blockers and editorial blockers before deciding whether to stop the build.

#### Scenario: Fatal structural blocker stops build

- **GIVEN** build-fidelity or final artifact checks report a missing module directory, invalid JSON, missing canonical artifact, or unrecoverable topology failure
- **WHEN** final blocker classification runs
- **THEN** the classifier SHALL mark the blocker as fatal
- **AND** the packet build SHALL remain blocked before readiness or finishing.

#### Scenario: Source atom mismatch becomes editorial blocker

- **GIVEN** build-fidelity reports a required source location, NPC, puzzle, clue, item, or encounter missing from generated output
- **AND** generated module artifacts exist and JSON can be inspected
- **WHEN** final blocker classification runs
- **THEN** the classifier SHALL mark the blocker as editorial unless tied to a fatal structural failure
- **AND** the build SHALL be eligible for final reconciliation.

#### Scenario: Well headings classify as editorial blockers

- **GIVEN** build-fidelity reports missing required locations named `Trigger`, `Passive Element`, or `Active Element`
- **AND** the source refs identify markdown headings or mechanics sections rather than generated module topology
- **WHEN** final blocker classification runs
- **THEN** those blockers SHALL be classified as editorial source-structure blockers
- **AND** they SHALL NOT be treated as fatal missing-location blockers.

### Requirement: Final blocker classifier SHALL preserve diagnostic evidence

The classifier SHALL preserve original blocker messages, categories, source atom IDs when present, and report paths in its output.

#### Scenario: Original blocker evidence remains available

- **GIVEN** build-fidelity produces blocker entries and a refusal reason
- **WHEN** final blocker classification completes
- **THEN** the classification result SHALL include the original blocker messages
- **AND** it SHALL include the fatal/editorial classification for each blocker.
