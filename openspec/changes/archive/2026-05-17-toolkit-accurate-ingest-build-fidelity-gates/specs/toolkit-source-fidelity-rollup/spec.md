## ADDED Requirements

### Requirement: Source fidelity rollup SHALL summarize normalization, blueprint, and build fidelity outcomes

The toolkit SHALL produce a compact final `source_fidelity_report.json` rollup for accurate-ingest builds when enough upstream artifacts exist.

#### Scenario: Final rollup includes all fidelity stages

- **GIVEN** normalization fidelity, blueprint report, and build fidelity report artifacts exist
- **WHEN** source fidelity rollup generation runs
- **THEN** `source_fidelity_report.json` SHALL include each stage status
- **AND** it SHALL include final blocker/warning counts
- **AND** it SHALL include artifact paths for source review.

#### Scenario: Final rollup preserves blocked state

- **GIVEN** build fidelity report is blocked or failed
- **WHEN** rollup generation runs
- **THEN** the final rollup SHALL preserve the blocked/failed status
- **AND** it SHALL retain compact blocker reasons.

### Requirement: Source fidelity rollup SHALL be artifact-only

The source fidelity rollup SHALL be generated from existing workspace artifacts and generated module files without calling LLM providers.

#### Scenario: Rollup generation does not call providers

- **GIVEN** source fidelity rollup generation runs
- **THEN** it SHALL NOT call chat, image, or other provider clients
- **AND** it SHALL NOT mutate generated module content.
