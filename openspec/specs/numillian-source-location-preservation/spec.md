# numillian-source-location-preservation Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-numillian-npc-location-preservation. Update Purpose after archive.
## Requirements
### Requirement: Numillian source locations SHALL be preserved or explicitly unresolved

The accurate-ingest Numillian path SHALL preserve benchmark-required source location names or approved aliases in benchmark-visible module artifacts. Missing required source locations SHALL remain source-fidelity blockers unless explicitly waived.

#### Scenario: Current benchmark location baseline is captured

- **GIVEN** the current production Numillian benchmark report
- **WHEN** regression locks evaluate the location preservation category
- **THEN** the test SHALL document that the current output is blocked at `0/13` found source locations.

#### Scenario: Required source location names are benchmark-visible

- **GIVEN** a required source location such as `The Rookery`, `Brooksteps Inn`, or `Temple of Broance`
- **WHEN** the source-enhanced build or support artifact path completes
- **THEN** the final module artifacts SHALL expose the source location name or approved alias in a benchmark-visible field.

#### Scenario: Unplaced source locations are explicit blockers

- **GIVEN** a source keyed location cannot be safely placed in the generated module
- **WHEN** build-fidelity status is reported
- **THEN** the location SHALL be recorded as an unresolved source location blocker
- **AND** the system SHALL NOT silently replace it with a generic generated location.

### Requirement: Source location identity SHALL include evidence metadata

Each preserved source location SHALL carry enough evidence metadata to remain auditable through the build path.

#### Scenario: Source refs survive location preservation path

- **GIVEN** a source keyed location in the source graph or normalized packet
- **WHEN** it is propagated into blueprint, handoff, support, or final artifacts
- **THEN** the propagated record SHALL include source refs, source order, source grouping, or equivalent provenance metadata.

