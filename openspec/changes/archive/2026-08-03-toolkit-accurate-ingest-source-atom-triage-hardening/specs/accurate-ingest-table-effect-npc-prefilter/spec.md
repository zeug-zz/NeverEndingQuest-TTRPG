## ADDED Requirements

### Requirement: Table effect cells SHALL NOT become required NPC atoms

Accurate-ingest source extraction SHALL NOT promote table cells to NPC/entity candidates when the table headers or nearby section context identify the cells as effects, complications, results, descriptions, spells, triggers, passive elements, active elements, or other trap/mechanics text.

#### Scenario: Well trap effect labels are not NPC candidates

- **GIVEN** source markdown contains a trap/effects table with cells named `Awaken`, `Menace`, `Enrage`, `Enthrall`, `Irradiate`, and `Overwhelm`
- **WHEN** the source manifest and source graph are built
- **THEN** those labels SHALL NOT appear as required `npc` atoms
- **AND** they MAY be preserved as mechanics, table effects, DM guidance, or non-actor evidence.

#### Scenario: Effect prose is not an NPC candidate

- **GIVEN** source markdown contains table cells such as `Mundane objects worth at least 1 gp become sentient and hostile.`
- **WHEN** entity candidates are extracted
- **THEN** the full sentence SHALL NOT be registered as an NPC candidate
- **AND** it SHALL NOT later produce a `Required npc` source-fidelity blocker.

#### Scenario: Identity-bearing tables still extract real NPC names

- **GIVEN** source markdown contains an identity table with headers such as `Name`, `NPC`, `Character`, `Creature`, or `Faction`
- **AND** rows include names such as `Wayne`, `Irene Laughing-Eyes`, or `Treever`
- **WHEN** entity candidates are extracted
- **THEN** those names SHALL remain eligible NPC/entity candidates if they pass existing name heuristics.

## SHOULD Guidance

- Prefer table-header classification helpers over broad hardcoded name exclusions.
- Avoid filtering by exact Well-only strings except in tests.
