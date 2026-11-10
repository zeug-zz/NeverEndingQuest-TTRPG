# Spec Delta

## ADDED Requirements

### Requirement: Sharing lifecycle controls SHALL remain host-only

Start sharing, Copy invitation, status/diagnostics, Rotate/revoke access, and Stop sharing controls SHALL be available only through the local facilitator surface. They SHALL NOT be registered on the player application or included in the tunnel target. Player snapshots and events SHALL NOT contain lifecycle controls, invitation data, companion status, or host diagnostics.

#### Scenario: Facilitator opens local sharing controls
- **WHEN** the facilitator opens the host application on its loopback surface
- **THEN** the host surface presents the named lifecycle controls and the player application registrations remain unchanged

#### Scenario: A player or tunnel client attempts a lifecycle operation
- **WHEN** a request through the player listener or its tunnel target attempts invitation retrieval, status/diagnostics, access rotation/revocation, or Stop sharing
- **THEN** the player application rejects it without invoking a host lifecycle handler or changing host state

#### Scenario: Route and event inventory is checked
- **WHEN** the route/event inventory enumerates host controls and player registrations
- **THEN** every lifecycle control is classified host-only, the player registrations still equal the N1 positive allowlist, and the tunnel target is only the player loopback listener

#### Scenario: Player receives a gameplay projection
- **WHEN** an authenticated player receives a snapshot or event
- **THEN** it contains no sharing control, invitation, companion status, or host diagnostic field
