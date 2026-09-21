# fork-documentation-source-of-truth Specification

## Purpose
Define the active-guidance synchronization contract for the independent fork
pivot: repository guidance files and OpenSpec project context must state
independent-fork policy coherently, retain the fork's internal engineering
guardrails, and carry fork independence into `AGENTS.md` as policy.

## Requirements

### Requirement: OpenSpec project context reflects fork independence

`openspec/config.yaml` SHALL describe the repository as an independently
developed fork and SHALL NOT describe it as a merge-safe plugin or require
upstream structure preservation.

#### Scenario: Context and guardrails

- **WHEN** reading `openspec/config.yaml`
- **THEN** the project context SHALL NOT contain a merge-safe or
  upstream-preservation requirement
- **AND** the guardrails SHALL retain Python state ground truth, atomic JSON
  operations, ASCII-only output, single-player/multiplayer compatibility, and
  MUST/SHOULD two-layer rules
- **AND** the proposal rules SHALL NOT require a merge-safety impact section
- **AND** the "Current initiative" block SHALL describe the fork independence
  pivot, not the obsolete OpenRouter router initiative

### Requirement: Builder profile no longer prefers merge-safe evolution

`openspec/frontier_builder_profile.md` SHALL replace the merge-safe evolution
style preference with guidance that preserves additive compatibility only where
a fork requirement exists.

#### Scenario: Style target

- **WHEN** reading the style targets section
- **THEN** no line SHALL prefer merge-safe evolution
- **AND** the file SHALL remain otherwise unchanged in its two-layer contract
  rules

### Requirement: AGENTS.md carries the Fork Independence Policy

`AGENTS.md` SHALL describe the project as an independent fork, SHALL include a
Fork Independence Policy referencing ADR-0031, and SHALL NOT retain the
ADR-0030 upstream sync policy, Upstream Sync Log, or legacy upstream merge
guidelines as active operational policy.

#### Scenario: Policy replacement

- **WHEN** reading `AGENTS.md`
- **THEN** a `Fork Independence Policy` section SHALL exist and reference
  ADR-0031
- **AND** the section SHALL state that the upstream remote is read-only, is not
  part of routine development, and that upstream ports require approved fork
  changes
- **AND** no Upstream Sync Log table or monthly upstream review instruction
  SHALL remain

#### Scenario: Preserved sections

- **WHEN** reading `AGENTS.md`
- **THEN** the origin-only push safety rules and upstream never-push rules SHALL
  remain
- **AND** the Module Publication Git Contract and security/state-authority
  contracts SHALL remain unchanged

### Requirement: README and CONTRIBUTING state the fork relationship

`README.md` and `CONTRIBUTING.md` SHALL describe the repository as an
independently developed fork originally derived from upstream, while retaining
attribution links and existing contributor guardrails.

#### Scenario: Fork relationship wording

- **WHEN** reading the fork relationship line in `README.md` and
  `CONTRIBUTING.md`
- **THEN** the wording SHALL state independent development originally derived
  from upstream
- **AND** the upstream attribution link SHALL remain present
- **AND** no merge-safe claim SHALL remain

### Requirement: Source plan records approval and tracking

`plans/archive/independent-fork.md` SHALL record that the plan was approved and that
its implementation was tracked by the `fork-independence-pivot` and
`fork-final-upstream-sweep` OpenSpec changes, both archived on 2026-09-21.

#### Scenario: Plan status line

- **WHEN** reading the status line of `plans/archive/independent-fork.md`
- **THEN** it SHALL indicate that the plan was approved and completed
- **AND** it SHALL reference both OpenSpec change names
