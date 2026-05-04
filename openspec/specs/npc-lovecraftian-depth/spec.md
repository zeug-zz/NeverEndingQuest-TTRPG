# npc-lovecraftian-depth Specification

## Purpose
TBD - created by archiving change ancients-lab-lovecraftian-narrative. Update Purpose after archive.
## Requirements
### Requirement: Empty NPC Descriptions Must Be Populated

The following NPCs SHALL have their `description` field populated with Lovecraftian depth:

| NPC | Current | Target |
|-----|---------|--------|
| `the_thing` | 0 chars | ~400 chars -- multi-interpretation entity description |
| `facility_security_system` | 0 chars | ~300 chars -- Aegis as fractured AI |
| `mutated_scavenger_leader` | 0 chars | ~250 chars -- Varn's playline-specific truth |
| `security_construct` | 0 chars | ~250 chars -- Warden-3's corrupted memory |
| `mutant_scavenger_lieutenant` | 0 chars | ~300 chars -- Grahl's multi-state condition |
| `edda_coppervein` | 0 chars | ~250 chars -- post-survival interpretation |

#### Scenario: Narrator loads The Thing

- **GIVEN** the Narrator has loaded `module_context.json` for `The_Ancients_Lab`
- **WHEN** the Narrator reads `npcs.the_thing.description`
- **THEN** the description SHALL contain at least 200 characters
- **AND** the description SHALL present the entity as interpretable through multiple playlines without committing to one

#### Scenario: All NPCs have non-empty descriptions

- **GIVEN** `module_context.json` for `The_Ancients_Lab`
- **WHEN** any NPC entry is inspected
- **THEN** `description` SHALL NOT be an empty string
- **AND** `description` SHALL have minimum 150 characters for named plot-relevant NPCs

### Requirement: Short NPC Descriptions Must Be Expanded

Existing descriptions under 250 chars SHALL be expanded:

| NPC | Current | Target |
|-----|---------|--------|
| `rambling_dwarven_survivor` | 208 chars | ~350 chars |
| `archivist_automaton` | 221 chars | ~400 chars |
| `damaged_security_overseer` | 208 chars | ~350 chars |

#### Scenario: Expanded descriptions preserve original content

- **GIVEN** an NPC with an existing description
- **WHEN** the description is expanded
- **THEN** the original text SHALL be preserved as the opening of the expanded description
- **AND** the expansion SHALL add Lovecraftian depth and multi-playline interpretation

### Requirement: Role and Faction Fields Must Be Populated

All 9 NPCs SHALL have their `role` and `faction` fields populated:

- `role` SHALL contain a brief role descriptor with multi-playline hints (~80 chars)
- `faction` SHALL identify the NPC's alignment (`Dreamer-aligned`, `Containment-aligned`, `Communion-aligned`, `Independent`, `Mirror-reflection`) (~40 chars)

#### Scenario: Role fields guide Narrator interpretation

- **GIVEN** the Narrator has loaded an NPC with a populated `role` field
- **WHEN** the Narrator interprets the NPC's behavior
- **THEN** the `role` field SHALL provide both the NPC's primary function and secondary playline interpretations

