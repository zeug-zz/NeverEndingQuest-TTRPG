## ADDED Requirements

### Requirement: Source NPC/location bindings SHALL be preserved when source-supported

Accurate ingest SHALL preserve source-supported relationships between NPCs and locations where those relationships are present in source text, source graph atoms, normalized packets, topology reports, or validated triage decisions.

#### Scenario: NPC appears_in binding is source-supported

- **GIVEN** a source NPC has a source-supported location binding
- **WHEN** the source NPC is kept in canonical artifacts
- **THEN** the artifact SHALL carry that binding through `appears_in`, source refs, or an equivalent binding field.

#### Scenario: Kept NPCs are not name-only records

- **GIVEN** a source NPC is preserved in module artifacts
- **WHEN** the record is audited
- **THEN** it SHALL include at least one of: location binding, plot binding, faction binding, explicit role, or source ref.

#### Scenario: Location-associated content remains available to builder handoff

- **GIVEN** a source location has associated NPCs, monsters, items, clues, puzzles, or plot beats
- **WHEN** the source-enhanced handoff is serialized
- **THEN** the handoff SHALL include those associations or explicit unresolved markers.

### Requirement: Preservation fixes SHALL not change source authority boundaries

NPC/location preservation SHALL not grant generated summaries or downstream prose artifacts authority to repair source fidelity.

#### Scenario: MODULE_SUMMARY remains derived output

- **GIVEN** `MODULE_SUMMARY.md` contains a missing source NPC or location name
- **WHEN** source-fidelity benchmark checks module JSON artifacts
- **THEN** the summary content SHALL NOT count as source-fidelity repair input unless the benchmark explicitly defines it as an output-only presentation artifact.
