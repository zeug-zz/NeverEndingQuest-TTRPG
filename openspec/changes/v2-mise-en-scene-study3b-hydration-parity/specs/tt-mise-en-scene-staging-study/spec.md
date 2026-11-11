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

### Requirement: Study 3b SHALL use an independent bounded run identity and allocation

Every Study 3b attempt MUST bind study ID `mise-en-scene-study3b-20261111`, a distinct root and lock identity `llm-staging-study3b-20261111`, the exact ordered scene set, and a durable append-only ledger. It MUST NOT read for allocation, reset, replay, or write into a Study 1, 2, or 3 run or ledger.

#### Scenario: The fixed envelope is enforced
- **GIVEN** a Study 3b manifest for `into_the_deepvault:scene:ha003-i02`, `into_the_deepvault:scene:sd005-i03`, and `xhalruuns_masquerade:scene:tsu001-ao02` in that order
- **WHEN** an attempt is reserved for dispatch
- **THEN** it uses OpenRouter `openai/gpt-6-luna`, `max_tokens=16384`, and a 720-second timeout
- **AND** no more than one attempt per scene or three attempts total can be reserved
- **AND** retry, fallback, and availability GET are prohibited
- **AND** dispatch is refused unless reconciled actual cost remains within USD 0.05

### Requirement: Study 3b dispatch and handoff SHALL remain gated and private

Only the primary may dispatch after approvals are pinned to the exact final head and Study 3b protocol/config hashes, all 11 required CI checks pass on that head, and provider-free preflight reports zero infrastructure failures. Raw outputs MUST remain private until independent review, and exactly one metadata-only Overseer handoff is permitted.

#### Scenario: Exact-head gates authorize the primary run
- **GIVEN** approvals, provenance, CI results, and preflight evidence for one exact final head
- **WHEN** dispatch readiness is evaluated
- **THEN** dispatch is permitted only if all pins match and all 11 checks and zero-infrastructure-failure preflight pass on that same head
- **AND** any outage, quota, timeout, or protocol defect stops the run without retry or fallback
- **AND** a protocol defect blocks Study 4

#### Scenario: Private evidence is handed off once
- **GIVEN** a completed run or an earlier fail-closed stop
- **WHEN** the primary prepares the independent-review handoff
- **THEN** exactly one handoff contains hashes, safe statuses, and reconciled actual-cost evidence
- **AND** it contains no raw request or output prose, self-score, repair output, or owner-facing output before independent review
