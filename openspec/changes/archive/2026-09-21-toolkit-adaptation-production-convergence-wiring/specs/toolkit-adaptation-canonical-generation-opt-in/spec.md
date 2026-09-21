## Purpose

Provides an explicit operator opt-in for bounded canonical monster stat completion while preserving reuse-first resolution, Python-owned identity authority, schema verification, and staging-only writes.

## ADDED Requirements

### Requirement: Canonical stat generation SHALL be explicitly opt-in

Canonical monster stat generation for adaptation builds SHALL require an explicit operator-controlled opt-in represented in Python-owned provenance. The opt-in SHALL default to `False`, and adaptation builds without it SHALL retain reuse-first resolution and fail closed on unresolved canonical references.

#### Scenario: Generation opt-in is disabled

- **WHEN** an approved canonical monster has no schema-sufficient reusable artifact and canonical generation opt-in is `False`, missing, or invalid
- **THEN** the build SHALL not invoke canonical stat generation
- **AND** the unresolved reference SHALL remain a bounded guardrail blocker

#### Scenario: Generation opt-in is enabled

- **WHEN** an approved canonical monster has no schema-sufficient reusable artifact, explicit generation opt-in is `True`, and the adaptation staging revision is eligible for generation
- **THEN** the build MAY request bounded canonical stat completion
- **AND** the request SHALL remain scoped to the approved canonical identity

### Requirement: Reuse-first resolution SHALL search all supplied roots

Before generation, adaptation materialization SHALL search every explicitly supplied reusable root and compendium source in deterministic order. Exact canonical artifacts and descriptive or quantity-bearing filenames whose payload carries the exact approved canonical name SHALL be eligible for reuse when schema-sufficient.

#### Scenario: A later reusable root contains the artifact

- **WHEN** an earlier reusable root has no schema-sufficient match and a later supplied root contains an exact or payload-named canonical artifact
- **THEN** the later artifact SHALL be reused before any provider generation attempt
- **AND** the source root SHALL remain unchanged

#### Scenario: Reusable artifacts are incomplete

- **WHEN** every supplied reusable artifact omits required monster fields or has a mismatched payload identity
- **THEN** those artifacts SHALL be rejected as reuse candidates
- **AND** generation SHALL remain subject to the explicit opt-in and approved-identity checks

### Requirement: Generated canonical stats SHALL preserve identity and schema

Any generated monster artifact SHALL use the exact approved canonical identity, required schema fields, bounded mechanical values, and the canonical staging filename. Provider output SHALL not rename, substitute, add, or remove monster identities.

#### Scenario: Approved identity receives valid mechanics

- **WHEN** generation returns schema-sufficient mechanics whose payload name matches the approved canonical identity exactly
- **THEN** Python SHALL persist the artifact only in the active staging monster directory
- **AND** the guardrail SHALL record the generated identity, source context, bounded generation policy, and schema verification result

#### Scenario: Provider substitutes an identity

- **WHEN** generation returns a payload whose name or canonical identity differs from the approved identity
- **THEN** Python SHALL reject the artifact
- **AND** no generated file SHALL be accepted by closure or written to a live module

### Requirement: Generation failures SHALL fail closed without live side effects

Timeout, provider failure, malformed output, incomplete schema, unsafe output path, or identity mismatch during canonical stat completion SHALL produce a bounded failure classification and SHALL not mutate live modules, registry, campaign, or prior staging revisions.

#### Scenario: Staging generation fails

- **WHEN** canonical stat completion fails after the adaptation staging revision is reserved
- **THEN** the failed attempt SHALL retain bounded diagnostics and identity metadata
- **AND** live module, registry, and campaign artifacts SHALL remain byte-unchanged
