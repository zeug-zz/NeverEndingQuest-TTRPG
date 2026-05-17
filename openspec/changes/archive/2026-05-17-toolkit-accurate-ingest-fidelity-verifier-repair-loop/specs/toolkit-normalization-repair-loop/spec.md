## ADDED Requirements

### Requirement: Repair loop SHALL apply only validated source-backed packet patches

The repair loop SHALL use model output only as patch proposals. Python validation SHALL decide whether each operation is safe to apply.

#### Scenario: Repair proposal adds missing source-backed NPC

- **GIVEN** fidelity audit reports a repairable missing NPC with source refs
- **AND** the repair model proposes `add_npc_seed` with matching source refs
- **WHEN** repair validation runs
- **THEN** the operation MAY be applied to a packet copy
- **AND** the resulting packet SHALL pass `validate_review_packet(...)` before persistence.

#### Scenario: Repair proposal lacks source refs

- **GIVEN** a repair proposal adds or changes packet content
- **AND** the operation lacks source refs or source atom IDs
- **WHEN** repair validation runs
- **THEN** the operation SHALL be rejected
- **AND** the attempt artifact SHALL record the rejection reason.

### Requirement: Repair loop SHALL be bounded and reviewable

The repair loop SHALL use a configured maximum attempt count and SHALL persist attempt artifacts for review.

#### Scenario: Maximum attempts exhausted

- **GIVEN** repair is enabled
- **AND** the repair provider repeatedly emits invalid patches
- **WHEN** the maximum attempt count is reached
- **THEN** the original packet SHALL remain available
- **AND** `normalization_repair_report.json` SHALL record `repair_status=failed` with attempt count and reasons.

#### Scenario: Repair succeeds after one attempt

- **GIVEN** fidelity audit reports repairable blocking findings
- **AND** the first repair proposal validates and improves fidelity
- **WHEN** the repaired packet is persisted
- **THEN** `packet_repair_attempts/attempt_1.json` SHALL record the accepted operations
- **AND** the final fidelity report SHALL be based on the repaired packet.

### Requirement: Repair loop SHALL preserve original artifacts and fail closed on unsafe changes

Repair SHALL not delete source artifacts or silently overwrite packet content when validation fails.

#### Scenario: Unsafe destructive operation proposed

- **GIVEN** a repair proposal attempts to remove or overwrite source-backed packet content
- **WHEN** destructive operation validation runs
- **THEN** the operation SHALL be rejected in this slice
- **AND** the packet SHALL remain unchanged.

#### Scenario: Repair provider fails

- **GIVEN** fidelity audit completes
- **AND** the repair provider raises an exception or returns malformed JSON
- **WHEN** repair handling runs
- **THEN** the failure SHALL be recorded as degraded or failed repair status
- **AND** the audit report and original packet SHALL remain available.
