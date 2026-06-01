## ADDED Requirements

### Requirement: Plot Locations Resolve To Emitted Location IDs

Generated module plot points MUST reference location IDs that exist in the emitted area/location graph.

#### Scenario: Source map keys use different IDs than emitted graph
- **GIVEN** source-derived plot points reference source IDs such as `THE01`
- **AND** the emitted area graph uses IDs such as `A01`
- **WHEN** post-build finalization runs
- **THEN** plot point `location` fields SHALL be reconciled to emitted IDs
- **AND** validation SHALL NOT report room-graph missing-location errors for reconciled plot points.

### Requirement: Adventure Arc Remains Separate From Map-Key Locations

Reconciliation MUST NOT collapse adventure-arc trial plot points into map-key location rows.

#### Scenario: Numillian has trial arc and map-key locations
- **GIVEN** plot points include PP map-key entries and TRIAL adventure-arc entries
- **WHEN** location ID reconciliation runs
- **THEN** PP and TRIAL ID spaces SHALL remain distinct
- **AND** both sets SHALL retain schema-required fields.
