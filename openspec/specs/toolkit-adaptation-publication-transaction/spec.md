# toolkit-adaptation-publication-transaction Specification

## Purpose
Defines the validation, staging, registry, rollback, and campaign-visibility transaction that controls whether an adapted module may be reported as completed.

## Requirements

### Requirement: Completed adaptation passes all publication gates

An adapted module MUST pass schema validation, mechanical readiness, continuity, semantic authority, semantic probes, report agreement, and required artifact checks before completion is reported.

#### Scenario: All gates pass

- **WHEN** a staged adapted module passes every required gate
- **THEN** it becomes eligible for Markdown generation and final registration

#### Scenario: Gate failure

- **WHEN** any required gate fails
- **THEN** the module remains unpublished and the failure is recorded with its gate and diagnostics

### Requirement: Registry integration is last and verified

World registry integration MUST occur only after all validation, report, and Markdown checks pass, and the registry entry MUST be verified afterward.

#### Scenario: Successful registration

- **WHEN** a candidate passes all pre-registration checks and integration succeeds
- **THEN** the module and its areas are present in the world registry and verification reports success

#### Scenario: Registration failure

- **WHEN** integration fails or verification cannot find the module afterward
- **THEN** the adaptation is not completed and the registry failure is surfaced

### Requirement: Failed publication has no misleading side effect

The transaction MUST use staging, backup, or atomic promotion so a failed adaptation cannot leave a partially published module represented as completed.

#### Scenario: Post-build failure before registration

- **WHEN** Markdown or report agreement fails before registry integration
- **THEN** no new registry entry is created

#### Scenario: Post-registration verification failure

- **WHEN** a failure occurs after a registry write but before publication completion
- **THEN** the transaction restores the prior registry state or reports an explicit failed publication requiring cleanup

### Requirement: Campaign availability is verified

When an active campaign exists, a completed adaptation MUST be visible through the campaign's available-module index or the result MUST explicitly state that campaign synchronization is deferred by policy.

#### Scenario: Active campaign synchronization

- **WHEN** an adapted module is registered while an active campaign is present
- **THEN** the campaign availability state contains the module or the transaction fails

#### Scenario: No active campaign

- **WHEN** no active campaign exists during registration
- **THEN** world registry verification succeeds and the report records that campaign synchronization is deferred
