## ADDED Requirements

### Requirement: LLM enrichment output SHALL be JSON-only and validated before application

Provider-backed blueprint enrichment SHALL accept only JSON-only responses and SHALL validate parsed output before converting it into patches.

#### Scenario: Valid JSON output becomes patch candidates

- **GIVEN** an enrichment provider returns valid JSON matching the pass contract
- **WHEN** the response is parsed
- **THEN** the pipeline SHALL convert allowed field updates into enrichment patch candidates
- **AND** those patch candidates SHALL still pass Python patch validation before application.

#### Scenario: Invalid JSON degrades without mutation

- **GIVEN** an enrichment provider returns malformed JSON or non-JSON prose
- **WHEN** parsing fails
- **THEN** the pass SHALL return degraded or failed diagnostics
- **AND** no patch from that response SHALL be applied.

#### Scenario: Unknown or unsafe response fields are rejected

- **GIVEN** parsed provider JSON contains unknown patch shape, missing required identity fields, missing source refs, or unsafe target paths
- **WHEN** output validation runs
- **THEN** those updates SHALL be rejected with diagnostics
- **AND** the target blueprint/module artifacts SHALL NOT be corrupted.

### Requirement: LLM enrichment SHALL preserve Python structural authority

Provider output SHALL NOT be able to rename source entities, change IDs, alter connectivity, rewrite puzzle rules, change puzzle solutions, or invent replacement main plotlines.

#### Scenario: Structural mutation proposal is rejected

- **GIVEN** provider JSON proposes a patch to names, IDs, coordinates, connectivity, dependencies, puzzle rules, puzzle solutions, failure consequences, or replacement main plotlines
- **WHEN** patch validation runs
- **THEN** the patch SHALL be rejected
- **AND** rejection SHALL be included in pass/report diagnostics
- **AND** no structural mutation SHALL be written.
