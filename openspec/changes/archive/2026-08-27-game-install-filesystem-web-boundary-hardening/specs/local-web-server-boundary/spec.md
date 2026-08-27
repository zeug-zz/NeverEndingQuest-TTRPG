# Local Web Server Boundary

## Purpose

Make a normal installed NeverEndingQuest server reachable only from the local machine by default while retaining an explicit, documented configuration path for deliberate LAN deployment.

## ADDED Requirements

### Requirement: The server SHALL default to loopback binding

When no valid host configuration is supplied, the web server SHALL bind to `127.0.0.1` and SHALL preserve the configured or default port. Blank, malformed, or unsupported host configuration SHALL fail closed to loopback rather than widening exposure.

#### Scenario: Existing configuration without host setting

- **WHEN** an existing installation starts with no `WEB_HOST` setting
- **THEN** the server SHALL bind to `127.0.0.1`
- **AND** the server port SHALL remain unchanged

#### Scenario: Invalid host setting

- **WHEN** `WEB_HOST` is blank or fails host validation
- **THEN** startup SHALL use `127.0.0.1`
- **AND** startup SHALL not bind to all interfaces

#### Scenario: Explicit LAN configuration

- **WHEN** an operator supplies a valid non-loopback `WEB_HOST` through the documented configuration
- **THEN** the server MAY bind to that host
- **AND** the LAN exposure SHALL require that explicit configuration

### Requirement: Default browser origins SHALL not be wildcarded

The Socket.IO web boundary SHALL use loopback browser origins by default and SHALL require an explicit configuration value for non-loopback origins. A missing or invalid origin configuration SHALL not restore wildcard origin behavior.

#### Scenario: Default local browser access

- **WHEN** the server uses its default loopback host and no CORS override is configured
- **THEN** localhost and loopback browser origins for the configured port SHALL be accepted
- **AND** arbitrary wildcard origins SHALL not be configured

#### Scenario: Explicit non-local origin configuration

- **WHEN** an operator supplies a valid explicit origin allowlist for deliberate LAN use
- **THEN** the configured origins SHALL be used
- **AND** the allowlist SHALL not be silently expanded to `*`

#### Scenario: Invalid origin configuration

- **WHEN** the origin configuration is missing, blank, malformed, or contains an unsafe wildcard
- **THEN** the server SHALL use the safe loopback-origin default
- **AND** startup SHALL continue without broadening browser access
