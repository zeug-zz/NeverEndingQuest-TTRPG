## ADDED Requirements

### Requirement: Narrative enrichment SHALL preserve source locks

Narrative enrichment planning SHALL NOT authorize changes that reduce source fidelity or rewrite required source truth.

#### Scenario: Required source NPC would be renamed

- **GIVEN** a required source NPC is present in the source graph or build fidelity report
- **WHEN** an enrichment plan would rename or replace that NPC
- **THEN** the plan SHALL be blocked
- **AND** no enrichment SHALL be applied.

#### Scenario: Required source location would be replaced

- **GIVEN** a required source location is present in the source graph or build fidelity report
- **WHEN** an enrichment plan would rename, remove, or replace that location
- **THEN** the plan SHALL be blocked.

#### Scenario: Plot or puzzle topology would change

- **GIVEN** source plot beats, puzzle rules, or clue dependencies are source-locked
- **WHEN** enrichment would alter topology, solution rules, or dependencies
- **THEN** the plan SHALL be blocked
- **AND** source evidence SHALL remain authoritative.

#### Scenario: Source fidelity has blockers

- **GIVEN** build/source fidelity status is blocked or failed
- **WHEN** non-`none` enrichment planning is requested
- **THEN** enrichment planning SHALL be blocked until source fidelity blockers are resolved or explicitly waived by a later reviewed contract.
