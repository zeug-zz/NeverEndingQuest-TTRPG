# fork-upstream-reference-policy Specification

## Purpose
Define the fork's upstream reference policy: the upstream remote remains inert
read-only reference infrastructure, upstream behavior enters the fork only
through separately approved changes, and the deferred closing artifacts for the
old upstream plan are explicitly scoped to the sweep change.

## Requirements

### Requirement: Upstream remote is inert reference infrastructure

The `upstream` remote SHALL remain configured for fetch/reference only with its
push URL disabled, and no part of this governance pivot SHALL fetch from, push
to, or merge upstream.

#### Scenario: Remote state after implementation

- **WHEN** inspecting `git remote -v`
- **THEN** the upstream fetch URL SHALL still reference MoonlightByte/NeverEndingQuest
- **AND** the upstream push URL SHALL still be `DISABLE`
- **AND** no upstream fetch, merge, or push SHALL have been executed by the
  change

### Requirement: Upstream behavior enters the fork only through approved changes

Porting upstream behavior SHALL require a separately approved OpenSpec fork
change; routine synchronization and merge-parity maintenance SHALL NOT be
reintroduced.

#### Scenario: Classification of future upstream work

- **WHEN** future upstream behavior is evaluated
- **THEN** it SHALL be treated as reference material unless an approved fork
  change selects it
- **AND** the governance record SHALL state that ports are designed against
  fork contracts rather than imported wholesale

### Requirement: Deferred closing artifacts are explicitly scoped

The final upstream review ledger and archival of `plans/upstream-merge-0826.md`
SHALL be completed by the `fork-final-upstream-sweep` change after the approved
behavior ports are verified; this change MUST NOT archive that plan or write a
ledger claiming sweep outcomes.

#### Scenario: Plan archival boundary

- **WHEN** this change is verified
- **THEN** `plans/upstream-merge-0826.md` SHALL still exist under `plans/`
- **AND** no ledger entry claiming final port outcomes SHALL have been written

#### Scenario: Plan file preserved in this change

- **WHEN** reviewing the change diff
- **THEN** `plans/upstream-merge-0826.md` SHALL be unchanged by this change
