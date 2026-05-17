## ADDED Requirements

### Requirement: Deterministic import SHALL preserve source metadata for source graph reconstruction

Deterministic content-block import SHALL preserve enough source metadata for later source graph, fidelity, and benchmark stages to map emitted module content back to source headings.

#### Scenario: Content block metadata is present

- **GIVEN** deterministic parsing extracts a map-key location
- **WHEN** the intermediate adventure structure is built
- **THEN** the record SHALL preserve source heading text, source heading level, source block style, source number, source title, and raw content.

#### Scenario: Dry-run preview runs on structured source

- **GIVEN** deterministic import runs in dry-run mode against map-key source
- **WHEN** preview data is returned
- **THEN** preview SHALL include the parsed block count or location count
- **AND** it SHALL NOT require LLM normalization.

### Requirement: Deterministic import SHALL preserve source graph helper compatibility

When source graph helper APIs are available and an artifact workspace is available, deterministic import SHALL remain compatible with those helpers and SHOULD write or preserve source graph/source manifest artifacts without inventing a new incompatible schema.

#### Scenario: Source graph helper unavailable

- **GIVEN** deterministic import runs without source graph helper availability
- **WHEN** content-block records are generated
- **THEN** import SHALL still preserve source metadata in the intermediate records
- **AND** it SHALL NOT fail solely because source graph artifact writing is unavailable.

#### Scenario: Source graph helper available

- **GIVEN** deterministic import can call existing source graph helpers safely
- **WHEN** deterministic import runs
- **THEN** it SHOULD produce source graph/source manifest artifacts compatible with existing accurate-ingest review and fidelity stages.
