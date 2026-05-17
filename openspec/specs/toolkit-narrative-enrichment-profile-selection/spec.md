# toolkit-narrative-enrichment-profile-selection Specification

## Purpose
Enrichment profile vocabulary and default behavior - defaults to none, supported profiles, unsupported rejection.
## Requirements
### Requirement: Narrative enrichment profile selection SHALL default to none

Accurate-ingest narrative enrichment planning SHALL default to profile `none` unless a reviewed configuration or user action explicitly selects another supported profile.

#### Scenario: No profile selected

- **GIVEN** an accurate-ingest build has completed source/build fidelity checks
- **AND** no enrichment profile has been selected
- **WHEN** enrichment planning is evaluated
- **THEN** the selected profile SHALL be `none`
- **AND** accurate ingest SHALL remain complete without enrichment.

#### Scenario: Supported profile selected

- **GIVEN** a supported profile value is selected
- **WHEN** enrichment planning records profile metadata
- **THEN** the profile SHALL be one of `none`, `three_stance_single_turn`, `five_playline_stateful`, or `custom`.

#### Scenario: Unsupported profile rejected

- **GIVEN** an unsupported enrichment profile value is provided
- **WHEN** enrichment planning validates the profile
- **THEN** planning SHALL reject or block the unsupported profile
- **AND** it SHALL NOT apply enrichment.

