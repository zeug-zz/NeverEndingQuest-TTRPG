# module-publication-git-workflow Specification

## Purpose

Define the operator/agent workflow for staging, committing, and pushing validated modules without runtime artifacts.

## Requirements

### Requirement: Module publishing workflow SHALL verify gitignore behavior before staging

The module publishing workflow SHALL verify that canonical publication artifacts are not ignored and runtime artifacts are ignored before a module commit is prepared.

#### Scenario: Canonical file remains ignored
- **WHEN** a validated module is prepared for publication
- **AND** `git check-ignore -v` reports that a required canonical artifact is ignored
- **THEN** the workflow SHALL stop and instruct the builder to fix `.gitignore`
- **AND** SHALL NOT recommend `git add -f` as the normal remedy

#### Scenario: Runtime file is not ignored
- **WHEN** a validated module is prepared for publication
- **AND** `git check-ignore -v` reports that a runtime file is not ignored
- **THEN** the workflow SHALL stop and require ignore-rule correction before staging

### Requirement: Module publishing workflow SHALL stage only canonical paths

The module publishing workflow SHALL stage README/catalog/docs updates and canonical module artifacts while refusing mutable runtime gameplay files.

#### Scenario: Runtime path appears in staged diff
- **WHEN** staged files include `module_plot.json`, `party_tracker.json`, live `areas/*.json`, `encounters/**`, `modules/world_registry.json`, `modules/campaign.json`, `.bak`, `.backup`, or backup directories
- **THEN** the workflow SHALL flag the staged diff as unsafe
- **AND** SHALL require unstaging or cleanup before commit

#### Scenario: Canonical module payload is staged
- **WHEN** a module is validated and public
- **THEN** the workflow SHALL stage the canonical module payload, README changes, `modules/published_modules.json`, and documentation/skill changes needed to publish it
- **AND** SHALL preserve module-local media and monster definitions required by publication audits

#### Scenario: Published module live maps are staged
- **WHEN** a published module includes `map_*.json` files
- **THEN** the workflow SHALL treat those map files as canonical staged artifacts
- **AND** SHALL NOT classify them as runtime files unless a future spec marks maps as gameplay-mutable

### Requirement: Module publishing documentation SHALL be agent-actionable

The repository documentation SHALL tell agents exactly what to commit, what to exclude, and which verification commands to run for module publication.

#### Scenario: Agent reviews AGENTS before module push
- **WHEN** an agent is asked to commit or push a validated module
- **THEN** `AGENTS.md` SHALL provide an explicit module publication git contract
- **AND** SHALL state that ignored canonical files indicate a `.gitignore` bug rather than a reason to omit the module

#### Scenario: Agent uses module publishing skill
- **WHEN** a module publish/git skill is invoked
- **THEN** the skill SHALL include validation, gitignore checks, canonical staging rules, runtime-file rejection, commit, and explicit `origin` push guidance

### Requirement: Module publishing workflow SHALL preserve upstream push safety

Module publication commits SHALL follow repository push safety rules and SHALL NOT target the upstream remote.

#### Scenario: Module is pushed for colleagues
- **WHEN** a module publication commit is pushed
- **THEN** the push command SHALL target `origin` explicitly
- **AND** SHALL NOT push to `upstream`
