# toolkit-adaptation-runtime-publication Specification

## Purpose
Defines the shared staged build and publication transaction used by uploaded adventures and text descriptions after adaptation authoring succeeds.

## Requirements

### Requirement: Adaptation builds use isolated staging

When adaptation is enabled, both uploaded-source and text-description builds SHALL generate provisional module files in an isolated attempt/revision staging target before publication.

#### Scenario: Initial adaptation build

- **WHEN** a validated dossier is ready for ModuleBuilder
- **THEN** ModuleBuilder SHALL write to the reserved adaptation staging target
- **AND** no existing registered module directory SHALL be overwritten by the initial attempt

#### Scenario: Semantic revision

- **WHEN** the final semantic auditor requests a revision
- **THEN** the revised build SHALL use a distinct fresh staging target
- **AND** the prior attempt SHALL remain available for diagnostics or rollback

### Requirement: Shared gates precede publication

An adaptation build SHALL reuse schema, readiness, mechanical closure, semantic, report-agreement, Markdown quality, registry, campaign, and rollback contracts from the completed scaffold in their defined order.

#### Scenario: All pre-publication gates pass

- **WHEN** the staged module passes every required pre-registration gate and its Markdown summary is valid
- **THEN** Python SHALL perform registry integration as the final stateful publication step
- **AND** SHALL post-verify module and area registry entries before reporting success

#### Scenario: A pre-publication gate fails

- **WHEN** schema, readiness, semantic, report, or Markdown quality fails
- **THEN** the runtime SHALL report blocked or failed adaptation status
- **AND** SHALL not modify registry or active campaign state

### Requirement: Text-description builds do not bypass finishing

When adaptation is enabled, the existing text-description builder SHALL use the same readiness, finishing, Markdown, registry, campaign, and rollback transaction as uploaded adventures.

#### Scenario: Text description reaches publication

- **WHEN** a text description produces a valid adaptation dossier and staged module
- **THEN** the build SHALL enter the shared readiness and finishing stages
- **AND** SHALL report completion only after the same publication verification used for uploaded adventures

### Requirement: Runtime failures leave no false publication

An adaptation build SHALL not report completion or leave misleading registry/campaign entries when authoring, staging, validation, publication, campaign synchronization, or post-write verification fails.

#### Scenario: Post-registration failure

- **WHEN** a failure occurs after registry or campaign writes begin
- **THEN** the completed scaffold rollback contract SHALL restore or remove only entries created by the failed attempt
- **AND** the job SHALL end with an explicit failed or blocked outcome

#### Scenario: Successful publication

- **WHEN** the staged module, reports, Markdown, registry entries, and required campaign visibility all verify successfully
- **THEN** the job SHALL report a completed adaptation build
- **AND** SHALL retain bounded provenance and attempt reports for the published module

### Requirement: Legacy routes remain isolated

The adaptation runtime SHALL not change legacy accurate-ingest or direct-builder output when adaptation is disabled or when a job is explicitly classified as legacy.

#### Scenario: Legacy regression path

- **WHEN** a legacy job runs with adaptation disabled
- **THEN** it SHALL not require adaptation dossiers, world-context provenance, or adaptation staging artifacts
- **AND** it SHALL preserve its existing readiness, finishing, and status contracts

### Requirement: First eligible semantic failures remain revision-available

When an adaptation gate reports a semantic or mechanical content failure, the runtime SHALL preserve the classifier's remaining revision budget and project an eligible first failure as `adaptation_revision_required` rather than terminal `adaptation_blocked`.

#### Scenario: First semantic failure

- **WHEN** the initial staged build has a semantic failure, convergence completed sufficiently to run the adaptation gates, and one revision remains
- **THEN** the job SHALL report `adaptation_revision_required`
- **AND** bounded retry diagnostics SHALL report `outcome=semantic_revision`, retry availability, and `next_revision_eligible=true`
- **AND** registry, campaign, and live-module publication SHALL not be attempted

#### Scenario: Fresh revision recovers

- **WHEN** the first semantic failure is eligible and the fresh revision passes all required gates
- **THEN** the revision SHALL use a distinct staging target
- **AND** the job SHALL publish only after the normal verified publication transaction succeeds

### Requirement: Revision eligibility MUST agree across persisted surfaces

The packet result, attempt `build_result` artifact, job projection, and retry diagnostics SHALL expose the same revision decision, remaining budget, attempt identity, and source identity.

#### Scenario: Revision budget is exhausted

- **WHEN** a semantic failure persists after the permitted revision budget is consumed
- **THEN** the job SHALL report the bounded exhausted/blocked terminal status
- **AND** retry diagnostics SHALL clear revision eligibility
- **AND** no registry or campaign side effect SHALL be present

#### Scenario: Non-semantic failure

- **WHEN** the failure class is infrastructure, rights/refusal, publication, or monster-guardrail rather than semantic/mechanical content
- **THEN** the runtime MUST preserve its existing non-revision terminal mapping
- **AND** a remaining semantic revision budget MUST NOT make the failure retryable
