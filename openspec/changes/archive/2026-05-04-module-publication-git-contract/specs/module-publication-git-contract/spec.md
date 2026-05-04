## ADDED Requirements

### Requirement: Published module directories SHALL be git-visible by normal staging
The repository SHALL make intentionally published module directories visible to normal `git status` and `git add` without requiring `git add -f` for canonical module artifacts.

#### Scenario: README-public module directory is allowlisted
- **WHEN** a module is named in `README.md` as a public/playable module
- **THEN** `.gitignore` SHALL include rules that allow normal git discovery of that module's canonical publication artifacts
- **AND** `git add -f` SHALL NOT be required for those canonical artifacts

#### Scenario: Draft module remains ignored by default
- **WHEN** a local module directory is not intentionally published
- **THEN** the default `.gitignore` rules SHALL keep that module hidden from normal git staging
- **AND** the module SHALL NOT appear in normal `git status` because it is present on the dev laptop

### Requirement: Canonical module artifacts SHALL be tracked for published modules
Published modules SHALL expose the canonical artifacts required for colleague-facing fresh clones, validation, publication audit review, runtime hydration, and static module navigation.

#### Scenario: Canonical artifacts are not ignored
- **WHEN** `git check-ignore -v` is run on canonical files for a published module
- **THEN** files such as `module_context.json`, `module_context_BU.json`, `module_plot_BU.json`, `party_tracker_BU.json`, `validation_report.json`, `toolkit_build_report.json`, `areas/*_BU.json`, `map_*.json`, `map_*_BU.json`, `monsters/*.json`, and module-local `media/**` SHALL NOT be ignored

#### Scenario: Live map files are tracked as static module structure
- **WHEN** a published module includes `map_*.json` files
- **THEN** those live map files SHALL be tracked as authored static module structure
- **AND** fresh clones SHALL NOT require map hydration before module map data is available

#### Scenario: Public docs are not ignored
- **WHEN** a published module includes `README.md`, `PLAYER_GUIDE.md`, or `MODULE_SUMMARY.md`
- **THEN** those public/operator-facing docs SHALL NOT be ignored by a later broad markdown pattern

### Requirement: Runtime module files SHALL remain ignored for published modules
Published module allowlisting SHALL NOT make dev-laptop runtime gameplay state eligible for accidental commit.

#### Scenario: Live mutable runtime files remain ignored
- **WHEN** `git check-ignore -v` is run on live runtime files for a published module
- **THEN** files such as `areas/*.json` except `*_BU.json`, `module_plot.json`, `party_tracker.json`, `player_quests_*.json`, and `encounters/**` SHALL remain ignored

#### Scenario: Backup files remain ignored
- **WHEN** a published module directory contains `.bak`, `.backup`, `backup*/`, or timestamped pre-integration backup files
- **THEN** those backup artifacts SHALL remain ignored or be removed before commit

### Requirement: Public module catalog state SHALL match README-public modules
The repository SHALL provide a committed `modules/published_modules.json` public module catalog that reflects modules named for colleague/tester use, while local runtime catalog files remain ignored.

#### Scenario: README module has catalog entry
- **WHEN** a module is listed publicly in `README.md`
- **THEN** `modules/published_modules.json` SHALL include that module slug and display name
- **AND** the catalog SHALL NOT refer to an obsolete pre-rename module slug

#### Scenario: Catalog module has committed payload
- **WHEN** the committed catalog lists a module as available
- **THEN** the corresponding canonical module directory SHALL be committed or intentionally excluded with documented rationale

#### Scenario: Local world and campaign files remain ignored
- **WHEN** `git check-ignore -v` is run on `modules/world_registry.json` or `modules/campaign.json`
- **THEN** both files SHALL remain ignored as user-local runtime/catalog state
- **AND** they SHALL NOT be used as the git-authoritative public module catalog

#### Scenario: Public catalog does not erase local modules
- **WHEN** a user has local-only modules registered in `modules/world_registry.json`
- **AND** the repository receives an updated `modules/published_modules.json` from `git pull`
- **THEN** local-only module registry entries SHALL be preserved
- **AND** shipped public module catalog updates SHALL be additive or explicitly user-approved before changing local runtime registry state

### Requirement: Gitignore module contract SHALL be centrally understandable
The module publication git rules SHALL be organized so maintainers can identify the default-ignore rule, published-module allowlist, canonical unignore rules, and runtime ignore rules without relying on scattered last-match-wins behavior.

#### Scenario: Module rules are audited
- **WHEN** a developer reads the module section of `.gitignore`
- **THEN** the section SHALL clearly distinguish published module artifacts from runtime gameplay state
- **AND** broad ignore rules SHALL NOT silently override documented canonical unignore rules for published modules
