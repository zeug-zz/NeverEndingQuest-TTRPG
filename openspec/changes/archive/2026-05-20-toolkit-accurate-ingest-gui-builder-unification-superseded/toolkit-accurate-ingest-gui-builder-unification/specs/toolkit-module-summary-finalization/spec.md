## ADDED Requirements

### Requirement: Toolkit finisher SHALL generate MODULE_SUMMARY.md after successful unified builds

Every successful accurate-ingest GUI build that reaches toolkit finishing SHALL generate or refresh `modules/<slug>/MODULE_SUMMARY.md` using the existing Homebrewery adventure writer.

#### Scenario: Summary generated after finisher stages

- **GIVEN** a blueprint-native accurate-ingest build passes readiness prerequisites and enters the toolkit finisher
- **WHEN** the finisher completes its module summary stage
- **THEN** `MODULE_SUMMARY.md` SHALL exist when generation succeeds
- **AND** `toolkit_build_report.json` SHALL include the module summary stage status and path.

#### Scenario: Summary generation failure degrades but does not mutate source data

- **GIVEN** module summary generation raises an exception
- **WHEN** the finisher handles the exception
- **THEN** the finisher report SHALL mark the module summary stage degraded
- **AND** it SHALL NOT mutate module JSON files as a repair attempt.

### Requirement: MODULE_SUMMARY.md SHALL remain a derived presentation artifact

`MODULE_SUMMARY.md` SHALL present the completed module but SHALL NOT be treated as authoritative source truth, source-fidelity repair, or publication waiver evidence.

#### Scenario: Summary cannot mask fidelity blocker

- **GIVEN** source-fidelity status is blocked because required source content is missing from module JSON
- **AND** `MODULE_SUMMARY.md` contains prose mentioning that missing content
- **WHEN** publication gate composition runs
- **THEN** the module SHALL remain blocked
- **AND** summary prose SHALL NOT satisfy source-fidelity requirements by itself.

#### Scenario: Summary download uses cached file

- **GIVEN** `MODULE_SUMMARY.md` already exists and is non-empty
- **WHEN** the user downloads the adventure markdown
- **THEN** the endpoint SHALL serve the cached file from disk
- **AND** it SHALL NOT regenerate the summary on every request.

### Requirement: Summary content SHALL reflect audited module data

The Homebrewery adventure writer SHALL render content from the final audited module files, including source-preserved locations, NPCs, plot points, monsters, and treasure.

#### Scenario: Source-preserved locations appear in summary

- **GIVEN** a completed module has source-preserved locations in `areas/*_BU.json`
- **WHEN** `MODULE_SUMMARY.md` is generated
- **THEN** the Locations section SHALL include those locations
- **AND** it SHALL use the final audited module data rather than original upload text alone.
