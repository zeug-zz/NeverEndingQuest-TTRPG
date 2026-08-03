# accurate-ingest-triage-regression-tests Specification

## Purpose
TBD - created by archiving change toolkit-accurate-ingest-source-atom-triage-hardening. Update Purpose after archive.
## Requirements
### Requirement: Source atom triage hardening SHALL be provider-free testable

The source atom triage hardening SHALL be covered by deterministic tests that require no live provider calls and do not mutate production module artifacts.

#### Scenario: Well-style false NPC fixture is covered

- **GIVEN** a synthetic Well-style markdown fixture contains table effect labels and effect prose
- **WHEN** tests run source manifest, triage, blueprint, and build-fidelity boundaries
- **THEN** the fixture SHALL prove those labels/prose do not become required NPC blockers.

#### Scenario: True NPC table fixture is covered

- **GIVEN** a synthetic identity table fixture contains real NPC names
- **WHEN** tests run source extraction and triage
- **THEN** those names SHALL remain eligible true NPC candidates.

#### Scenario: Existing final-editor and structural-routing tests remain green

- **GIVEN** this patch changes source extraction, triage, blueprint, or brief construction
- **WHEN** targeted verification runs
- **THEN** final-editor negative tests, final reconciliation tests, source-graph tests, and structural-routing tests SHALL still pass.

