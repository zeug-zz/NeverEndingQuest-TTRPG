# toolkit-narrative-enrichment-report-surfacing Specification

## Purpose
Enrichment plan status in toolkit reports - status compatibility without obscuring source-fidelity results. Preserves existing MODULE_SUMMARY.md generation.
## Requirements
### Requirement: Narrative enrichment status SHALL be report-compatible

Narrative enrichment planning status SHALL be compatible with accurate-ingest review/status reports without obscuring source-fidelity results.

#### Scenario: Source fidelity has blockers

- **GIVEN** source/build fidelity reports include blockers
- **WHEN** status payloads are rendered
- **THEN** source-fidelity blockers SHALL remain the primary status
- **AND** enrichment status SHALL NOT make the build appear publishable.

#### Scenario: Enrichment skipped

- **GIVEN** profile `none` is selected
- **WHEN** report/status payloads include enrichment metadata
- **THEN** the status SHALL be `skipped` or equivalent non-blocking status
- **AND** accurate ingest SHALL remain complete.

#### Scenario: Enrichment plan blocked

- **GIVEN** a non-`none` profile is selected
- **AND** source-lock rules block enrichment planning
- **WHEN** status payloads are rendered
- **THEN** the payload SHALL include enrichment blocker details
- **AND** it SHALL NOT alter source-fidelity scoring.

### Requirement: Narrative enrichment SHALL preserve existing adventure markdown generation

Narrative enrichment planning SHALL NOT duplicate, bypass, trigger, or replace the existing toolkit finisher path that generates `MODULE_SUMMARY.md`.

#### Scenario: Toolkit finisher generates module summary

- **GIVEN** an accurate-ingest build reaches the existing toolkit finisher path
- **WHEN** the finisher generates `MODULE_SUMMARY.md`
- **THEN** narrative enrichment planning SHALL NOT regenerate that file
- **AND** it SHALL NOT change the download endpoint behavior for adventure markdown.

#### Scenario: Enrichment plan references adventure markdown

- **GIVEN** `MODULE_SUMMARY.md` exists for a module
- **WHEN** enrichment planning records report metadata
- **THEN** the plan MAY reference the summary artifact path
- **AND** it SHALL NOT require the summary artifact to exist for profile `none`.

