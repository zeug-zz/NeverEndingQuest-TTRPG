# toolkit-narrative-enrichment-no-auto-apply Specification

## Purpose
First implementation auto-apply guard - plan is review-only, auto_apply is false, no automatic module mutation path.
## Requirements
### Requirement: Narrative enrichment SHALL NOT auto-apply in the first implementation

The first narrative enrichment placeholder implementation SHALL keep `auto_apply` false and SHALL NOT expose an automatic module mutation path.

#### Scenario: Non-none profile planned

- **GIVEN** a non-`none` enrichment profile is selected
- **AND** source/build fidelity has no blockers
- **WHEN** the plan artifact is generated
- **THEN** the plan SHALL remain reviewable only
- **AND** `auto_apply` SHALL be false
- **AND** module files SHALL remain unchanged.

#### Scenario: User expects enrichment output

- **GIVEN** a user selects an enrichment profile
- **WHEN** this first implementation runs
- **THEN** the toolkit SHALL record the plan metadata only
- **AND** it SHALL NOT generate enriched prose or patches.

