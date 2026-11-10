# Spec Delta

## ADDED Requirements

### Requirement: Sharing lifecycle controls SHALL remain host-only

Initialize sharing identity, Start sharing, Copy invitation, status/diagnostics, Rotate/revoke access, and Stop sharing SHALL be local-facilitator controls only and SHALL be absent from the player application and tunnel target. Identity initialization SHALL be explicit and at most once per profile. Player snapshots and events SHALL omit lifecycle controls, invitations, companion status, and host diagnostics.

#### Scenario: Facilitator opens local sharing controls
- **WHEN** the facilitator opens the host application on its loopback surface
- **THEN** the host surface presents the named lifecycle controls, identity initialization requires explicit facilitator action, and the player application registrations remain unchanged

#### Scenario: A player or tunnel client attempts a lifecycle operation
- **WHEN** a request through the player listener or its tunnel target attempts identity initialization, invitation retrieval, status/diagnostics, access rotation/revocation, or Stop sharing
- **THEN** the player application rejects it without invoking a host lifecycle handler or changing host state

#### Scenario: Route and event inventory is checked
- **WHEN** the route/event inventory enumerates host controls and player registrations
- **THEN** every lifecycle control, including identity initialization, is classified host-only, the player registrations still equal the N1 positive allowlist, and the tunnel target is only the player loopback listener

#### Scenario: Player receives a gameplay projection
- **WHEN** an authenticated player receives a snapshot or event
- **THEN** it contains no sharing control, invitation, companion status, or host diagnostic field
