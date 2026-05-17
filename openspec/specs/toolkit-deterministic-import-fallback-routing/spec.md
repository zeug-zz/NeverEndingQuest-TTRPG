# toolkit-deterministic-import-fallback-routing Specification

## Purpose
Deterministic import fallback routing when structured content blocks cannot be safely parsed.

## Requirements
### Requirement: Deterministic import SHALL fail closed when structure is insufficient

The deterministic import path SHALL NOT emit partial module artifacts when no safe room, map-key, or sub-location content blocks are found.

#### Scenario: Source has no supported structured headings

- **GIVEN** source markdown is readable
- **AND** it contains no supported deterministic room or location headings
- **WHEN** deterministic import runs
- **THEN** it SHALL return a clear error or fallback status such as `deterministic_insufficient_structure`
- **AND** it SHALL NOT create module artifacts.

#### Scenario: Source has ambiguous heading structure

- **GIVEN** source markdown contains numbered headings that cannot be safely classified as locations
- **WHEN** deterministic import runs
- **THEN** it SHALL report ambiguous deterministic structure
- **AND** it SHALL NOT silently emit an incomplete module.

### Requirement: Deterministic import fallback SHALL preserve existing AI-driven path availability

Failure to parse deterministic structure SHALL NOT remove or break the existing non-deterministic AI-driven import path.

#### Scenario: Caller chooses AI-driven import

- **GIVEN** `use_deterministic` is false
- **WHEN** import runs
- **THEN** existing AI-driven import behavior SHALL remain available
- **AND** deterministic parser failures SHALL NOT block that path.

#### Scenario: Higher-level accurate-ingest pipeline owns fallback

- **GIVEN** deterministic parsing reports insufficient structure
- **WHEN** a higher-level pipeline supports multi-pass LLM normalization fallback
- **THEN** deterministic import SHALL provide enough status detail for that pipeline to choose fallback
- **AND** it SHALL NOT pretend deterministic parsing succeeded.
