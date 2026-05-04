## MODIFIED Requirements

### Requirement: Canonical backup coverage SHALL be complete before live files are untracked
The system SHALL NOT rely on untracked live files as the only remaining copy of mutable module content. Published modules SHALL expose tracked canonical backup coverage sufficient for fresh-clone hydration and validation. Live map files SHALL be treated as tracked static structure, not mutable runtime state, unless a future change explicitly makes maps gameplay-mutable.

#### Scenario: Module lacks canonical backup coverage
- **WHEN** a shipped module is missing required `_BU` coverage for a live mutable area or module plot file
- **THEN** tracking cleanup for that file family SHALL stop until canonical coverage is added
- **AND** rollout SHALL treat the missing backup as a blocker rather than silently proceeding

#### Scenario: Published module canonical backup is gitignored
- **WHEN** a module is named for publication in README or the committed module catalog
- **AND** required canonical backup files such as `areas/*_BU.json`, `module_plot_BU.json`, or `party_tracker_BU.json` are ignored by `.gitignore`
- **THEN** the git contract SHALL be considered invalid
- **AND** the module SHALL NOT be committed or pushed as publish-ready until those canonical files are visible to normal git staging

#### Scenario: Published module live map is gitignored
- **WHEN** a module is named for publication in README or `modules/published_modules.json`
- **AND** a required `map_*.json` file is ignored by `.gitignore`
- **THEN** the git contract SHALL be considered invalid
- **AND** the module SHALL NOT rely on runtime map hydration to compensate

#### Scenario: Fresh clone hydrates ignored live state from tracked canonical files
- **WHEN** a colleague fresh-clones the repository and launches a published module
- **THEN** ignored live runtime files SHALL be recreated from tracked canonical artifacts where hydration is required
- **AND** gameplay SHALL NOT depend on untracked dev-laptop runtime copies being present
