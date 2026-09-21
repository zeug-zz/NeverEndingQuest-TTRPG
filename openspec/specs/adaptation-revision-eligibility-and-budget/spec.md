# adaptation-revision-eligibility-and-budget Specification

## Purpose
Define when adaptation content failures may consume the bounded LLM revision budget and how revision status is projected across build, job, and retry surfaces.

## Requirements

### Requirement: Content closure failures are revision-eligible

An adaptation failure caused by source-grounded monster identity interpretation, quantity/scene semantics, or bounded content remediation MUST be marked revision-eligible when the finalization workflow and remaining budget permit a safe retry.

#### Scenario: Initial Amphail closure failure

- **WHEN** the initial staged revision reports a semantic `monster_closure_unresolved` for `Cave guardians` and the configured revision budget is nonzero
- **THEN** the result MUST report `adaptation_revision_required` or its equivalent revision-eligible status
- **AND** it MUST not be terminal solely because the failure domain contains `monster`
- **AND** no publication may begin

### Requirement: Hard failures remain terminal

Rights/policy rejection, malformed or schema-invalid artifacts, path/staging escape, stale identity, provider/infrastructure failure, unsafe proposal, and transaction failure MUST remain terminal and MUST NOT be relabeled as content revision.

#### Scenario: Path failure at revision zero

- **WHEN** a monster materialization attempts to escape the project-relative staging root
- **THEN** the job MUST remain terminal/blocked
- **AND** revision eligibility MUST be false even when content budget remains

### Requirement: Revision budget is consumed exactly once per accepted revision

The revision runner MUST create a fresh staging target for each accepted content revision, preserve the prior revision as evidence, and report remaining budget deterministically. It MUST not retry automatically after exhaustion.

#### Scenario: Budget exhausted

- **WHEN** all configured content revisions are consumed without passing hard gates
- **THEN** the result MUST report revision exhaustion with `next_revision_eligible=false`
- **AND** no registry, campaign, or live-module publication may occur

### Requirement: Status projections agree

The packet build result, persisted attempt report, job status, retry diagnostics, and GUI-facing status envelope MUST agree on content revision required, exhausted, or terminal blocked state for the same attempt/revision/source identity.

#### Scenario: Revision-required projection

- **WHEN** an eligible monster content blocker remains after the initial build
- **THEN** all status surfaces MUST retain the concrete failure code, remaining budget, and revision eligibility
- **AND** stale reports from an earlier attempt MUST NOT override the current result
