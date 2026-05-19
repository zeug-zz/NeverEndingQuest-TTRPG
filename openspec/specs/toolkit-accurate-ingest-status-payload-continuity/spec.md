# toolkit-accurate-ingest-status-payload-continuity Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-gui-state-overwrite-safety. Update Purpose after archive.
## Requirements
### Requirement: Accurate-ingest job payload SHALL include compact build summary

Accurate-ingest job polling payloads SHALL include a grouped summary of source structure counts and major pipeline statuses when available.

#### Scenario: Summary includes source counts and statuses

- **GIVEN** an accurate-ingest job has source graph, blueprint, seed, build fidelity, readiness, or publishability artifacts
- **WHEN** the job polling payload is returned
- **THEN** it SHALL include a grouped accurate-ingest summary
- **AND** the summary SHALL include source counts for locations, NPCs, plot beats, and areas when known
- **AND** it SHALL include blueprint status, seed status, enrichment status, build fidelity status, readiness status, publishability status, and source-fidelity status when known.

#### Scenario: Legacy job payload remains compatible

- **GIVEN** a legacy or non-accurate-ingest toolkit job has no source graph or blueprint artifacts
- **WHEN** the job polling payload is returned
- **THEN** existing payload fields SHALL remain compatible
- **AND** the accurate-ingest summary MAY be omitted or marked disabled.

### Requirement: Fidelity review remains mandatory before module writes

Accurate-ingest status surfacing SHALL NOT bypass fidelity review approval requirements.

#### Scenario: Unapproved review blocks module materialization

- **GIVEN** an accurate-ingest workspace requires fidelity review
- **AND** review approval is missing, stale, or rejected
- **WHEN** packet build is requested
- **THEN** module file writes SHALL NOT begin
- **AND** the job status SHALL communicate that review approval is required or refused.

