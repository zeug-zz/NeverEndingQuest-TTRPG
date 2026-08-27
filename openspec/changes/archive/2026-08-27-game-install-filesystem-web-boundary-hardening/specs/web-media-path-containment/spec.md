# Web Media Path Containment

## Purpose

Ensure public media-serving routes cannot use path traversal or symlinked files to expose arbitrary files from the game user's filesystem.

## ADDED Requirements

### Requirement: Media routes SHALL serve only from approved media roots

Video, icon, portrait, and module-media endpoints SHALL resolve requested paths and SHALL serve a file only when the resolved file remains beneath the endpoint's approved media root. Absolute inputs, traversal escapes, and symlinked files or components SHALL be rejected before `send_file`.

#### Scenario: Normal module media lookup

- **WHEN** a requested media filename is a regular file beneath the current module media root
- **THEN** the endpoint SHALL serve it using the existing media type and MIME behavior

#### Scenario: Static fallback lookup

- **WHEN** a requested module media file is absent and the same safe filename exists beneath the approved static media root
- **THEN** the endpoint SHALL preserve the existing static fallback behavior

#### Scenario: Traversal or absolute filename

- **WHEN** a media request contains `..`, an absolute path, or a path that resolves outside its approved root
- **THEN** the endpoint SHALL return a not-found or equivalent safe rejection response
- **AND** it SHALL not open or disclose the outside file

#### Scenario: Symlinked media

- **WHEN** the requested media file or any path component resolves through a symlink
- **THEN** the endpoint SHALL reject the request
- **AND** it SHALL not call the file-sending operation

### Requirement: Media hardening SHALL preserve safe compatibility behavior

The existing media type allowlist, module-first ordering, static fallback ordering, supported file types, and missing-media behavior SHALL remain unchanged for safe regular files.

#### Scenario: Existing safe media contract

- **WHEN** a valid safe request uses an existing supported filename for `monsters`, `npcs`, or `environment`
- **THEN** the response SHALL follow the same lookup order and status behavior as before path hardening

#### Scenario: Invalid media type

- **WHEN** a request supplies a media type outside the existing allowlist
- **THEN** the endpoint SHALL retain its existing invalid-media response
- **AND** no filesystem lookup outside approved roots SHALL occur
