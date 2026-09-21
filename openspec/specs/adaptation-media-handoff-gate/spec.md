# adaptation-media-handoff-gate Specification

## Purpose
Ensure adaptation readiness treats approved toolkit structural media debt as manual handoff while preserving strict gameplay blocking for all other integrity failures.

## Requirements

### Requirement: Adaptation Reuses Toolkit Media Handoff Policy

The adaptation gate composer MUST apply the existing toolkit media-only relaxation to its gameplay result before final gate normalization.

#### Scenario: Only structural base media is missing

- **WHEN** every gameplay blocking error is a recognized missing-base-media error
- **AND** the corresponding structural media findings have an allowed manual-handoff outcome
- **THEN** the normalized gameplay gate MUST report an effective passing status
- **AND** MUST mark the result as manual handoff only
- **AND** MUST preserve the raw subprocess exit code and bounded media-debt metadata.

### Requirement: Non-Media Gameplay Failures Remain Blocking

The adaptation gate MUST remain fail-closed for any non-media blocker, mixed media and non-media blockers, missing monster JSON, unknown media outcome, malformed output, or unresolved structural gameplay finding.

#### Scenario: Media debt is mixed with a hard blocker

- **WHEN** a gameplay result contains missing media plus a missing monster JSON or other non-media blocker
- **THEN** the gameplay gate MUST remain blocked
- **AND** the adaptation result MUST retain the existing bounded retry/failure classification.

### Requirement: Manual Handoff Does Not Publish Automatically

A media-only passing gameplay gate MUST not generate media, bypass schema/continuity/semantic/mechanical/publication gates, or mutate live modules, registry, campaign, or runtime state.

#### Scenario: Adaptation proceeds after media handoff classification

- **WHEN** the media-only gameplay result is accepted as manual handoff
- **THEN** media debt MUST remain visible in reports
- **AND** publication MUST still require the complete final gate set and existing publication transaction.

### Requirement: Reporting Remains Bounded

The adaptation reporting envelope MUST retain `raw_provider_payload_exposed=false` and MUST NOT include raw provider prompts, source excerpts, request JSON, response bodies, credentials, or arbitrary provider exceptions.

#### Scenario: Media handoff result is persisted

- **WHEN** an adaptation report records a manual media handoff result
- **THEN** the report MUST retain bounded gate and debt metadata only
- **AND** `raw_provider_payload_exposed` MUST remain false.
