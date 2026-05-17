# toolkit-narrative-enrichment-plan-artifact Specification

## Purpose
Enrichment plan artifact shape - artifact-only plan with profile, status, source locks, eligible fields, field budgets, blockers, warnings, and artifact refs. No module mutation.
## Requirements
### Requirement: Narrative enrichment plan SHALL be artifact-only in the first implementation

The toolkit SHALL generate or reserve `narrative_enrichment_plan.json` as a reviewable artifact only. It SHALL NOT mutate generated module data or apply field patches in the first implementation.

#### Scenario: Plan artifact generated after non-blocking fidelity

- **GIVEN** an accurate-ingest workspace has completed build/source fidelity with no blockers
- **WHEN** narrative enrichment planning runs
- **THEN** `narrative_enrichment_plan.json` MAY be persisted
- **AND** it SHALL include profile, status, source locks, eligible fields, field budgets, blockers, warnings, and artifact refs.

#### Scenario: Accurate ingest completes without artifact

- **GIVEN** enrichment profile is `none`
- **WHEN** accurate ingest completes
- **THEN** absence of `narrative_enrichment_plan.json` SHALL NOT fail the build or publication readiness.

#### Scenario: Artifact does not apply patches

- **GIVEN** a narrative enrichment plan exists
- **WHEN** the toolkit persists the plan
- **THEN** it SHALL NOT write changes to module JSON files
- **AND** it SHALL NOT call a provider to generate enriched prose.

