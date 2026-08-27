# install-root-path-resolution Specification

## Purpose
Keep installed game runtime files, uploads, logs, and update operations tied to the repository installation root even when the launcher is invoked from another working directory.

## Requirements

### Requirement: Installed entrypoints SHALL resolve application paths from the repository root

The web launcher and toolkit/application runtime paths SHALL resolve application-owned relative directories from the repository root derived from the installed source location, not from the caller's current working directory. This SHALL cover startup configuration/runtime directories, web upload roots, diagnostic logs, and update working-directory selection.

#### Scenario: Launch from the installation directory

- **WHEN** an installed entrypoint is launched from its normal installation directory
- **THEN** existing runtime files SHALL continue to be read and written at their current installation-relative locations
- **AND** no compatibility path behavior SHALL change for normal launchers

#### Scenario: Launch from an alternate current directory

- **WHEN** an installed entrypoint is launched while the caller's current directory is outside the installation
- **THEN** application-owned runtime paths SHALL still resolve beneath the installation root
- **AND** the caller's directory SHALL not receive game state, upload, log, or update files solely because it was current

#### Scenario: Update operation

- **WHEN** the in-app update operation runs
- **THEN** Git status, fetch, pull, and restart preparation SHALL use the resolved installation root as their working directory
- **AND** the update SHALL not operate on an unrelated repository selected by the caller's current directory

### Requirement: Root resolution SHALL remain bounded and fail safely

Repository-root resolution SHALL be deterministic for the installed source tree and SHALL reject unsafe derived paths rather than silently falling back to arbitrary current-directory locations. Existing provider, gameplay, and save/restore behavior SHALL remain unchanged apart from path placement.

#### Scenario: Root helper resolution

- **WHEN** the application resolves its root from an installed source file
- **THEN** the result SHALL be a stable directory containing the application source tree
- **AND** approved child paths SHALL be resolvable without requiring the caller to change directories

#### Scenario: Missing or unusable derived root

- **WHEN** a required rooted path cannot be resolved safely
- **THEN** the operation SHALL fail with a bounded actionable error or use its existing fail-open optional diagnostic behavior
- **AND** it SHALL not use an arbitrary user-supplied absolute path
