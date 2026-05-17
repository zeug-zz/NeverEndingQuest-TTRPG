## ADDED Requirements

### Requirement: Normalized packets SHALL be synthesized from source graph artifacts when multipass is enabled

Accurate-ingest multipass normalization SHALL synthesize review packets from source graph, section extraction, identity, and topology artifacts rather than directly trusting a one-shot model payload.

#### Scenario: Packet synthesis uses source graph and synthesis reports

- **GIVEN** source graph artifacts and multipass synthesis reports exist
- **WHEN** normalized packet synthesis runs
- **THEN** packet locations, NPC seeds, monster references, plot progression, and warnings SHALL be derived from source-backed artifacts
- **AND** generated packet content SHALL remain review-compatible.

#### Scenario: Packet entries may include source references compatibly

- **GIVEN** source graph atom IDs are available
- **WHEN** packet synthesis emits optional provenance or confidence notes
- **THEN** it MAY include source graph refs
- **AND** those refs SHALL NOT break existing packet validation.

### Requirement: Existing review packet compatibility SHALL be preserved

Multipass normalization SHALL not invalidate legacy normalized packets or old workspaces.

#### Scenario: Legacy packet still validates

- **GIVEN** a normalized packet satisfies the previous review contract
- **AND** it lacks multipass source graph references
- **WHEN** `validate_review_packet(...)` runs
- **THEN** the packet SHALL remain valid.

#### Scenario: Multipass packet still validates

- **GIVEN** a normalized packet was generated from source graph and synthesis artifacts
- **WHEN** `validate_review_packet(...)` runs
- **THEN** the packet SHALL validate under the existing review contract
- **AND** optional source refs SHALL not be required for validity.

### Requirement: Multipass fallback SHALL remain available

The legacy one-shot normalizer path SHALL remain available when multipass cannot run safely.

#### Scenario: Missing source graph falls back safely

- **GIVEN** multipass normalization is enabled
- **AND** source graph artifacts are missing or invalid
- **WHEN** normalization begins
- **THEN** the pipeline SHALL either fall back to legacy normalization or fail closed with a reviewable report
- **AND** it SHALL NOT silently claim multipass success.

#### Scenario: Synthesis failure preserves source artifacts

- **GIVEN** section extraction succeeded but packet synthesis fails
- **WHEN** the normalizer reports failure
- **THEN** source manifest, source graph, section extraction, identity, and topology artifacts SHALL remain available for inspection or retry.
