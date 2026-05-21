## ADDED Requirements

### Requirement: Enrichment passes SHALL support deterministic input hashes for cacheable provider work

Blueprint enrichment SHALL support avoiding repeated provider calls for unchanged pass inputs by deriving deterministic cache keys from pass name, target identity, source refs, bounded excerpts, and prompt contract version when a pass is cacheable.

#### Scenario: Same pass input can reuse cached result

- **GIVEN** a pass input hash matches a previously cached enrichment response
- **WHEN** enrichment runs
- **THEN** the implementation SHALL be able to reuse the cached result instead of making another provider call
- **AND** telemetry SHALL report a cache hit when cached reuse occurs.

#### Scenario: Changed source excerpt invalidates cache

- **GIVEN** source excerpt text, source hash, prompt contract version, or target identity changes
- **WHEN** enrichment derives the input hash
- **THEN** the cache key SHALL change
- **AND** the pass SHALL NOT reuse stale provider output.

### Requirement: Enrichment reports SHALL expose pass telemetry

Blueprint enrichment reports SHALL expose enough pass metadata to audit provider use and failure behavior without breaking existing consumers.

#### Scenario: Pass telemetry is reported

- **WHEN** enrichment report generation runs
- **THEN** the report SHALL include or preserve pass-level metadata for provider call count, cache hit/miss count, parse failures, rejected patch count, applied patch count, warnings, errors, and status when available.

#### Scenario: Missing telemetry does not break consumers

- **GIVEN** legacy enrichment results lack cache or provider telemetry
- **WHEN** report generation runs
- **THEN** existing report consumers SHALL continue to receive status, reason, counts, warnings, and errors
- **AND** missing optional telemetry SHALL NOT raise an exception.
