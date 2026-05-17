# homebrew-md-sequential-module-ingest Specification

## Purpose
Deterministic sequential module ingest from Homebrew markdown sources into NEQ-compatible module artifacts.

## Requirements
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

### Requirement: Importer MUST emit NEQ sequential IDs regardless of source room numbering
Generated module artifacts MUST use deterministic sequential NEQ IDs for areas and locations, and source room numbering MUST remain display metadata only.

#### Scenario: Source includes outlier room number
- **WHEN** source contains `Room 100` after `Room 22`
- **THEN** generated location IDs remain sequential (`...23`) while display name/metadata preserves `Room 100`

#### Scenario: Same source is ingested twice
- **WHEN** identical source content is ingested with same module slug
- **THEN** generated area/location IDs are identical across runs

### Requirement: Importer SHALL bound LLM usage to enrichment-only fields
Deterministic extraction, ordering, and ID assignment SHALL NOT depend on LLM output. LLM, when enabled, SHALL only enrich sparse narrative fields after deterministic scaffold creation.

#### Scenario: LLM enrichment disabled
- **WHEN** ingest runs with `--no-llm` or equivalent flag
- **THEN** parser and emitter still produce schema-valid deterministic scaffold output

#### Scenario: LLM enrichment enabled
- **WHEN** enrichment runs after deterministic scaffold
- **THEN** IDs and room ordering remain unchanged while narrative fields may be improved

