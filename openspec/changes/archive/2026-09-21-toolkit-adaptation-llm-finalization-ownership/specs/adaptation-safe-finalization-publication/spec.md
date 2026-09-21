## Purpose

Ensure accepted LLM content remediation is validated, rerun through every required gate, and published only through the existing Python-owned transaction boundary.

## ADDED Requirements

### Requirement: Accepted remediation reruns the complete adaptation pipeline

After an accepted content-resolution operation, the adaptation lane MUST rerun from source/packet normalization through canonical registry/materialization, monster closure, spatial and semantic convergence, readiness, gameplay, report agreement, Markdown, and publication evaluation.

#### Scenario: Cave Guardian revision

- **WHEN** Python accepts a bounded `Cave Guardian` resolution for the Amphail failure
- **THEN** a fresh staging revision MUST rerun normalization and all downstream gates
- **AND** the result MUST be tied to one current attempt/revision identity

### Requirement: Hard gates precede publication

Python MUST verify rights/policy, project-relative staging containment, JSON/schema validity, artifact identity/freshness, bounded proposal validity, readiness, gameplay, report agreement, registry write, campaign sync, and post-write verification before publication succeeds.

#### Scenario: Finalizer claims ready early

- **WHEN** the LLM reports a content candidate as ready but any hard gate or post-write verification is incomplete
- **THEN** publication MUST NOT be attempted
- **AND** the staged candidate MUST remain non-publishable with a bounded diagnostic

### Requirement: Publication and rollback are atomic and Python-owned

LLM output MUST never directly mutate live modules, registry, campaign, or runtime state. The existing atomic publication transaction MUST be the only promotion path, with rollback on post-write verification failure.

#### Scenario: Publication write fails

- **WHEN** a registry or campaign post-write verification fails
- **THEN** the transaction MUST roll back its owned writes
- **AND** the adaptation result MUST remain blocked without treating the candidate as published

### Requirement: Legacy compatibility is preserved

The new finalization and rerun boundary MUST be guarded by `llm_adaptation` behavior and MUST NOT alter legacy accurate-ingest, concept-builder, or single-player paths.

#### Scenario: Legacy path runs

- **WHEN** adaptation is disabled or a legacy builder route is selected
- **THEN** the legacy pipeline and output shape MUST remain unchanged
- **AND** no adaptation revision or finalization metadata may leak into the legacy result
