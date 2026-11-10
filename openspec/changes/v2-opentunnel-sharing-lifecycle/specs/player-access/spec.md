# Spec Delta

## ADDED Requirements

### Requirement: Facilitator access rotation SHALL revoke prior player sessions

Facilitator rotation or revocation SHALL use the existing N1 shared-credential verifier and session model. It SHALL invalidate every active session, pre-login challenge, CSRF proof, and player socket before new access is accepted; prior credentials and cookies SHALL NOT remain valid. N1 authentication, cookie, Host/Origin, and CSRF rules SHALL remain unchanged.

#### Scenario: Facilitator rotates the shared player credential
- **WHEN** the facilitator replaces the configured shared credential while sharing is active
- **THEN** all existing player sessions and sockets are immediately invalidated, the prior credential and cookies are rejected, and only the new credential can create a session after the readiness checks pass

#### Scenario: Facilitator revokes access without replacement
- **WHEN** the facilitator revokes player access without configuring a replacement credential
- **THEN** all existing sessions and sockets are invalidated, new login fails closed, and no unauthenticated player service is exposed

#### Scenario: Rotation occurs while a player is connected
- **WHEN** a connected player's session is invalidated by facilitator rotation or Stop sharing
- **THEN** the socket receives no further player events or command admission and the client must authenticate and resynchronize under the existing N1 protocol
