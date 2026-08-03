# accurate-ingest-final-reconciliation-lock-path-safety Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-llm-builder-final-editor. Update Purpose after archive.
## Requirements
### Requirement: Final reconciliation artifact writes SHALL use safe file paths for locks

Final reconciliation artifact persistence SHALL derive lock paths from the target file path only. Serialized JSON payloads, dictionaries, lists, or other artifact content SHALL NOT be accepted or interpolated as file paths or lock-file names.

#### Scenario: Payload-as-path is rejected safely

- **GIVEN** a final reconciliation artifact write receives a non-path JSON payload where a file path is expected
- **WHEN** the write helper validates the target
- **THEN** it SHALL fail safely with structured diagnostics
- **AND** it SHALL NOT attempt to create a lock file whose name contains serialized JSON content.

#### Scenario: Normal final reconciliation brief persists safely

- **GIVEN** a valid workspace path and valid `final_reconciliation_brief.json` payload
- **WHEN** the brief is persisted
- **THEN** the helper SHALL write the artifact atomically
- **AND** the lock or temporary file path SHALL be bounded by the target artifact path, not the payload content.

#### Scenario: Existing safe_write_json callers remain compatible

- **GIVEN** existing callers pass `(path, data)` in the supported order
- **WHEN** the path-safety fix is applied
- **THEN** those callers SHALL continue to write valid JSON successfully
- **AND** no runtime module artifact write path SHALL regress.

