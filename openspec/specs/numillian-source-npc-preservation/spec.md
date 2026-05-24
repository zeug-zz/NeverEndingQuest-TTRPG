# numillian-source-npc-preservation Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-numillian-npc-location-preservation. Update Purpose after archive.
## Requirements
### Requirement: Numillian source NPCs SHALL be preserved or explicitly unresolved

The accurate-ingest Numillian path SHALL preserve benchmark-required source NPC names in benchmark-visible module artifacts or record explicit unresolved-source blockers. It SHALL NOT silently omit required source NPCs while reporting clean source fidelity.

#### Scenario: Current benchmark NPC baseline is captured

- **GIVEN** the current production Numillian benchmark report
- **WHEN** regression locks evaluate the NPC preservation category
- **THEN** the test SHALL document that the current output is blocked at `1/23` found source NPCs.

#### Scenario: Required NPC omissions remain blockers

- **GIVEN** a required source NPC from the benchmark fixture is missing from benchmark-visible module artifacts
- **WHEN** source-fidelity status is composed
- **THEN** the missing NPC SHALL remain a blocker unless an explicit waiver contract exists.

#### Scenario: Valid minor NPCs are preserved with bindings

- **GIVEN** source text identifies Dog-Growl, Book-shut, and Deflation as Rookery residents
- **WHEN** the NPC preservation path builds source NPC artifacts
- **THEN** each NPC SHALL be preserved as a source NPC
- **AND** each NPC SHALL include `The Rookery` or an approved canonical alias as a location binding.

### Requirement: Prose phrases SHALL remain rejected as actor records

The NPC preservation path SHALL NOT improve preservation counts by promoting narrative phrases, table labels, or prose assertions into actors.

#### Scenario: Narrative assertion remains filtered

- **GIVEN** the source phrase `but this is not true`
- **WHEN** source NPC artifacts are generated or repaired
- **THEN** the phrase SHALL NOT appear as an NPC, monster, scene actor, semantic NPC authority entry, or seed actor.

