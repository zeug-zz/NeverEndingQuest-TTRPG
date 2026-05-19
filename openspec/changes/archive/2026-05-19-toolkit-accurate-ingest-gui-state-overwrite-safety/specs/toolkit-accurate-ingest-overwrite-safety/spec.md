## ADDED Requirements

### Requirement: Packet builds SHALL refuse unconfirmed overwrite

Packet-driven accurate-ingest builds SHALL refuse to write over an existing module directory unless overwrite has been authorized by route-level confirmation or validated clean-rebuild plan.

#### Scenario: Existing module without confirmation is refused

- **GIVEN** `modules/<slug>/` already exists
- **AND** no valid overwrite confirmation token or rebuild plan artifact is present
- **WHEN** packet build is requested
- **THEN** the build SHALL fail before seed writer or ModuleBuilder writes module files
- **AND** the failure reason SHALL identify missing overwrite authorization.

#### Scenario: First build proceeds without overwrite token

- **GIVEN** `modules/<slug>/` does not exist
- **WHEN** packet build is requested
- **THEN** the build MAY proceed without overwrite confirmation.

#### Scenario: Confirmed clean rebuild proceeds

- **GIVEN** `modules/<slug>/` exists
- **AND** the route-level overwrite confirmation or rebuild plan artifact is valid for the same workspace and module slug
- **WHEN** packet build is requested
- **THEN** the clean rebuild MAY proceed through the backup-clean rebuild path.

### Requirement: Retry paths SHALL preserve overwrite safety

Retry and resume paths SHALL not bypass overwrite authorization.

#### Scenario: Retry-from-packet refuses destructive overwrite

- **GIVEN** a packet-build retry is requested for an existing module
- **AND** no valid overwrite authorization is present
- **WHEN** the retry attempts to rebuild from packet artifacts
- **THEN** it SHALL fail before module writes.

#### Scenario: Finishing-only retry remains allowed

- **GIVEN** a module already exists and packet materialization is not requested
- **WHEN** the operator retries finishing or report refresh only
- **THEN** the retry SHALL remain allowed without overwrite authorization.
