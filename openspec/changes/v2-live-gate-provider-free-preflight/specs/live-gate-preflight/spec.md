# Spec Delta

## Purpose

Defines a provider-free qualification pass for a later live gate run so recorded harness failures are detected before booking, while keeping preflight outcomes separate from pilot evidence and live-gate verdicts.

## ADDED Requirements

### Requirement: Preflight reproduces the intended invocation without provider use

The preflight MUST exercise the frozen SP3 row set on an isolated `Capture_Arena` copy with the same intended host command, working directory, and `PYTHONPATH` as the later live run. It MUST use a stub router, issue zero upstream provider requests, consume zero provider budget and zero live attempt allowance, and hold the shared live-window lock while using port 8360.

#### Scenario: Invocation identity differs from the intended live run
- **WHEN** the command, working directory, or `PYTHONPATH` differs from the declared live invocation
- **THEN** preflight blocks before sandbox seeding or host launch and records the identity mismatch

#### Scenario: A routed call occurs during preflight
- **WHEN** the host path requests a response while a row is being exercised
- **THEN** the stub supplies the test response, no upstream request is sent, and provider-budget and live-attempt counters remain unchanged

### Requirement: Every frozen row has complete fixture and lifecycle coverage

Preflight MUST exercise all 26 frozen SP3 planned scenario rows through the full scripted host path for each row's declared party size, including rows without same-area connectivity. The four replacement-only reserve slots MUST remain unactivated. Each planned row MUST resolve its referenced module files, party, and monster templates, match a previously declared startup and resume call profile for its fixture-party pair, and complete its first scripted exchange through the driver.

#### Scenario: Frozen row set includes both party sizes and disconnected locations
- **WHEN** the preflight runs against the frozen SP3 row set
- **THEN** all 26 planned rows complete their scripted host path for the frozen party size, including 1-PC and 4-PC cases and locations without same-area connectivity, while reserve slots remain unactivated

#### Scenario: A referenced fixture asset is missing
- **WHEN** a row references a module file, party record, or monster template that does not resolve in its seeded copy
- **THEN** that row is reported as a fixture failure with the unresolved reference and does not proceed as covered

#### Scenario: Lifecycle profile is absent or differs from observation
- **WHEN** a fixture-party pair has no declared startup/resume profile, or observed call counts differ from it
- **THEN** preflight reports the missing or mismatched profile and the row is not booking-eligible

#### Scenario: Driver transport completes the first exchange
- **WHEN** the driver connects to a row's host and sends its first scripted exchange
- **THEN** the host returns the stubbed response through the driver transport and the exchange is recorded for that row

### Requirement: Stop controls and row continuation are proven by fault injection

The preflight MUST demonstrate through fault injection that the driver enforces the frozen attempt cap, time cap, and pause after three consecutive infrastructure failures. These simulations MUST NOT consume live attempt allowance or activate replacement-only reserve slots. The harness MUST continue beyond its first path and row when no stop rule applies.

#### Scenario: Attempt or time cap is reached under injected fault
- **WHEN** injected work reaches the configured attempt cap or time cap
- **THEN** the driver stops further work, records the cap and observed counts, and consumes no live attempt allowance

#### Scenario: Three consecutive infrastructure failures are injected
- **WHEN** the third consecutive row is classified as an infrastructure failure
- **THEN** the driver pauses before starting another row and records the pause point

#### Scenario: Initial path and row complete without a stop condition
- **WHEN** the first path and row complete and no cap or pause condition is active
- **THEN** the harness continues to subsequent paths and rows in the frozen set

### Requirement: Identity, evidence, teardown, and booking eligibility are explicit

Each preflight report MUST record the source SHA, dependency identity hash, routing identity hash, invocation identity, row outcomes, provider-free result, and teardown checks under `tmp/router-rollout/<gate>/<run-id>/preflight/`. A later live booking is eligible only when every required preflight check passes with zero infrastructure failures at the exact SHA and identities to be run; a preflight report is not a booking or gate PASS.

#### Scenario: Clean preflight finishes
- **WHEN** all rows and PF checks pass with zero infrastructure failures
- **THEN** the report records the exact source and identity hashes, the required evidence path, lock release, and no listener on ports 8360 or 8370, and identifies the report as preflight-only

#### Scenario: The later run does not match the preflight identity
- **WHEN** a proposed live run uses a different source SHA, dependency identity, or routing identity than the clean report
- **THEN** that report cannot support a booking ruling for the proposed run

#### Scenario: Teardown leaves a required listener active
- **WHEN** preflight teardown completes but a listener remains on port 8360 or 8370
- **THEN** teardown fails, the infrastructure failure is recorded, and the report is not booking-eligible

### Requirement: Comparative acceptance detects the pre-#105 host regression

The comparison MUST exercise the same 26 planned rows at pre-#105 SHA `5999af374ded4f56b21b25d68fc10f9520444b51` and the full SHA resolved from `refs/remotes/origin/main` after a separate refresh immediately before comparison. Freeze that SHA before execution; comparison/preflight MUST use local snapshots offline and block if either commit is unavailable locally. The old checkout stays under project-relative `tmp/`, reserve slots remain unactivated, and no pilot evidence is written.

#### Scenario: Pre-#105 source is used as the regression control
- **WHEN** the comparison runs the frozen rows against commit `5999af374ded4f56b21b25d68fc10f9520444b51`
- **THEN** the report identifies the host `NameError` on rows E06 and E13-E18 and marks the result as a non-bookable regression control

#### Scenario: Current origin main is refreshed and frozen before comparison
- **WHEN** separate pre-comparison preparation refreshes `refs/remotes/origin/main` and resolves its full SHA
- **THEN** preparation freezes that SHA for the comparison; planning base `8d1a9e1ce5d9acda8fb7ff36d8866d28aaaf5624` is context only, and comparison/preflight uses local snapshots without network access

#### Scenario: The frozen current-main target is exercised
- **WHEN** the comparison runs against the exact SHA frozen by pre-comparison preparation
- **THEN** the report records that SHA and contains no host `NameError` for rows E06 or E13-E18; only a report with all required checks passing and zero infrastructure failures can support a later booking ruling
