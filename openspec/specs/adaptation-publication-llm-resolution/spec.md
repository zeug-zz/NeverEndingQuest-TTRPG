# adaptation-publication-llm-resolution Specification

## Purpose
Uses the Module Builder LLM to resolve genuinely ambiguous destination semantics and other explicitly repairable staged content gaps while keeping Python authoritative over canonical locations, monster identities, topology, provenance, and publication safety.

## Requirements

### Requirement: Ambiguous destination proposals are bounded and validated

The adaptation pipeline MUST send only bounded ambiguity context to the configured Module Builder LLM and MUST validate every proposed destination against canonical locations, topology, source evidence, and an explicit confidence threshold before applying it.

#### Scenario: LLM proposes one valid canonical resolution

- **WHEN** an ambiguous destination phrase has multiple possible locations and the LLM proposes exactly one canonical location supported by source evidence
- **THEN** Python MUST validate and persist the alias with provenance and proposal metadata
- **AND** subsequent readiness and gameplay checks MUST use the canonical location ID

#### Scenario: LLM proposes an invalid or ambiguous resolution

- **WHEN** the proposal names a nonexistent location, conflicts with topology, lacks source support, or contains multiple candidates
- **THEN** Python MUST reject the proposal
- **AND** the module MUST remain blocked with a concrete semantic-resolution diagnostic

### Requirement: Finalization Operations Are Explicitly Whitelisted

The adaptation convergence finalizer MUST accept only an explicitly enumerated operation with a Python-owned target and bounded replacement data.

#### Scenario: Proposal requests an allowed repair

- **WHEN** the LLM proposes one allowed destination alias, bounded narrative completion, or a canonical stat completion request for an identity already approved by the monster guardrail
- **THEN** Python MUST validate the target, source evidence, attempt identity, and bounded value before applying the operation to staging
- **AND** the operation MUST be recorded with provenance and input/output hashes

#### Scenario: Proposal requests a structural or arbitrary edit

- **WHEN** the proposal edits coordinates, connectivity, IDs, schemas, monster identity, NPC authority, registry state, arbitrary paths, or unlisted fields
- **THEN** Python MUST reject the proposal
- **AND** the current staging revision MUST remain unchanged
- **AND** the build MUST retain a concrete finalization diagnostic

### Requirement: Provider failure is fail-closed and staging-safe

Provider timeout, quota failure, malformed output, or unavailable credentials MUST leave the current staging revision intact, persist a bounded failure result, and prevent publication.

#### Scenario: Resolution provider is unavailable

- **WHEN** the LLM call cannot complete
- **THEN** the pipeline MUST record the provider failure class and failed stage
- **AND** it MUST NOT mutate live module files or fabricate a fallback location

### Requirement: Finalization Attempts Are Bounded

The convergence finalizer MUST enforce a fixed maximum number of proposal rounds, per-call timeout, and per-round operation budget.

#### Scenario: Finalization budget is exhausted

- **WHEN** the staged module remains blocked after the configured maximum finalization attempts
- **THEN** the pipeline MUST persist one terminal bounded blocker report
- **AND** it MUST not retry automatically or promote the module

#### Scenario: Accepted repair is applied

- **WHEN** Python accepts a finalization proposal
- **THEN** the relevant deterministic checks MUST run again before another proposal round
- **AND** the complete schema, readiness, gameplay, semantic, and publication gates MUST run before promotion

### Requirement: Legacy paths remain isolated

The LLM-assisted semantic resolution stage MUST run only for the adaptation publication convergence path.

#### Scenario: Legacy module build runs

- **WHEN** a non-adaptation ModuleBuilder build executes
- **THEN** the new semantic resolution stage MUST NOT run
- **AND** existing legacy spatial, semantic, and publication behavior MUST remain available
