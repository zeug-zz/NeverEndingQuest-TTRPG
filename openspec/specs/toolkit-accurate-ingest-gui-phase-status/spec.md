# toolkit-accurate-ingest-gui-phase-status Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-gui-state-overwrite-safety. Update Purpose after archive.
## Requirements
### Requirement: Accurate-ingest GUI jobs SHALL expose canonical phase status

Accurate-ingest GUI jobs SHALL expose a stable canonical phase field that reflects source extraction, blueprint, review, seed, enrichment, fidelity, readiness, finishing, and publishability progress.

#### Scenario: Job payload includes canonical phase

- **GIVEN** an accurate-ingest job is progressing through the GUI builder pipeline
- **WHEN** the job polling payload is returned
- **THEN** it SHALL include a canonical accurate-ingest phase field
- **AND** phase values SHALL include source extraction, blueprint generation, review, seeding, enrichment, build fidelity, readiness, finishing, and publishability audit states when those stages are active.

#### Scenario: Existing status fields preserved

- **GIVEN** existing GUI code consumes `status`, `stage`, `pipeline_status`, `progress_stage`, or `progress_message`
- **WHEN** accurate-ingest phase status is added
- **THEN** those existing fields SHALL remain present with compatible semantics.

### Requirement: Accurate-ingest terminal states SHALL remain explicit

Accurate-ingest jobs SHALL keep terminal states distinguishable from in-progress phases.

#### Scenario: Terminal status visible

- **GIVEN** an accurate-ingest job reaches completed, not-publishable, failed, quarantined, or rejected state
- **WHEN** the GUI polls job status
- **THEN** the payload SHALL expose that terminal status without collapsing it into a generic progress phase.

