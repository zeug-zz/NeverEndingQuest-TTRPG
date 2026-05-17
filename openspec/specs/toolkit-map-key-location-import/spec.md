# toolkit-map-key-location-import Specification

## Purpose
Map-key location record conversion and NEQ artifact emission for deterministic Homebrewery import.

## Requirements
### Requirement: Map-key content blocks SHALL convert to importer-compatible location records

Map-key content blocks SHALL be converted into the same location/room-compatible record shape consumed by existing deterministic emitters.

#### Scenario: Map-key block is converted

- **GIVEN** a parsed map-key block for `### 1. Brooksteps Inn`
- **WHEN** importer-compatible records are built
- **THEN** the record SHALL include `source_room_number=1`
- **AND** it SHALL include `source_room_title="Brooksteps Inn"`
- **AND** it SHALL include `name` containing `Brooksteps Inn`
- **AND** it SHALL include `raw_content` from the source block.

#### Scenario: Existing emitters consume map-key records

- **GIVEN** map-key records have been generated
- **WHEN** deterministic NEQ artifact emission runs
- **THEN** module context, area, map, plot, and backup artifacts SHALL be emitted through the existing deterministic emitter path
- **AND** schema expectations SHALL remain compatible with room-chain outputs.

### Requirement: Map-key import SHALL preserve source labels separately from NEQ IDs

Source map-key numbers SHALL be preserved as source metadata and SHALL NOT be used as NEQ location IDs.

#### Scenario: Map-key number is out of sequence

- **GIVEN** source headings include `### 100. Finale`
- **WHEN** NEQ IDs are generated
- **THEN** the emitted location ID SHALL be sequential by source order
- **AND** source number `100` SHALL remain available as display/provenance metadata.

### Requirement: Sub-locations SHALL retain parent context

Sub-location blocks SHALL preserve their parent heading context whether emitted as separate NEQ locations or nested metadata.

#### Scenario: Sub-location emitted as a location

- **GIVEN** `#### 1. Cellar` appears under `### 2. Brooksteps Inn`
- **WHEN** deterministic records are built
- **THEN** the cellar record SHALL preserve parent title `Brooksteps Inn` or equivalent parent reference
- **AND** source order SHALL place the cellar after its parent.
