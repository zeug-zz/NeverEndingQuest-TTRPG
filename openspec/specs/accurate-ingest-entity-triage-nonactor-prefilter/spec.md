# accurate-ingest-entity-triage-nonactor-prefilter Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-source-atom-triage-hardening. Update Purpose after archive.
## Requirements
### Requirement: Entity triage SHALL reject obvious non-actor candidates before blueprinting

The entity candidate triage layer SHALL reject or reclassify obvious non-actor candidates before they can enter `npc_roster` construction.

#### Scenario: Full-sentence candidate is a narrative phrase

- **GIVEN** an entity candidate text contains a sentence or long clause rather than a name
- **WHEN** `build_prefilter_decision(...)` evaluates the candidate
- **THEN** the candidate SHALL receive a reject or non-actor decision
- **AND** it SHALL NOT be treated as `true_npc`.

#### Scenario: Trap effect verbs are non-actors

- **GIVEN** one-word capitalized candidates such as `Awaken`, `Menace`, `Enrage`, `Enthrall`, `Irradiate`, or `Overwhelm`
- **AND** their source refs or context indicate trap, effect, table, spell, or mechanics material
- **WHEN** entity candidate triage runs
- **THEN** those candidates SHALL be rejected or reclassified as non-actor types
- **AND** they SHALL NOT create underbound NPC findings.

#### Scenario: True one-word NPC names are preserved

- **GIVEN** a one-word candidate appears under identity-bearing context or has actor/source-role evidence
- **WHEN** entity candidate triage runs
- **THEN** the candidate SHALL NOT be rejected solely because it has one word.

