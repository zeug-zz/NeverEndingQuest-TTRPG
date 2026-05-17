## MODIFIED Requirements

### Requirement: Importer MUST parse Homebrew markdown into deterministic content-block structure

The importer MUST strip presentation markup (`css` fences, `<style>` blocks, rendering macros) and MUST extract semantic adventure structure from markdown headings, room blocks, map-key location blocks, and supported sub-location blocks.

#### Scenario: Room-chain markdown source is provided

- **WHEN** a Homebrewery-style adventure file contains `## Room <number>: <title>` sections
- **THEN** the importer extracts each room block into normalized room-compatible records in source order
- **AND** existing room-chain deterministic behavior remains compatible.

#### Scenario: Map-key markdown source is provided

- **WHEN** a Homebrewery-style adventure file contains numbered location headings such as `### 1. Brooksteps Inn`
- **THEN** the importer extracts each map-key location into normalized location records in source order
- **AND** it SHALL NOT require LLM output for location detection.

#### Scenario: Presentation markup is interleaved with content

- **WHEN** layout macros and style blocks are present in the source file
- **THEN** parser output excludes those artifacts from semantic room or location descriptions and mechanics fields.
