# independent-fork-governance Specification

## Purpose
Define the repository-level independent fork governance contract: the project
identifies as an independently developed fork, retains internal architecture
discipline without upstream parity, removes routine upstream synchronization
obligations, and keeps runtime artifacts untouched by the governance pivot.

## Requirements

### Requirement: Repository identifies as an independent fork

The repository SHALL identify itself in active guidance as an independently
developed TTRPG platform originally derived from MoonlightByte/NeverEndingQuest,
and SHALL treat upstream as a read-only historical and technical reference.

#### Scenario: Active guidance wording

- **WHEN** a maintainer reads active repository guidance (`AGENTS.md`,
  `README.md`, `CONTRIBUTING.md`, `openspec/config.yaml`,
  `openspec/frontier_builder_profile.md`)
- **THEN** the repository SHALL be described as independently developed
- **AND** no active guidance SHALL describe the repository as a merge-safe
  plugin or merge-safe extension of upstream

#### Scenario: Attribution preserved

- **WHEN** the README fork relationship is updated
- **THEN** the original upstream project link and the fork link SHALL remain
  present
- **AND** no claim of compatibility with upstream's current runtime or
  development branch SHALL be added

### Requirement: Internal architecture discipline is retained without upstream parity

The repository SHALL retain its internal architecture discipline: Python
authority for mechanical, persistence, publication, and campaign state;
extension boundaries for ownership and testability; single-player
compatibility; and `# TABLETOP MODE:` markers as lineage documentation.

#### Scenario: Marker meaning

- **WHEN** active guidance documents `# TABLETOP MODE:` markers
- **THEN** the markers SHALL be described as fork lineage, ownership, and
  integration documentation
- **AND** they SHALL NOT be described as merge-compatibility guarantees

#### Scenario: Extension boundary meaning

- **WHEN** active guidance explains extension files and hooks
- **THEN** they SHALL be framed as internal maintainability and testability
  boundaries
- **AND** upstream merge conflict minimization SHALL NOT be stated as their
  purpose

### Requirement: No routine upstream synchronization obligation

Active repository guidance MUST NOT require routine upstream fetching, periodic
upstream review, merge parity, or an upstream sync log.

#### Scenario: Sync guidance removed

- **WHEN** scanning active guidance for upstream synchronization requirements
- **THEN** no active guidance SHALL require a review cadence, a sync log, or
  merge parity
- **AND** the remaining upstream policy SHALL state only that upstream is inert
  read-only reference material outside routine development

#### Scenario: Origin-only push safety retained

- **WHEN** scanning active guidance for remote safety rules
- **THEN** the rules SHALL still require explicit pushes to `origin`
- **AND** the rules SHALL still prohibit pushing to upstream

### Requirement: Governance change does not modify runtime artifacts

This change MUST NOT modify runtime campaign state, module artifacts, character
files, saved games, schemas, or application code behavior.

#### Scenario: Documentation-only diff

- **WHEN** the change diff is reviewed
- **THEN** every changed file SHALL be a governance or documentation artifact
  (ADR files, OpenSpec guidance, repository documentation, or the source plan)
- **AND** no file under `modules/`, `characters/`, `data/`, or an application
  source path SHALL be modified
