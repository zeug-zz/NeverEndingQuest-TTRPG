## 1. Connector Data Contract

- [x] 1.1 Define generated connector fields and `spatial_remediation` provenance shape.
- [x] 1.2 Define deterministic connector archetype whitelist and naming/id rules.
- [x] 1.3 Confirm connector nodes can be represented in existing area and map schemas without overlapping coordinates.
- [x] 1.4 Document that same-coordinate multi-plane rooms are deferred until a future spatial-layer schema.

## 2. Topology Normalization Runtime

- [x] 2.1 Consume unresolved-edge diagnostics from the corrected coordinate solver.
- [x] 2.2 Implement deterministic connector insertion for one unresolved edge.
- [x] 2.3 Extend insertion to multiple unresolved edges with stable ordering and collision-safe ids.
- [x] 2.4 Replace impossible direct edges with connector paths while preserving original authored rooms.
- [x] 2.5 Re-run coordinate solving on the normalized graph and reject outputs that still fail strict validation.

## 3. Area/Map Parity Synchronization

- [x] 3.1 Write generated connector nodes to the authoritative area artifact.
- [x] 3.2 Synchronize generated connector nodes and edges to map/graph artifacts used by parity validation.
- [x] 3.3 Ensure validators remain non-mutating and only report parity status.
- [x] 3.4 Emit `author_structural_debt` when parity cannot be restored.

## 4. Optional Advisory Flavor

- [x] 4.1 Add no LLM dependency for successful deterministic connector insertion.
- [x] 4.2 If advisory flavor is enabled, constrain LLM suggestions to connector names/descriptions/archetype selection only.
- [x] 4.3 Validate advisory output against the deterministic whitelist and fall back to templates on any failure.
- [x] 4.4 Require human approval before accepting non-template advisory flavor, if surfaced in the GUI.

## 5. Regression Coverage

- [x] 5.1 Add a fixture where Tier 1 fails or is forced to fail and connector insertion repairs the unresolved edge.
- [x] 5.2 Add a fixture with multiple unresolved edges and deterministic connector ordering.
- [x] 5.3 Add a fixture proving generated connectors carry provenance and unique coordinates.
- [x] 5.4 Add a no-regression fixture proving already-valid modules are unchanged.
- [x] 5.5 Add a fixture proving invalid advisory LLM suggestions cannot mutate canonical topology.

## 6. Verification

- [x] 6.1 Run targeted compile checks for remediation and tests.
- [x] 6.2 Run spatial embedding, coordinate grounding, and parity tests.
- [x] 6.3 Run Numillian publishability audit and confirm no regression.
- [x] 6.4 Run `openspec validate spatial-topology-normalization-failsafe`.

## Guidance

The final implementation should guarantee spatial adjacency only for the blocker class it owns: unresolved coordinate adjacency. It must not claim to solve unrelated schema, semantic, media, NPC, or monster blockers.
