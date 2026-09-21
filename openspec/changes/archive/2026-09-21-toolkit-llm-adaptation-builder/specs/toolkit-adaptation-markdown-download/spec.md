## Purpose

Defines the readable derived adventure document that every completed adaptation must provide and the download behavior that serves the persisted artifact.

## ADDED Requirements

### Requirement: Completed adaptations produce readable Markdown

Every completed adaptation MUST persist a UTF-8 `MODULE_SUMMARY.md` containing the adapted title, readable headings, at least one playable area or location, the adapted premise or plot, and the adaptation notice.

#### Scenario: Valid Markdown summary

- **WHEN** a staged module passes its structural and semantic gates
- **THEN** the Markdown renderer produces a non-empty readable adventure document containing the required sections

#### Scenario: Unreadable summary

- **WHEN** Markdown generation produces missing, invalid, too-short, raw-JSON, traceback, or provider-error content
- **THEN** the adaptation cannot be reported as completed

### Requirement: Download serves the persisted summary

The adventure download endpoint MUST serve the persisted `MODULE_SUMMARY.md` for a completed module and MUST NOT require a new provider call on each request.

#### Scenario: Existing summary download

- **WHEN** a client requests the adventure Markdown for a completed module with a valid summary file
- **THEN** the endpoint returns that persisted file

#### Scenario: Missing summary download

- **WHEN** a client requests a module without a valid persisted summary
- **THEN** the endpoint returns a controlled unavailable response rather than silently claiming a completed adaptation

### Requirement: Markdown quality is independently testable

The summary contract MUST be testable without live provider calls using a fixture module and persisted Markdown output.

#### Scenario: Provider-free quality check

- **WHEN** a fixture module and summary are checked by the Markdown quality gate
- **THEN** required title, headings, playable content, encoding, and adaptation notice checks produce deterministic results
