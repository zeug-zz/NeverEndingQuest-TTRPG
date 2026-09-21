# Provider Response Failure Classification

## Purpose

Distinguish empty transient completions from refusal, content-filter,
authentication, quota, timeout, and invalid-request failures so each class keeps
its existing handling and empty-result recovery never widens its scope.

## ADDED Requirements

### Requirement: Failure classes are explicitly distinguished

The recovery boundary SHALL classify completions and errors into distinct
classes: empty transient, refusal, content filter, retryable provider error,
and terminal provider error.

#### Scenario: Refusal response

- **WHEN** the selected choice message carries a non-empty refusal marker
- **THEN** the response SHALL NOT be classified as empty transient
- **AND** it SHALL NOT be retried by the empty-transient loop
- **AND** existing refusal handling SHALL be preserved

#### Scenario: Content-filtered response

- **WHEN** the selected choice finish reason indicates content filtering
- **THEN** the response SHALL NOT be classified as empty transient
- **AND** it SHALL NOT be retried by the empty-transient loop
- **AND** existing content-filter handling SHALL be preserved

#### Scenario: Authentication, quota, or invalid-request error

- **WHEN** a provider exception indicates authentication failure, quota
  exhaustion, or an explicitly invalid request
- **THEN** existing non-retryable provider error classification SHALL be
  preserved
- **AND** the empty-response retry SHALL NOT be applied to that exception

#### Scenario: Rate limit, timeout, or transient server error

- **WHEN** a provider exception indicates a retryable condition
- **THEN** existing retryable classification and fallback eligibility SHALL be
  preserved

### Requirement: Observability is bounded and payload-free

The recovery boundary MAY emit bounded diagnostics for attempt count, stage
(primary or fallback), classification outcome, and terminal status. Diagnostics
MUST NOT contain prompts, raw provider payloads, credentials, or request bodies.

#### Scenario: Terminal empty response

- **WHEN** an empty transient completion reaches the bounded limit
- **THEN** any emitted diagnostic SHALL contain only stage, attempt count, and
  classification metadata
- **AND** no prompt text or raw response body SHALL be logged

#### Scenario: Logging failure

- **WHEN** diagnostic logging raises internally
- **THEN** request execution and fallback behavior SHALL continue unchanged

### Requirement: Upstream #240 inspection is bounded and recorded

The change SHALL inspect the fork's provider error and fallback state for the
upstream #240 defect class (a completed provider error being reissued) and SHALL
record the outcome. A fix SHALL be added only if the defect is reproduced in
fork code.

#### Scenario: Defect not reproduced

- **WHEN** the fork already prevents completed provider errors from being
  reissued
- **THEN** the inspection outcome SHALL be recorded in the change
  implementation notes
- **AND** no provider code SHALL be modified for #240

#### Scenario: Defect reproduced

- **WHEN** the fork reproduces a completed-error reissue path
- **THEN** the smallest fork-native fix SHALL be added
- **AND** provider-free regression coverage SHALL be extended
