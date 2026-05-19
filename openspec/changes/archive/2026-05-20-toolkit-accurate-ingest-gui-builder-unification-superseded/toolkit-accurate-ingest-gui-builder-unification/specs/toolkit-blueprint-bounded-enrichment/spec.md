## ADDED Requirements

### Requirement: Blueprint enrichment SHALL use validated patch operations

Blueprint enrichment SHALL modify seeded modules only through validated patch operations tied to blueprint IDs, source refs, target files, JSON paths, and approved fields.

#### Scenario: Approved text field patch is accepted

- **GIVEN** a patch targets a location `dmInstructions` field listed in the blueprint enrichment allowlist
- **AND** the patch includes a valid blueprint ID and source refs
- **WHEN** patch validation runs
- **THEN** the patch SHALL be accepted
- **AND** it SHALL be eligible for atomic write.

#### Scenario: Structure mutation patch is rejected

- **GIVEN** a patch attempts to change a location name, location ID, connectivity, puzzle solution, plot dependency, or source refs
- **WHEN** patch validation runs
- **THEN** the patch SHALL be rejected
- **AND** it SHALL NOT mutate module files.

### Requirement: Enrichment SHALL be feature-flagged and fail safe

LLM enrichment SHALL run only when `ENABLE_ACCURATE_INGEST_BLUEPRINT_ENRICHMENT` is enabled. Disabled or failed enrichment SHALL preserve seeded module content.

#### Scenario: Enrichment flag disabled

- **GIVEN** blueprint-native build is enabled
- **AND** blueprint enrichment is disabled
- **WHEN** the enrichment stage runs
- **THEN** it SHALL return a skipped status
- **AND** it SHALL NOT call an LLM provider
- **AND** it SHALL NOT block seeded module readiness by itself.

#### Scenario: Provider failure preserves seed

- **GIVEN** blueprint enrichment is enabled
- **AND** the provider call fails
- **WHEN** the enrichment stage handles the failure
- **THEN** it SHALL return a degraded enrichment report
- **AND** seeded module files SHALL remain valid and unmodified by failed patches.

### Requirement: Enrichment SHALL preserve source fidelity

Enrichment SHALL deepen descriptions and narrative only inside source bounds and SHALL NOT reduce source-fidelity status silently.

#### Scenario: Accepted enrichment is audited after write

- **GIVEN** accepted enrichment patches are applied
- **WHEN** build-fidelity checks run after enrichment
- **THEN** source-locked locations, NPCs, plot beats, puzzle rules, and clues SHALL still be present
- **AND** any source-fidelity regression SHALL block or warn according to existing fidelity gates.
