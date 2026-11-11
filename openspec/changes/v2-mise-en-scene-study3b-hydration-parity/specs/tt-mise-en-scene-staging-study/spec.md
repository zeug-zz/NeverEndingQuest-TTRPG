# Spec Delta

## Purpose

Defines an isolated staging-study contract that keeps request-visible facts, deterministic acceptance, and hydrated records in parity while protecting guarded knowledge and unknowns during bounded, reviewable runs.

## ADDED Requirements

### Requirement: Request-public facts SHALL have exhaustive contract and hydration parity

For every approved scene, one canonical inventory MUST account for each request-public fact ID and its complete fact record across the rendered request, accepted claim references, and hydrated result. Identity, audience, status, value, provenance, and source binding MUST agree or the run MUST fail closed before dispatch.

#### Scenario: All request-public records agree
- **GIVEN** the canonical per-scene fact inventory and rendered request
- **WHEN** provider-free parity validation checks every request-public fact and ID against contract acceptance and hydration
- **THEN** all eligible facts and IDs are present in each view with equivalent complete records
- **AND** a missing, extra, or changed ID, audience, status, value, provenance, or source binding is rejected

### Requirement: Guarded knowledge and protected unknowns SHALL NOT be promoted

The Study 3b contract MUST preserve canonical audience and unknown status. Guarded or non-public facts MUST NOT become claim-eligible, and protected unknowns MUST NOT be inferred, materialized as known, or overwritten.

#### Scenario: A mutation promotes protected knowledge
- **GIVEN** a provider-free fixture containing a guarded fact or protected unknown
- **WHEN** a mutation changes its audience, status, value, provenance, claim eligibility, or hydrated state
- **THEN** parity validation rejects the mutation before dispatch and preserves the canonical protected state

### Requirement: ha003 Study 3 request attribution SHALL be private and hash-bound

The primary-only Study 3b diagnostic MUST determine whether the preserved offending ha003 Study 3 response marker appears as guarded in the actual dispatched Study 3 request. It MUST verify the reconstructed request against the recorded transport hash and canonical guarded annotations. It MUST use the marker in memory only; ambiguous evidence MUST yield indeterminate with no model-attribution claim.

#### Scenario: The preserved ha003 marker is compared with the actual Study 3 request
- **GIVEN** the exact preserved offending ha003 Study 3 response marker, its recorded transport request hash, the hash-bound Study 3 request inputs, and canonical guarded annotations
- **WHEN** the primary performs the authorized in-memory diagnostic and verifies that the reconstructed request hash matches the recorded transport hash
- **THEN** the diagnostic returns only a true, false, or indeterminate marker-presence result with hashes, necessary IDs, and an ambiguity code
- **AND** it emits no request, guarded, or response prose, changes no private artifact, and makes no semantic or model-attribution claim when the evidence is ambiguous
- **AND** the check performs no provider, credential, or network access

### Requirement: Study 3b SHALL preserve its bounded identity and immutable ledger prefix

Study 3b MUST retain study ID `mise-en-scene-study3b-20261111`, its distinct root and lock identity `llm-staging-study3b-20261111`, and an append-only ledger. The original run/report, attempt, receipt, response, stop record, and 7,495-byte ledger prefix with SHA-256 `a522e60692c4aa2c7f622998f2ac6cb165ef02211043abf949c319858fa7fd5e` MUST remain unchanged.

#### Scenario: The original ledger prefix is pinned before continuation
- **GIVEN** the stopped Study 3b ledger and its original one-attempt evidence
- **WHEN** continuation begins
- **THEN** the primary verifies and pins both the exact prefix byte length and SHA-256 before any append
- **AND** the original event, receipt, response, and stop record remain byte-for-byte unchanged

### Requirement: Study 3b continuation SHALL be one-time, authorized, and race-safe

Continuation MUST be gated by ruling `neq-s-study3b-adjudication-20261111`, proof of the exact original prefix, prior result and reconciled spend, and the prescribed remaining-scene order. It MUST append once to the existing ledger under an atomic lock and MUST NOT reinitialize, replay, or repeat an attempt.

#### Scenario: A valid continuation transition appends once
- **GIVEN** the verified 7,495-byte prefix, SHA-256 `a522e60692c4aa2c7f622998f2ac6cb165ef02211043abf949c319858fa7fd5e`, the stopped ha003 result, its USD 0.004085175 receipt, and the explicit ruling
- **WHEN** the primary acquires the continuation lock and verifies the next scene is `into_the_deepvault:scene:sd005-i03`
- **THEN** one continuation transition is appended to the same ledger and the prefix bytes remain unchanged
- **AND** the only subsequent scene order is `into_the_deepvault:scene:sd005-i03` then `xhalruuns_masquerade:scene:tsu001-ao02`

#### Scenario: Invalid or competing continuation attempts fail closed
- **GIVEN** a mismatched prefix, result, spend, scene order, missing ruling, already-used transition, or competing continuation request
- **WHEN** continuation authorization is evaluated under the atomic lock
- **THEN** no reservation or dispatch is made and the ledger is not reinitialized or altered

### Requirement: Study 3b SHALL retain the approved model, scene, attempt, and cost limits

Continuation MUST use OpenRouter `openai/gpt-6-luna`, `max_tokens=16384`, and a 720-second timeout. The original ha003 attempt counts toward the three-attempt total; only sd005-i03 and tsu001-ao02 may be attempted, once each, in order, with no retry, fallback, or availability GET and no more than USD 0.05 total actual cost.

#### Scenario: Only the two unattempted scenes consume the remaining allocation
- **GIVEN** the original ha003 attempt and USD 0.004085175 receipt
- **WHEN** the authorized continuation dispatches
- **THEN** it attempts sd005-i03 followed by tsu001-ao02, at most once each
- **AND** it makes no ha003 replay and refuses any dispatch exceeding three total attempts or USD 0.05 reconciled total cost

### Requirement: Attempt outcomes SHALL distinguish completed contract failures from STOPPED outcomes

A contract failure MUST complete that scene and continue to the next prescribed scene. Only transport, identity, persistence, or budget STOPPED outcomes halt dispatch; validator failures MUST record a machine-readable validator code and rule ID without prose.

#### Scenario: A contract failure completes its scene and continues
- **GIVEN** a contract failure for sd005-i03 with a validator code and rule ID
- **WHEN** the attempt result is recorded
- **THEN** the scene is complete, its code and rule ID are stored without prose, and tsu001-ao02 remains eligible for its single authorized attempt

#### Scenario: A STOPPED outcome halts continuation
- **GIVEN** a transport, identity, persistence, or budget STOPPED outcome for either remaining scene
- **WHEN** the outcome is recorded
- **THEN** no later scene is dispatched and no retry or replacement attempt is made

#### Scenario: The adjudicated ha003 metadata is supplemented without rewriting history
- **GIVEN** the immutable original ha003 event and the adjudication `GUARDED_MARKER_IN_PUBLIC_DELTA`, rule `S3-GUARDED-CONTENT-MARKERS`
- **WHEN** the continuation records adjudicated attempt metadata
- **THEN** it appends a metadata-only supplement containing that code and rule ID
- **AND** it does not rewrite the original event, receipt, response, stop record, or ledger prefix and includes no prose

### Requirement: A new protocol or harness defect SHALL block the staging line

A newly identified protocol or harness defect MUST mark the staging line BLOCKED and MUST NOT authorize Study 4, but MUST NOT by itself halt the remaining authorized attempt. An ordinary model-attributable contract failure MUST remain a per-scene result and MUST NOT by itself be reclassified as a protocol or harness defect.

#### Scenario: A new harness defect blocks the staging line
- **GIVEN** a new protocol or harness defect in either remaining scene
- **WHEN** the continuation records the defect and completes any independently authorized remaining attempt
- **THEN** the staging line is BLOCKED and no Study 4 is opened
- **AND** the next prescribed scene remains eligible unless a transport, identity, persistence, or budget STOPPED outcome occurs

#### Scenario: An ordinary model-attributable contract failure is not relabeled
- **GIVEN** a contract failure attributable to the model and no new protocol or harness defect
- **WHEN** the scene result is recorded
- **THEN** it remains a per-scene model-attributable result and the next prescribed scene may be attempted

### Requirement: Study 3b dispatch and handoff SHALL remain gated and private

Only the primary may continue after fresh CI evidence shows all 11 required checks green on the exact final published head and a clean provider-free preflight reports zero infrastructure failures on that same head. Earlier CI and readiness records are historical and MUST NOT satisfy this gate. Raw outputs MUST remain private until independent review; the original handoff remains unchanged and exactly one separate metadata-only continuation handoff is permitted.

#### Scenario: Fresh exact-head gates authorize the primary continuation
- **GIVEN** fresh CI and preflight evidence for one exact final published head
- **WHEN** continuation readiness is evaluated
- **THEN** continuation is permitted only if all 11 checks are green and zero-infrastructure-failure preflight is bound to that same head
- **AND** earlier readiness evidence is not reused
- **AND** a new protocol or harness defect blocks the staging line and Study 4

#### Scenario: The continuation is handed off separately once
- **GIVEN** the preserved original handoff and a completed continuation or an earlier STOPPED outcome
- **WHEN** the primary prepares the continuation handoff
- **THEN** exactly one separate handoff contains hashes, safe statuses, structured validator codes/rule IDs, and reconciled total-cost evidence
- **AND** it contains no raw request or output prose, self-score, repair output, or owner-facing output before independent review
- **AND** the original handoff and its evidence remain unchanged
