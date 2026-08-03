## ADDED Requirements

### Requirement: Accurate-Ingest ModuleBuilder Repairs Spatial Representation

Source-enhanced accurate-ingest ModuleBuilder builds SHALL repair spatial representation after generated locations and connectivity are finalized.

#### Scenario: Spatial contract passes after repair
- **GIVEN** a source-enhanced ModuleBuilder build emits valid location identities but inconsistent coordinates, cardinal adjacency, map links, or area connectivity
- **WHEN** the spatial repair stage runs
- **THEN** the repair stage SHALL recompute validator-safe spatial representation
- **AND** full-module validation SHALL NOT report spatial contract failures caused by stale generated coordinates or map links.

#### Scenario: Location identities are preserved
- **GIVEN** spatial repair processes a source-enhanced module
- **WHEN** coordinates or map links are rewritten
- **THEN** source and generated location IDs/names SHALL be preserved unless validation proves a duplicate or invalid identity must be rejected
- **AND** the repair report SHALL not claim a source-fidelity improvement from coordinate-only repair.

#### Scenario: Unsafe topology fails closed
- **GIVEN** spatial repair cannot place locations without creating contradictory or disconnected topology
- **WHEN** the repair stage completes
- **THEN** the build SHALL be blocked with explicit spatial diagnostics
- **AND** final-editor reconciliation SHALL NOT be invoked for that build.

### Requirement: Spatial Repair Emits Audit Metadata

Spatial repair SHALL emit compact audit metadata that explains what changed and what remains unresolved.

#### Scenario: Repair report contains counts
- **GIVEN** spatial repair runs for an accurate-ingest module
- **WHEN** the repair report is written
- **THEN** the report SHALL include input location count, repaired location count, edge count, unresolved issue count, and status
- **AND** the report SHALL be provider-free and deterministic for identical input artifacts.

## SHOULD Guidance

- Prefer existing spatial solver and topology normalization helpers over bespoke per-module repair logic.
