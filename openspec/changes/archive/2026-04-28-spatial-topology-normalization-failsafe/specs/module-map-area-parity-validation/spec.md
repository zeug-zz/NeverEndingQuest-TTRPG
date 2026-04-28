# Module Map Area Parity Validation

## Purpose

Ensure deterministic connector insertion keeps authored area files and map/graph artifacts synchronized while preserving validators as non-mutating checkers.

## MODIFIED Requirements

### Requirement: Parity validation SHALL include generated connector nodes

Map/area parity validation SHALL treat deterministic spatial-remediation connector nodes as ordinary module locations once they are written by the remediation pipeline. Validation SHALL verify that generated connectors exist consistently across authoritative area and map artifacts.

#### Scenario: Generated connector appears in area and map artifacts

- GIVEN topology normalization inserts connector C between authored rooms A and B
- WHEN map/area parity validation runs
- THEN C is present in the area location data
- AND C is present in the map/graph data used for navigation
- AND edges A-C and C-B are represented consistently
- AND the removed direct A-B edge does not remain as contradictory parity drift

### Requirement: Validation SHALL remain non-mutating

Parity validation SHALL report generated connector parity findings but SHALL NOT create, remove, or alter connector nodes during validation.

#### Scenario: Validator reports but does not repair connector drift

- GIVEN area data contains generated connector C
- AND map data is missing C
- WHEN parity validation runs
- THEN it reports parity drift
- AND it does not mutate the area or map file
- AND remediation must be run separately to repair the drift
