# numillian-source-fidelity-release-prerequisite Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-numillian-npc-location-preservation. Update Purpose after archive.
## Requirements
### Requirement: Numillian release proof SHALL wait for NPC/location preservation resolution

The final Numillian release-proof change SHALL NOT claim release readiness while source-fidelity status is blocked by NPC or location preservation failures.

#### Scenario: Release proof is blocked by NPC preservation

- **GIVEN** `npc_preservation` is `blocked`
- **WHEN** release-proof readiness is evaluated
- **THEN** the release proof SHALL report blocked or not-ready status.

#### Scenario: Release proof is blocked by location preservation

- **GIVEN** `location_preservation` is `blocked`
- **WHEN** release-proof readiness is evaluated
- **THEN** the release proof SHALL report blocked or not-ready status.

#### Scenario: Puzzle preservation remains protected

- **GIVEN** the archived bridge fix made `puzzle_preservation` pass at `3/3`
- **WHEN** NPC/location preservation changes are applied
- **THEN** `skull_riddle`, `flooding_room`, and `kill_the_dog_mindscape` SHALL remain matched by the benchmark.

### Requirement: Publication SHALL not ignore blocked source fidelity

Accurate-ingest modules SHALL carry source-fidelity status into publishability composition. Blocked NPC/location preservation SHALL prevent clean publication unless an explicit waiver contract applies.

#### Scenario: Publishability consumes final source-fidelity status

- **GIVEN** final source-fidelity status is `blocked`
- **WHEN** publishability audit composes readiness, semantic, and source-fidelity dimensions
- **THEN** clean publishability SHALL be blocked.

