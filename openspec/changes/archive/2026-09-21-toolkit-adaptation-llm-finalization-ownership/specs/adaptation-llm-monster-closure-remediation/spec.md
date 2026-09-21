## Purpose

Turn eligible adaptation monster-closure content gaps into bounded, redacted LLM remediation candidates without exposing arbitrary filesystem or provider payload authority.

## ADDED Requirements

### Requirement: Eligible closure failures produce bounded failure packets

When an adaptation content-level monster closure failure is eligible for revision, Python MUST persist an atomic, bounded failure packet containing the normalized unresolved reference, approved/candidate canonical identities, affected locations, quantity data, bounded scene evidence, source-reference IDs, attempt identity, revision identity, and remaining budget.

#### Scenario: Amphail failure packet

- **WHEN** `Cave guardians` cannot be resolved at revision zero despite an approved `Cave Guardian` artifact
- **THEN** the packet MUST identify normalized reference `cave_guardians`, canonical candidate `Cave Guardian`, K06/K08/RTR001/K10 evidence, and the three quantity contexts
- **AND** it MUST not contain full source text, full prompts, raw provider responses, credentials, request bodies, or absolute filesystem paths

### Requirement: Monster resolution is a bounded operation

The finalization contract MUST accept at most one whitelisted monster-resolution operation per revision round, targeting a Python-owned reference key and one approved canonical identity with bounded source-reference and interpretation fields.

#### Scenario: Valid canonical resolution

- **WHEN** the LLM proposes `resolve_monster_reference` for an approved `Cave Guardian` identity with valid source references
- **THEN** Python MUST validate the operation, identity, target, freshness, and bounds before applying it to a fresh staging target
- **AND** the operation MUST be recorded with bounded provenance and hashes

#### Scenario: Provider substitutes an identity

- **WHEN** the proposal names an identity outside the approved registry or attempts to add a new stat-block identity
- **THEN** Python MUST reject the proposal
- **AND** no invalid artifact or duplicate stat file may be written

### Requirement: Raw provider payload is never a remediation artifact

Failure packets, revision reports, job envelopes, and progress payloads MUST persist only bounded redacted diagnostics and hashes/counts for provider interactions.

#### Scenario: Provider returns malformed content

- **WHEN** a provider returns malformed or unsafe finalization content
- **THEN** the current staging revision MUST remain intact
- **AND** the persisted failure artifact MUST expose only a bounded failure code and safe diagnostic
