# toolkit-deterministic-content-block-parsing Specification

## Purpose
Deterministic content-block heading parsing for Homebrewery import without provider calls.

## Requirements
### Requirement: Deterministic parser SHALL recognize supported content-block heading styles

The deterministic Homebrewery importer SHALL parse supported room, map-key location, and sub-location heading styles into source-ordered content blocks without provider calls.

#### Scenario: Existing room heading is parsed

- **GIVEN** markdown contains `## Room 1: The Entrance`
- **WHEN** deterministic content-block parsing runs
- **THEN** it SHALL produce a block with `source_block_kind="room"`
- **AND** it SHALL preserve source number `1`
- **AND** it SHALL preserve title `The Entrance`.

#### Scenario: Dot map-key heading is parsed

- **GIVEN** markdown contains `### 1. Brooksteps Inn`
- **WHEN** deterministic content-block parsing runs
- **THEN** it SHALL produce a block with `source_block_kind="map_key_location"`
- **AND** it SHALL preserve source number `1`
- **AND** it SHALL preserve title `Brooksteps Inn`.

#### Scenario: Dash map-key heading is parsed

- **GIVEN** markdown contains `### 1 - Brooksteps Inn`
- **WHEN** deterministic content-block parsing runs
- **THEN** it SHALL produce a block with `source_block_kind="map_key_location"`
- **AND** it SHALL preserve source number `1`
- **AND** it SHALL preserve title `Brooksteps Inn`.

#### Scenario: Sub-location heading is parsed

- **GIVEN** markdown contains `#### 1. Cellar Stairs` under a parsed location section
- **WHEN** deterministic content-block parsing runs
- **THEN** it SHALL produce a source-ordered sub-location block or equivalent parent-linked location record
- **AND** it SHALL preserve parent context.

### Requirement: Deterministic parser SHALL preserve source order

Content-block parsing SHALL preserve the order in which supported headings appear in source text. Numeric labels SHALL be provenance/display metadata only.

#### Scenario: Out-of-order numbering appears in source

- **GIVEN** source headings appear as `### 1. First`, `### 4. Fourth`, then `### 2. Second`
- **WHEN** deterministic content-block parsing runs
- **THEN** output block order SHALL be `First`, `Fourth`, `Second`
- **AND** it SHALL NOT sort by numeric label.

### Requirement: Deterministic parser SHALL avoid prose and bullet false positives

Content-block parsing SHALL only treat markdown headings as deterministic location headings. It SHALL NOT promote numbered bullet lists or prose sentences into location blocks.

#### Scenario: Numbered list appears inside description

- **GIVEN** a location description contains `1. Find the key` as a list item
- **WHEN** deterministic content-block parsing runs
- **THEN** that list item SHALL NOT become a location block.
