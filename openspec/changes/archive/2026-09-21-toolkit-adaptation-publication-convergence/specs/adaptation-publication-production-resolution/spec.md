## Purpose

Closes the production callback wiring for bounded destination-resolution repairs in the existing adaptation publication-convergence lane while preserving Python authority, staging safety, gate agreement, and legacy isolation.

## ADDED Requirements

### Requirement: Repairable production ambiguity reaches a bounded request

The adaptation production convergence path MUST build current staged semantic authority and a bounded `validation_context` before invoking the existing convergence callback. The context MUST identify the current attempt, revision, and source hash; one ambiguous phrase; area-scoped canonical candidates; source-reference IDs; topology summary; allowed operations; confidence threshold; `operation_budget=1`; and `timeout_seconds=30`.

#### Scenario: Amphail phrase has repairable candidates

- **WHEN** the current Amphail staging revision contains the ambiguous `softstone inn` phrase and supported area-scoped candidates such as `EV001:K02` and `RO001:K03`
- **THEN** the callback MUST receive an explicit bounded destination-resolution provider request containing that current validation context
- **AND** the request MUST NOT contain unrestricted module contents, raw provider history, or arbitrary file paths

#### Scenario: Deterministic authority already resolves the phrase

- **WHEN** current semantic authority resolves a destination uniquely
- **THEN** production convergence MUST NOT invoke the provider for that phrase
- **AND** it MUST continue using the deterministic canonical resolution path

### Requirement: Valid alias proposals are validated, applied, and re-gated

An accepted proposal MUST contain exactly one whitelisted `resolve_destination_alias` operation targeting one current area-scoped canonical location. Python MUST validate source evidence, topology compatibility, confidence, attempt identity, revision identity, and source hash before atomically applying the alias to staging with provenance and input/output hashes.

#### Scenario: One valid canonical proposal is returned

- **WHEN** the provider returns one supported candidate with sufficient confidence and valid source references
- **THEN** Python MUST apply the alias atomically to staging only
- **AND** semantic authority MUST be refreshed and relevant plus complete hard gates MUST be rerun
- **AND** finisher/publication MAY continue only when all current reports agree on attempt, revision, source identity, and passing gate status

### Requirement: Invalid or failed resolution remains blocked and staging-safe

Provider failure, timeout, malformed output, rejected output, unsupported operation, stale identity, insufficient evidence, topology conflict, or unresolved ambiguity MUST persist a bounded blocker, leave the prior staging revision unchanged, and prevent publication. The pipeline MUST NOT use regex matching, best-candidate fallback, or arbitrary LLM file patches.

#### Scenario: Provider fails or proposal is rejected

- **WHEN** the provider is unavailable or Python rejects the returned proposal
- **THEN** the current staging revision MUST remain unchanged
- **AND** no live module, registry, campaign, or runtime state MUST be mutated
- **AND** the production convergence result MUST remain blocked with a concrete failure diagnostic

### Requirement: The new production seam is adaptation-only

The bounded production destination-resolution request and callback seam MUST run only inside the existing adaptation publication-convergence path. Legacy accurate-ingest, concept-builder, direct ModuleBuilder, single-player, and other non-adaptation paths MUST remain unchanged and MUST receive no convergence metadata.

#### Scenario: Legacy build executes

- **WHEN** a non-adaptation build runs
- **THEN** it MUST bypass the production destination-resolution seam
- **AND** its result MUST contain no adaptation convergence metadata or provider request context

### Requirement: Finalization budgets remain fixed

The closure MUST preserve the existing maximum of three finalization attempts, one accepted operation per round, and a 30-second per-operation timeout. It MUST NOT retry automatically after budget exhaustion or promote a staging revision with unresolved blockers.

#### Scenario: Budget is exhausted

- **WHEN** no safe resolution is accepted within the bounded rounds
- **THEN** one current-attempt terminal blocker report MUST be persisted
- **AND** finisher/publication MUST not continue
