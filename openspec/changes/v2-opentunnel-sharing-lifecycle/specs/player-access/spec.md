# Spec Delta

## ADDED Requirements

### Requirement: Facilitator credential issuance SHALL store only the N1 verifier

For each credential issuance, the plaintext player credential SHALL be generated once and shown once to the local facilitator. It SHALL never be persisted, logged, passed as an argument, placed in an environment variable, or included in evidence. Only the existing N1 verifier SHALL be stored in private 0600 storage outside the repository and campaign data, and it SHALL never be committed to Git. This change SHALL NOT require an OS keychain; keychain integration is deferred.

#### Scenario: A credential is issued
- **WHEN** the facilitator initializes player access or rotates its credential
- **THEN** the plaintext is shown once locally, only the existing N1 verifier is written to the private 0600 store, and no plaintext appears in logs, arguments, environment, repository/campaign files, or evidence

#### Scenario: The facilitator loses the plaintext credential
- **WHEN** the facilitator cannot retrieve the previously displayed credential
- **THEN** recovery requires issuing a new credential through rotation; the plaintext is not read back from storage

### Requirement: Facilitator access rotation SHALL revoke prior player sessions

Rotation and revocation SHALL use the existing N1 verifier and session model. Rotation SHALL issue a new credential and invalidate sessions, challenges, CSRF proofs, and sockets before accepting its verifier; prior credentials and cookies SHALL NOT remain valid. Stop sharing SHALL invalidate sessions and sockets. N1 authentication, cookie, and CSRF rules remain; the only Host/Origin addition is the exact generation-bound HTTPS origin below.

#### Scenario: Facilitator rotates the shared player credential
- **WHEN** the facilitator replaces the configured shared credential while sharing is active
- **THEN** all existing player sessions and sockets are immediately invalidated, the prior credential and cookies are rejected, and only the new credential can create a session after the readiness checks pass

#### Scenario: Facilitator revokes access without replacement
- **WHEN** the facilitator revokes player access without configuring a replacement credential
- **THEN** all existing sessions and sockets are invalidated, new login fails closed, and no unauthenticated player service is exposed

#### Scenario: Rotation occurs while a player is connected
- **WHEN** a connected player's session is invalidated by facilitator rotation or Stop sharing
- **THEN** the socket receives no further player events or command admission and the client must authenticate and resynchronize under the existing N1 protocol

## MODIFIED Requirements

### Requirement: Player requests SHALL validate Host, Origin, and CSRF

The player boundary SHALL compare the raw `Host` to an explicit allowlist and validate `Origin` for Socket.IO handshakes and state-changing requests. State-changing HTTP requests SHALL also carry same-origin CSRF proof. `Forwarded` and `X-Forwarded-*` headers SHALL NOT establish identity, host, origin, scheme, or client address. After companion status reports route readiness for the active generation, and before the controller reports that generation ready, the controller SHALL add only the exact HTTPS scheme, host, and port reported by status: N1 receives the exact `https://host:port` Origin and matching exact Host authority. This binding SHALL be controller-owned and generation-scoped, and SHALL be cleared on stop, failed, degraded, and rotation. A changed or unparsable companion origin SHALL fail closed. No wildcard, suffix, subdomain, or HTTP match is permitted, and the player binding SHALL NOT expose the host surface.

#### Scenario: Host or Origin is not allowed
- **WHEN** an HTTP request or Socket.IO handshake presents a Host or required Origin outside the explicit local allowlist and the exact active-generation HTTPS binding
- **THEN** the boundary rejects it before routing, authentication state changes, or gameplay data delivery

#### Scenario: Forwarding headers are spoofed
- **WHEN** a request contains attacker-controlled forwarding headers that conflict with its Host or Origin
- **THEN** the decision and cookie policy are unchanged from the raw Host and Origin values

#### Scenario: Cross-origin mutation is attempted
- **WHEN** a browser submits a login or other state-changing HTTP request without valid same-origin CSRF proof
- **THEN** the request is rejected without changing session, party, or gameplay state

#### Scenario: The active companion origin is bound exactly
- **WHEN** companion status reports a parseable HTTPS origin after readiness for the active generation
- **THEN** only that exact scheme/host/port Origin and matching exact Host authority are added to N1 validation

#### Scenario: A wildcard Origin is attempted
- **WHEN** a player request uses a wildcard Origin instead of the exact active-generation Origin
- **THEN** N1 rejects the request

#### Scenario: A suffix-matching Host or Origin is attempted
- **WHEN** a player request uses a suffix match rather than the exact active-generation Host or Origin
- **THEN** N1 rejects the request

#### Scenario: A subdomain Host or Origin is attempted
- **WHEN** a player request uses a subdomain rather than the exact active-generation Host or Origin
- **THEN** N1 rejects the request

#### Scenario: An HTTP Origin is attempted
- **WHEN** a player request presents an `http` Origin
- **THEN** N1 rejects the request

#### Scenario: The request port does not match
- **WHEN** a Host or Origin uses a port different from the exact active-generation HTTPS origin
- **THEN** N1 rejects the request

#### Scenario: Companion status has an unparsable or changed origin
- **WHEN** companion status contains an unparsable origin or changes the active generation's reported origin
- **THEN** the controller fails closed, publishes no invitation, and does not retain or broaden the prior binding

#### Scenario: A stale generation reports an origin
- **WHEN** companion status from a stale generation reports an otherwise valid HTTPS origin
- **THEN** the controller ignores it and does not add it to N1 validation

#### Scenario: Stop clears the origin binding
- **WHEN** sharing stops
- **THEN** the prior Host/Origin addition is cleared and rejected

#### Scenario: Degraded sharing clears the origin binding
- **WHEN** the active sharing generation becomes degraded
- **THEN** the prior Host/Origin addition is cleared and rejected until a fresh readiness check succeeds

#### Scenario: Rotation clears the origin binding
- **WHEN** the facilitator rotates player access
- **THEN** the prior Host/Origin addition is cleared and rejected until a fresh status/readiness check succeeds
