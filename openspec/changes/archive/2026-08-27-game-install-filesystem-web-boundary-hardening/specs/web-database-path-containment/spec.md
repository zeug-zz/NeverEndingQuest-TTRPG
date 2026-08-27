# Web Database Path Containment

## Purpose

Prevent web-controlled world-narrative ingestion from opening or modifying arbitrary SQLite files outside the installed game data boundary.

## ADDED Requirements

### Requirement: Database targets SHALL be repository-local data files

The world-narrative ingestion endpoint SHALL resolve an omitted database target to the canonical runtime memory database and SHALL accept supplied targets only when they are relative `.db` paths beneath the repository `data/` directory. The endpoint SHALL reject absolute paths, traversal components, symlinked path components, and paths outside the approved data directory before opening SQLite.

#### Scenario: Default database target

- **WHEN** a valid ingestion request omits `db_path`
- **THEN** ingestion SHALL use the repository's canonical `data/memory.db` target
- **AND** no path outside the repository `data/` directory SHALL be opened

#### Scenario: Valid repository-local database target

- **WHEN** a valid ingestion request supplies a relative path such as `data/memory.db`
- **THEN** the request SHALL be accepted and resolved to the canonical repository-local target

#### Scenario: Absolute or traversal target

- **WHEN** a request supplies an absolute path or a path containing traversal components that would escape `data/`
- **THEN** the endpoint SHALL return a client error before SQLite connection
- **AND** it SHALL not create, read, or modify the requested outside path

#### Scenario: Symlinked target

- **WHEN** a requested database path or one of its parent components is a symlink
- **THEN** the endpoint SHALL reject the request before SQLite connection
- **AND** it SHALL report only a bounded path-policy error

### Requirement: Database path errors SHALL be fail-closed and non-leaking

The endpoint SHALL distinguish an unsafe database path from a database schema or ingestion failure, SHALL avoid returning absolute host paths in client-facing errors, and SHALL preserve existing successful ingestion response semantics for approved targets.

#### Scenario: Unsafe path response

- **WHEN** path authorization fails
- **THEN** the response SHALL identify the path-policy failure without exposing the repository's absolute filesystem path
- **AND** the ingestion function SHALL not be called

#### Scenario: Approved target database failure

- **WHEN** an approved target passes path authorization but SQLite or schema processing fails
- **THEN** existing ingestion error handling SHALL remain responsible for the failure
- **AND** path hardening SHALL not rewrite the database service's error contract
